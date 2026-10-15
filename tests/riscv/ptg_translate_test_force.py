"""Phase 2.4.2c: Debug VS-stage page table placement."""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("Phase 2.4.2c: VS-stage node address debug")
        self.notice("=" * 60)

        ptg = PtgBackend()
        ctx_id = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Sv39x4",
            asid=0,
            vmid=1,
            pa_base=0x80000000,
            pa_limit=0x80200000,
            gpa_base=0x80000000,
            gpa_limit=0x80200000,
        )
        self.notice(f"Context ID: {ctx_id}")

        va = 0x80000000
        size = 4096
        self.notice("\n[T1] Add identity mappings (VS and G)")
        ptg.handle.add_mapping(ctx_id, "VS", va, va, size, 0, 0b111)
        ptg.handle.add_mapping(ctx_id, "G",  va, va, size, 0, 0b111)

        self.notice("\n[T2] Generate page tables")
        vs_result = ptg.generate_random(ctx_id, "VS", va, va + size, va, va + size,
                                         "Sv39", 1, seed=42)
        g_result = ptg.generate_random(ctx_id, "G", va, va + size, va, va + size,
                                        "Sv39x4", 1, seed=43, gs_inherit=1)
        self.notice(f"  VS: {vs_result[0]} mappings")
        self.notice(f"  G:  {g_result[0]} mappings")

        self.notice("\n[T3] Try validate to check consistency")
        try:
            result = ptg.handle.validate(ctx_id)
            self.notice(f"  validate: all_ok={result.all_ok}, total_nodes={result.total_nodes}, leaf_ptes={result.leaf_ptes}")
        except Exception as e:
            self.notice(f"  validate failed: {e}")

        self.notice("\n[T4] Check debug functions")
        try:
            dbg = ptg.handle.debug_implicit_guest_fault(ctx_id, 0.5, va)
            self.notice(f"  debug_implicit: {dbg}")
        except Exception as e:
            self.notice(f"  debug_implicit not available: {e}")

        self.notice("\n[T5] Test translations")
        result = ptg.handle.translate_sequential(ctx_id, va, 0)
        spa, fault_code, fault_level = result
        self.notice(f"  GVA 0x{va:X}: SPA=0x{spa:X} fault_code={fault_code} fault_level={fault_level}")

        self.notice("\n[T6] Try with larger G-stage mapping (512MB superpage)")
        ptg.handle.add_mapping(ctx_id, "G", 0x0, 0x0, 0x40000000, 0, 0b111)
        try:
            ptg.generate_random(ctx_id, "G", 0x0, 0x40000000, 0x0, 0x40000000,
                                "Sv39x4", 1, seed=44, gs_inherit=1,
                                size_1gb_weight=1.0, size_4kb_weight=0.0,
                                size_2mb_weight=0.0)
        except Exception as e:
            self.notice(f"  large G generate FAILED: {e}")

        result = ptg.handle.translate_sequential(ctx_id, va, 0)
        spa, fault_code, fault_level = result
        self.notice(f"  After big G mapping: SPA=0x{spa:X} fault={fault_code} level={fault_level}")

        self.notice("\n" + "=" * 60)
        ptg.destroy()


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
