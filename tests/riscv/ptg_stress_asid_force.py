"""PTG Stress Test: ASID Wrap-Around and Cycling.

Creates multiple two-stage contexts with different ASID values
(0, 1, 100, 1000, 65535) and tests that ASID switching works
correctly in vsatp. Each context has its own page table tree.
Validates translations as ASID is cycled through.

Run:
  bin/friscv -t tests/riscv/ptg_stress_asid_force.py
"""

from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend

SATP_MODE_MAP = {
    "Bare": 0, "Sv32": 1, "Sv39": 8, "Sv48": 9, "Sv57": 10,
    "Sv39x4": 8, "Sv48x4": 9, "Sv57x4": 10,
}
PPN_MASK_44 = (1 << 44) - 1


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 72)
        self.notice("  PTG STRESS TEST: ASID Wrap-Around & Cycling")
        self.notice("  Mode: VS-stage Sv39 | G-stage Sv39x4")
        self.notice("=" * 72)

        # ASID values to test (16-bit range: 0 - 65535)
        asid_values = [0, 1, 100, 1000, 65535]
        num_asids = len(asid_values)

        ptg = PtgBackend()

        # ------------------------------------------------------------------
        # Step 1: Create one context per ASID value
        # ------------------------------------------------------------------
        self.notice("\n[Step 1] Creating contexts for each ASID value")
        ctx_ids = []
        for asid in asid_values:
            ctx = ptg.create_two_stage_context(
                vs_mode="Sv39",
                gs_mode="Sv39x4",
                asid=asid,
                vmid=asid,
                gpa_base=0x80000000,
                gpa_limit=0x81000000,
                pa_base=0x100000000,
                pa_limit=0x110000000,
            )
            ctx_ids.append(ctx)
            self.notice(f"  Context {ctx}: ASID={asid}, VMID={asid}")

        # ------------------------------------------------------------------
        # Step 2: Configure mappings for each context
        #         Each context maps a private VA page to a unique SPA region
        # ------------------------------------------------------------------
        self.notice("\n[Step 2] Configuring per-context mappings")
        for idx, ctx in enumerate(ctx_ids):
            asid = asid_values[idx]
            # Unique GVA for each context to verify isolation
            gva_base = 0x80000000 + idx * 0x100000
            gpa_base = 0x80000000 + idx * 0x100000
            spa_base = 0x100000000 + idx * 0x100000

            # G-stage: map GPA -> SPA (2MB superpage)
            ptg.handle.add_mapping(ctx, "G", gpa_base, spa_base, 0x200000, 0, 7)
            ptg.generate_random(
                ctx, "G",
                va_start=gpa_base, va_end=gpa_base + 0x200000,
                pa_start=spa_base, pa_end=spa_base + 0x200000,
                sv_mode="Sv39x4", count=1, seed=100 + idx,
                size_2mb_weight=1.0, size_4kb_weight=0.0,
                flags_a=1, flags_d=1,
            )
            # VS-stage: map GVA -> GPA (4KB)
            ptg.handle.add_mapping(ctx, "VS", gva_base, gpa_base, 4096, 0, 7)
            ptg.generate_random(
                ctx, "VS",
                va_start=gva_base, va_end=gva_base + 4096,
                pa_start=gpa_base, pa_end=gpa_base + 4096,
                sv_mode="Sv39", count=1, seed=200 + idx,
                flags_a=1, flags_d=1,
            )
            self.notice(f"  Context ASID={asid:>5}: GVA 0x{gva_base:08X} -> "
                        f"GPA 0x{gpa_base:08X} -> SPA 0x{spa_base:010X}")

        # ------------------------------------------------------------------
        # Step 3: Validate all contexts
        # ------------------------------------------------------------------
        self.notice("\n[Step 3] Validating all contexts")
        all_valid = True
        for idx, ctx in enumerate(ctx_ids):
            asid = asid_values[idx]
            vr = ptg.handle.validate(ctx)
            status = "PASS" if vr.all_ok else "FAIL"
            self.notice(f"  Context ASID={asid:>5}: all_ok={vr.all_ok} "
                        f"leaf_ptes={vr.leaf_ptes} [{status}]")
            if not vr.all_ok:
                all_valid = False

        # ------------------------------------------------------------------
        # Step 4: Load all page tables to simulator memory
        # ------------------------------------------------------------------
        self.notice("\n[Step 4] Loading page tables to simulator memory")
        for idx, ctx in enumerate(ctx_ids):
            asid = asid_values[idx]
            ptg.load_to_force(ctx, "VS", self.genThread)
            ptg.load_to_force(ctx, "G", self.genThread)
            self.notice(f"  Context ASID={asid:>5}: page tables loaded")

        # ------------------------------------------------------------------
        # Step 5: Verify per-context ASID extraction from vsatp
        # ------------------------------------------------------------------
        self.notice("\n[Step 5] Verifying vsatp ASID encoding")
        for idx, ctx in enumerate(ctx_ids):
            asid = asid_values[idx]
            vsatp_val = ptg.handle.get_vsatp(ctx)
            encoded_asid = (vsatp_val >> 44) & 0xFFFF
            asid_match = (encoded_asid == asid)
            marker = "OK" if asid_match else "MISMATCH"
            self.notice(f"  Context ASID={asid:>5}: vsatp encoded ASID={encoded_asid:>5} "
                        f"[{marker}]")

        # ------------------------------------------------------------------
        # Step 6: Rapid ASID cycling test
        #         Switch between contexts, verifying each translation works
        # ------------------------------------------------------------------
        self.notice("\n[Step 6] Rapid ASID cycling...")
        switch_count = 500  # 500 switches across 5 ASIDs = 100 per ASID
        ok_switches = 0
        fault_switches = 0

        for i in range(switch_count):
            # Round-robin through ASID contexts
            idx = i % num_asids
            ctx = ctx_ids[idx]
            asid = asid_values[idx]
            expected_spa = 0x100000000 + idx * 0x100000
            test_gva = 0x80000000 + idx * 0x100000

            # Write full vsatp (including ASID field) and hgatp CSRs
            vsatp_val = ptg.handle.get_vsatp(ctx)
            hgatp_val = ptg.handle.get_hgatp(ctx)
            vs_mode_val = SATP_MODE_MAP["Sv39"]
            hg_mode_val = SATP_MODE_MAP["Sv39x4"]
            vs_ppn = vsatp_val & PPN_MASK_44
            hg_vmid = (hgatp_val >> 44) & 0x3FFF
            hg_ppn = hgatp_val & PPN_MASK_44
            vsatp_csr = (vs_mode_val << 60) | (asid << 44) | vs_ppn
            hgatp_csr = (hg_mode_val << 60) | (hg_vmid << 44) | hg_ppn
            self.genThread.writeRegister("vsatp", "", vsatp_csr, False)
            self.genThread.writeRegister("hgatp", "", hgatp_csr, False)

            # Verify translation through PTG
            spa, vs_code, g_code = ptg.handle.translate_sequential(ctx, test_gva, 0)
            if vs_code == 0 and g_code == 0 and spa == expected_spa:
                ok_switches += 1
            else:
                fault_switches += 1
                if fault_switches <= 3:
                    self.notice(f"  Switch {i}: ASID={asid} GVA 0x{test_gva:08X} "
                                f"-> SPA 0x{spa:010X} (expected 0x{expected_spa:010X}) "
                                f"vs={vs_code} g={g_code}")

            # Generate an instruction under this ASID context
            self.genInstruction("ADD##RISCV")

            # Print periodic progress
            if (i + 1) % 100 == 0:
                self.notice(f"  ... {i+1} ASID switches completed ({ok_switches} OK, "
                            f"{fault_switches} faults)")

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        self.notice("\n" + "=" * 72)
        self.notice("  ASID STRESS TEST SUMMARY")
        self.notice(f"  ASID values tested      : {asid_values}")
        self.notice(f"  All contexts valid      : {'YES' if all_valid else 'NO'}")
        self.notice(f"  ASID switches performed : {switch_count}")
        self.notice(f"  Translations OK         : {ok_switches}")
        self.notice(f"  Translation faults      : {fault_switches}")
        self.notice("=" * 72)

        ptg.destroy()
        self.notice("ASID stress test complete.")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
