"""PTG vs FORCE Built-in Paging Performance Benchmark.

Measures page table generation time at multiple scale points (10, 100, 500, 1000
mappings), comparing PTG (external page table generator) against FORCE built-in
VmasControlBlock paging triggered by genInstruction.
"""
import time
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend


class MainSequence(Sequence):
    def generate(self, **kargs):
        scale_points = [10, 100, 500, 1000]

        self.notice("=" * 70)
        self.notice("  PTG vs FORCE Built-in Paging Performance Benchmark")
        self.notice("  Single-stage Sv39 | 4KB pages only")
        self.notice("=" * 70)
        header = (
            f"{'Mappings':>10} | {'PTG (s)':>12} | {'FORCE (s)':>12} |"
            f" {'Speedup':>8}"
        )
        self.notice(header)
        self.notice("-" * 70)

        for n in scale_points:
            t0 = time.perf_counter()

            ptg = PtgBackend()
            ctx_id = ptg.create_s_stage_context(
                sv_mode="Sv39",
                asid=1,
                pa_base=0x80000000,
                pa_limit=0x90000000,
            )
            ptg.generate_random(
                ctx_id,
                "S",
                va_start=0x10000,
                va_end=0x10000000,
                pa_start=0x88000000,
                pa_end=0x8C000000,
                sv_mode="Sv39",
                count=n,
                seed=42,
                flags_a=1,
                flags_d=1,
            )
            val_result = ptg.validate(ctx_id)
            assert val_result.all_ok, f"PTG validation failed at n={n}"
            ptg.load_to_force(ctx_id, "S", self.genThread)
            ptg_time = time.perf_counter() - t0
            ptg.destroy()

            t1 = time.perf_counter()
            for _ in range(n):
                self.genInstruction("LD##RISCV")
            force_time = time.perf_counter() - t1

            speedup = force_time / ptg_time if ptg_time > 0 else 0
            self.notice(
                f"{n:>10} | {ptg_time:>12.6f} | {force_time:>12.6f} |"
                f" {speedup:>7.2f}x"
            )

        self.notice("=" * 70)
        self.notice("Benchmark complete")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
