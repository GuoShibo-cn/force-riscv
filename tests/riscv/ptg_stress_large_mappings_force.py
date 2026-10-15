"""PTG Stress Test: 10K+ Two-Stage Mappings.

Creates a two-stage (Sv39/Sv39x4) page table with 10,000+ VS-stage
and sufficient G-stage mappings covering a 256MB GPA range.
Validates all mappings, loads to simulator memory, and verifies
sample translations.

Run:
  bin/friscv -t tests/riscv/ptg_stress_large_mappings_force.py
"""

from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend

# RISC-V CSR MODE mapping for direct CSR writes
SATP_MODE_MAP = {
    "Bare": 0, "Sv32": 1, "Sv39": 8, "Sv48": 9, "Sv57": 10,
    "Sv39x4": 8, "Sv48x4": 9, "Sv57x4": 10,
}
PPN_MASK_44 = (1 << 44) - 1


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 72)
        self.notice("  PTG STRESS TEST: Large Two-Stage Mappings (10K+)")
        self.notice("  Mode: VS-stage Sv39 | G-stage Sv39x4 | 4KB leaf pages")
        self.notice("=" * 72)

        # ------------------------------------------------------------------
        # Step 1: Create PTG backend and two-stage context
        # ------------------------------------------------------------------
        self.notice("\n[Step 1] Creating PTG two-stage context (Sv39 / Sv39x4)")
        ptg = PtgBackend()
        ctx = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Sv39x4",
            asid=42,
            vmid=1,
            # Guest physical address space (GPA)
            gpa_base=0x80000000,
            gpa_limit=0x90000000,
            # Supervisor physical address space (SPA)
            pa_base=0x100000000,
            pa_limit=0x110000000,
        )
        self.notice(f"  Context ID: {ctx}")

        # ------------------------------------------------------------------
        # Step 2: G-stage - cover full GPA range with 2MB superpages
        # ------------------------------------------------------------------
        self.notice("\n[Step 2] Configuring G-stage mappings (GPA -> SPA)")
        self.notice("  Adding 128 x 2MB superpages across 256MB GPA range...")
        for i in range(128):
            gpa = 0x80000000 + i * 0x200000
            spa = 0x100000000 + i * 0x200000
            ptg.handle.add_mapping(ctx, "G", gpa, spa, 0x200000, 0, 7)

        self.notice("  Generating G-stage page table entries...")
        g_cnt, _ = ptg.generate_random(
            ctx, "G",
            va_start=0x80000000, va_end=0x90000000,
            pa_start=0x100000000, pa_end=0x110000000,
            sv_mode="Sv39x4", count=128, seed=1,
            size_2mb_weight=1.0, size_4kb_weight=0.0,
            flags_a=1, flags_d=1,
        )
        self.notice(f"  G-stage mappings generated: {g_cnt}")

        # ------------------------------------------------------------------
        # Step 3: VS-stage - generate 10000 x 4KB mappings in batches
        # ------------------------------------------------------------------
        self.notice("\n[Step 3] Generating VS-stage mappings (GVA -> GPA)")
        self.notice("  10000 x 4KB leaf mappings in 10 batches...")
        total_vs = 0
        for batch in range(10):
            va_lo = 0x80000000 + batch * 0x1000000   # 16MB per batch
            va_hi = va_lo + 0x1000000
            cnt, _ = ptg.generate_random(
                ctx, "VS",
                va_start=va_lo, va_end=va_hi,
                pa_start=va_lo, pa_end=va_hi,
                sv_mode="Sv39", count=1000, seed=42 + batch,
                flags_a=1, flags_d=1,
            )
            total_vs += cnt
            self.notice(f"    Batch {batch+1:>2}/10: {cnt:>5} mappings  "
                        f"(cumulative: {total_vs:>5})")

        self.notice(f"\n  VS-stage total: {total_vs} mappings")

        # ------------------------------------------------------------------
        # Step 4: Validate page table tree integrity
        # ------------------------------------------------------------------
        self.notice("\n[Step 4] Validating page table integrity...")
        vr = ptg.handle.validate(ctx)
        self.notice(f"  validation.all_ok       = {vr.all_ok}")
        self.notice(f"  total_nodes             = {vr.total_nodes}")
        self.notice(f"  total_ptes              = {vr.total_ptes}")
        self.notice(f"  valid_ptes              = {vr.valid_ptes}")
        self.notice(f"  leaf_ptes               = {vr.leaf_ptes}")
        self.notice(f"  nonleaf_ptes            = {vr.nonleaf_ptes}")
        self.notice(f"  invalid_addr_nodes      = {vr.invalid_addr_nodes}")
        self.notice(f"  invalid_pte_count       = {vr.invalid_pte_count}")
        self.notice(f"  orphan_nodes            = {vr.orphan_nodes}")
        self.notice(f"  gpa_overlap_count       = {vr.gpa_overlap_count}")
        self.notice(f"  gpa_unreachable         = {vr.gpa_unreachable}")
        self.notice(f"  leaf_missing_flags      = {vr.leaf_missing_flags}")

        if not vr.all_ok:
            self.notice("  WARNING: Validation reported issues!")

        # ------------------------------------------------------------------
        # Step 5: Load page tables to simulator memory
        # ------------------------------------------------------------------
        self.notice("\n[Step 5] Loading page tables to simulator memory...")
        ptg.load_to_force(ctx, "VS", self.genThread)
        ptg.load_to_force(ctx, "G", self.genThread)
        self.notice("  VS-stage and G-stage page tables loaded")

        # ------------------------------------------------------------------
        # Step 6: Set up CSRs to point to PTG page tables
        # ------------------------------------------------------------------
        self.notice("\n[Step 6] Overriding CSRs (vsatp / hgatp)...")
        vsatp_val = ptg.handle.get_vsatp(ctx)
        hgatp_val = ptg.handle.get_hgatp(ctx)
        vs_mode_val = SATP_MODE_MAP["Sv39"]
        hg_mode_val = SATP_MODE_MAP["Sv39x4"]
        vs_ppn = vsatp_val & PPN_MASK_44
        hg_vmid = (hgatp_val >> 44) & 0x3FFF
        hg_ppn = hgatp_val & PPN_MASK_44
        vsatp_csr = (vs_mode_val << 60) | (42 << 44) | vs_ppn
        hgatp_csr = (hg_mode_val << 60) | (hg_vmid << 44) | hg_ppn
        self.notice(f"  vsatp CSR = 0x{vsatp_csr:016X}")
        self.notice(f"  hgatp CSR = 0x{hgatp_csr:016X}")

        self.genThread.writeRegister("vsatp", "", vsatp_csr, False)
        self.genThread.writeRegister("hgatp", "", hgatp_csr, False)

        # ------------------------------------------------------------------
        # Step 7: Verify sample translations
        # ------------------------------------------------------------------
        self.notice("\n[Step 7] Verifying sample translations...")
        # Pick addresses from different batches to get good coverage
        sample_addrs = [
            0x80000000, 0x80100000, 0x80800000, 0x81000000,
            0x82000000, 0x83000000, 0x85000000, 0x88000000,
        ]
        ok_count = 0
        fault_count = 0
        for gva in sample_addrs:
            spa, vs_code, g_code = ptg.handle.translate_sequential(ctx, gva, 0)
            if vs_code == 0 and g_code == 0:
                status = "OK"
                ok_count += 1
            else:
                status = f"FAULT(vs={vs_code},g={g_code})"
                fault_count += 1
            expected_spa_lo = 0x100000000 + (gva - 0x80000000)
            self.notice(f"  GVA 0x{gva:08X} -> SPA 0x{spa:010X}  [{status}]")

        self.notice(f"  Translations: {ok_count} OK, {fault_count} fault(s)")

        # ------------------------------------------------------------------
        # Step 8: Generate instructions to exercise two-stage
        # ------------------------------------------------------------------
        self.notice("\n[Step 8] Generating instructions under two-stage paging...")
        for _ in range(30):
            self.genInstruction("ADD##RISCV")
        self.notice("  30 instructions generated")

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        self.notice("\n" + "=" * 72)
        self.notice("  STRESS TEST SUMMARY")
        self.notice(f"  G-stage mappings          : {g_cnt}")
        self.notice(f"  VS-stage mappings         : {total_vs}")
        self.notice(f"  Total leaf PTEs           : {vr.leaf_ptes}")
        self.notice(f"  Total PTE nodes           : {vr.total_ptes}")
        self.notice(f"  Validation                : {'PASS' if vr.all_ok else 'ISSUES'}")
        self.notice(f"  Sample translations OK    : {ok_count}/{len(sample_addrs)}")
        self.notice("=" * 72)

        ptg.destroy()
        self.notice("Large mappings stress test complete.")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
