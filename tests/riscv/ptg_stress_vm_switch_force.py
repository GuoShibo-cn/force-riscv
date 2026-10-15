"""PTG Stress Test: Rapid VM Context Switching.

Creates 4 separate two-stage VM contexts with distinct vsatp/hgatp
configurations, then rapidly switches between them 1000+ times.
Each switch verifies address translation still works, testing TLB
invalidation semantics and multi-VM isolation.

Run:
  bin/friscv -t tests/riscv/ptg_stress_vm_switch_force.py
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
        self.notice("  PTG STRESS TEST: Rapid VM Context Switching")
        self.notice("  Mode: VS-stage Sv39 | G-stage Sv39x4")
        self.notice("=" * 72)

        ptg = PtgBackend()

        # 4 VM contexts with different VMIDs
        vm_configs = [
            {"vmid": 1, "gva": 0x80000000, "gpa": 0x80000000, "spa": 0x100000000},
            {"vmid": 2, "gva": 0x82000000, "gpa": 0x82000000, "spa": 0x102000000},
            {"vmid": 3, "gva": 0x84000000, "gpa": 0x84000000, "spa": 0x104000000},
            {"vmid": 4, "gva": 0x86000000, "gpa": 0x86000000, "spa": 0x106000000},
        ]
        num_vms = len(vm_configs)

        # ------------------------------------------------------------------
        # Step 1: Create contexts and configure mappings
        # ------------------------------------------------------------------
        self.notice("\n[Step 1] Creating 4 VM contexts with private address regions")
        ctx_ids = []
        for cfg in vm_configs:
            ctx = ptg.create_two_stage_context(
                vs_mode="Sv39",
                gs_mode="Sv39x4",
                asid=cfg["vmid"],
                vmid=cfg["vmid"],
                gpa_base=cfg["gpa"],
                gpa_limit=cfg["gpa"] + 0x200000,
                pa_base=cfg["spa"],
                pa_limit=cfg["spa"] + 0x200000,
            )
            ctx_ids.append(ctx)
            self.notice(f"  VM{cfg['vmid']}: Context {ctx} | "
                        f"GVA 0x{cfg['gva']:08X} -> GPA 0x{cfg['gpa']:08X} -> "
                        f"SPA 0x{cfg['spa']:010X}")

        # ------------------------------------------------------------------
        # Step 2: Configure G-stage and VS-stage per context
        # ------------------------------------------------------------------
        self.notice("\n[Step 2] Configuring page tables for each VM")
        for idx, ctx in enumerate(ctx_ids):
            cfg = vm_configs[idx]
            gva = cfg["gva"]
            gpa = cfg["gpa"]
            spa = cfg["spa"]

            # G-stage: 2MB superpage GPA -> SPA
            ptg.handle.add_mapping(ctx, "G", gpa, spa, 0x200000, 0, 7)
            ptg.generate_random(
                ctx, "G",
                va_start=gpa, va_end=gpa + 0x200000,
                pa_start=spa, pa_end=spa + 0x200000,
                sv_mode="Sv39x4", count=1, seed=100 + idx,
                size_2mb_weight=1.0, size_4kb_weight=0.0,
                flags_a=1, flags_d=1,
            )

            # VS-stage: 4 x 4KB mappings within 2MB GPA window
            for page in range(4):
                page_offset = page * 4096
                ptg.handle.add_mapping(ctx, "VS",
                                       gva + page_offset, gpa + page_offset,
                                       4096, 0, 7)
            ptg.generate_random(
                ctx, "VS",
                va_start=gva, va_end=gva + 0x200000,
                pa_start=gpa, pa_end=gpa + 0x200000,
                sv_mode="Sv39", count=4, seed=200 + idx,
                flags_a=1, flags_d=1,
            )
            self.notice(f"  VM{cfg['vmid']}: 1 G-stage + 4 VS-stage mappings configured")

        # ------------------------------------------------------------------
        # Step 3: Validate all contexts
        # ------------------------------------------------------------------
        self.notice("\n[Step 3] Validating all VM contexts")
        all_valid = True
        for idx, ctx in enumerate(ctx_ids):
            vmid = vm_configs[idx]["vmid"]
            vr = ptg.handle.validate(ctx)
            status = "PASS" if vr.all_ok else "FAIL"
            self.notice(f"  VM{vmid}: all_ok={vr.all_ok} leaf_ptes={vr.leaf_ptes} "
                        f"[{status}]")
            if not vr.all_ok:
                all_valid = False

        # ------------------------------------------------------------------
        # Step 4: Load all page tables to simulator memory
        # ------------------------------------------------------------------
        self.notice("\n[Step 4] Loading page tables into simulator memory")
        for idx, ctx in enumerate(ctx_ids):
            vmid = vm_configs[idx]["vmid"]
            ptg.load_to_force(ctx, "VS", self.genThread)
            ptg.load_to_force(ctx, "G", self.genThread)
            self.notice(f"  VM{vmid}: page tables loaded")

        # ------------------------------------------------------------------
        # Step 5: Rapid VM context switching
        # ------------------------------------------------------------------
        self.notice("\n[Step 5] Rapid VM context switching (1000 switches)...")
        num_switches = 1000
        ok_switches = 0
        fault_switches = 0

        for i in range(num_switches):
            # Round-robin through VM contexts
            idx = i % num_vms
            ctx = ctx_ids[idx]
            cfg = vm_configs[idx]
            expected_spa = cfg["spa"]
            test_gva = cfg["gva"]

            # Write CSRs to switch to this VM context
            # Use setupPtgCSRs for hgatp (which handles VMID correctly)
            # and build vsatp directly to preserve ASID
            self.genThread.setupPtgCSRs(
                ptg_handle=ptg.handle,
                ctx_id=ctx,
                vs_mode="Sv39",
                g_mode="Sv39x4",
            )
            # Fix vsatp ASID field which setupPtgCSRs drops
            vsatp_val = ptg.handle.get_vsatp(ctx)
            vs_ppn = vsatp_val & PPN_MASK_44
            vsatp_csr = (SATP_MODE_MAP["Sv39"] << 60) | (cfg["vmid"] << 44) | vs_ppn
            self.genThread.writeRegister("vsatp", "", vsatp_csr, False)

            # TLB invalidation: flush both G-stage and VS-stage
            ptg.handle.hfence_gvma(vmid=cfg["vmid"])
            ptg.handle.sfence_vma(ctx, va=0, asid=cfg["vmid"])

            # Verify translation through PTG
            spa, vs_code, g_code = ptg.handle.translate_sequential(ctx, test_gva, 0)
            if vs_code == 0 and g_code == 0 and spa == expected_spa:
                ok_switches += 1
            else:
                fault_switches += 1
                if fault_switches <= 3:
                    self.notice(f"  Switch {i}: VM{cfg['vmid']} "
                                f"GVA 0x{test_gva:08X} -> SPA 0x{spa:010X} "
                                f"(expected 0x{expected_spa:010X}) "
                                f"vs={vs_code} g={g_code}")

            # Generate an instruction to exercise paging under this VM
            self.genInstruction("ADD##RISCV")

            # Periodic progress
            if (i + 1) % 200 == 0:
                self.notice(f"  ... {i+1} switches completed "
                            f"({ok_switches} OK, {fault_switches} faults)")

        # ------------------------------------------------------------------
        # Step 6: Final translation verification
        # ------------------------------------------------------------------
        self.notice("\n[Step 6] Final round of all VM translations")
        for idx, ctx in enumerate(ctx_ids):
            cfg = vm_configs[idx]
            expected_spa = cfg["spa"]
            test_gva = cfg["gva"]

            self.genThread.setupPtgCSRs(
                ptg_handle=ptg.handle,
                ctx_id=ctx,
                vs_mode="Sv39",
                g_mode="Sv39x4",
            )
            vsatp_val = ptg.handle.get_vsatp(ctx)
            vs_ppn = vsatp_val & PPN_MASK_44
            vsatp_csr = (SATP_MODE_MAP["Sv39"] << 60) | (cfg["vmid"] << 44) | vs_ppn
            self.genThread.writeRegister("vsatp", "", vsatp_csr, False)

            spa, vs_code, g_code = ptg.handle.translate_sequential(ctx, test_gva, 0)
            if spa == expected_spa:
                self.notice(f"  VM{cfg['vmid']}: GVA 0x{test_gva:08X} -> "
                            f"SPA 0x{spa:010X} [OK]")
            else:
                self.notice(f"  VM{cfg['vmid']}: GVA 0x{test_gva:08X} -> "
                            f"SPA 0x{spa:010X} (expected 0x{expected_spa:010X}) "
                            f"[MISMATCH] vs={vs_code} g={g_code}")

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        self.notice("\n" + "=" * 72)
        self.notice("  VM SWITCH STRESS TEST SUMMARY")
        self.notice(f"  VM contexts created      : {num_vms}")
        self.notice(f"  All validations passed   : {'YES' if all_valid else 'NO'}")
        self.notice(f"  Context switches         : {num_switches}")
        self.notice(f"  Translations OK          : {ok_switches}")
        self.notice(f"  Translation faults       : {fault_switches}")
        self.notice(f"  Success rate             : "
                    f"{100.0 * ok_switches / num_switches:.1f}%")
        self.notice("=" * 72)

        ptg.destroy()
        self.notice("VM context switch stress test complete.")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
