"""Minimal reproduction: PTG two-stage translation failure.

Expected: validate() returns all_ok=1, translate_sequential() succeeds
Actual: validate() returns all_ok=0, translate_sequential() returns vs_fault=5

Bug: VS-stage page tree nodes are allocated at GPAs outside gpa_base..gpa_limit
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend


class MainSequence(Sequence):
    def generate(self, **kargs):
        ptg = PtgBackend()

        ctx = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Sv39x4",
            asid=0,
            vmid=1,
            pa_base=0x80000000,
            pa_limit=0x80400000,
            gpa_base=0x80000000,
            gpa_limit=0x80400000,
        )
        self.notice(f"Context ID: {ctx}")

        va = 0x80000000
        size = 4096
        perm = 0b111

        self.notice("Step 1: Add identity mappings in both stages")
        ptg.handle.add_mapping(ctx, "VS", va, va, size, 0, perm)
        ptg.handle.add_mapping(ctx, "G",  va, va, size, 0, perm)

        self.notice("Step 2: Generate page tables for both stages (with gs_inherit=1)")
        vs_result = ptg.generate_random(ctx, "VS", va, va + size, va, va + size,
                                        "Sv39", 1, seed=123)
        g_result = ptg.generate_random(ctx, "G", va, va + size, va, va + size,
                                       "Sv39x4", 1, seed=456, gs_inherit=1)
        self.notice(f"  VS: {vs_result[0]} mapping(s), G: {g_result[0]} mapping(s)")

        self.notice("Step 3: PTG internal page table node addresses")
        vsatp_val = ptg.handle.get_vsatp(ctx)
        hgatp_val = ptg.handle.get_hgatp(ctx)
        vs_root_ppn = vsatp_val & 0xFFFFFFFFFFF
        g_root_ppn = hgatp_val & 0xFFFFFFFFFFF
        vs_root_gpa = vs_root_ppn << 12
        g_root_pa = g_root_ppn << 12
        self.notice(f"  VS root node GPA: 0x{vs_root_gpa:X}  (must be in gpa_base..gpa_limit)")
        self.notice(f"  G  root node PA:  0x{g_root_pa:X}")

        in_range = 0x80000000 <= vs_root_gpa < 0x80400000
        self.notice(f"  VS root GPA in G-stage range? {in_range}")
        if not in_range:
            self.notice("  *** BUG: VS root node GPA is OUTSIDE gpa_base..gpa_limit ***")
            self.notice("  *** G-stage cannot translate this GPA -> page walk fails ***")

        self.notice("Step 4: validate()")
        result = ptg.handle.validate(ctx)
        self.notice(f"  all_ok={result.all_ok}, total_nodes={result.total_nodes}, leaf_ptes={result.leaf_ptes}")

        self.notice("Step 5: translate_sequential(0x80000000)")
        spa, fault_code, fault_level = ptg.handle.translate_sequential(ctx, 0x80000000, 0)
        self.notice(f"  SPA=0x{spa:X}, fault_code={fault_code}, fault_level={fault_level}")

        self.notice("Step 6: Single-stage control test (G=Bare, should pass)")
        ctx2 = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Bare",
            asid=0,
            vmid=2,
            pa_base=0x80000000,
            pa_limit=0x80400000,
            gpa_base=0x80000000,
            gpa_limit=0x80400000,
        )
        ptg.handle.add_mapping(ctx2, "VS", va, va, size, 0, perm)
        ptg.generate_random(ctx2, "VS", va, va + size, va, va + size, "Sv39", 1, seed=789)
        result2 = ptg.handle.validate(ctx2)
        spa2, fc2, fl2 = ptg.handle.translate_sequential(ctx2, va, 0)
        self.notice(f"  all_ok={result2.all_ok}, SPA=0x{spa2:X}, fault_code={fc2}")

        self.notice("=" * 60)
        if fault_code == 0:
            self.notice("RESULT: PASS (two-stage translation succeeded)")
        else:
            self.notice("RESULT: FAIL")
            self.notice(f"  fault_code={fault_code} (5=Load Access Fault = page not accessible)")
            self.notice(f"  fault_level={fault_level} (page table level where fault occurred)")
            self.notice("  Root cause: VS-stage page tree nodes allocated at GPAs")
            self.notice("  outside gpa_base..gpa_limit, so G-stage cannot translate them")
        self.notice("=" * 60)

        ptg.destroy()


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
