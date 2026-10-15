"""PTG integration path micro-benchmark.

Run: bin/friscv -t tests/riscv/ptg_integration_perf_force.py
"""
import time
import ctypes
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend, PtgRandomConfig


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 70)
        self.notice("  PTG Integration Path Micro-Benchmarks")
        self.notice("=" * 70)

        kwargs = {"access_types": 7, "default_perm": 0, "flags_a": 1,
                  "flags_d": 1, "force_new": 1, "merge_probability": 1.0}

        cfg = PtgRandomConfig()
        self._bench("struct fill (34 direct fields)",
                    lambda: self._fill_struct(cfg), 2000)
        self._bench("struct fill (dict kwargs wrapper)",
                    lambda: self._fill_struct_kwargs(cfg, kwargs), 2000)

        ptg = PtgBackend()
        for n in [10, 100, 500, 1000]:
            reps = max(1, 100 // n)
            t0 = time.perf_counter()
            for _ in range(reps):
                ctx = ptg.create_s_stage_context(
                    sv_mode="Sv39", asid=1,
                    pa_base=0x80000000, pa_limit=0x90000000)
                ptg.generate_random(
                    ctx, "S", va_start=0x10000, va_end=0x10000000,
                    pa_start=0x88000000, pa_end=0x8C000000,
                    sv_mode="Sv39", count=n, seed=42, flags_a=1, flags_d=1)
            t = (time.perf_counter() - t0) / reps * 1e3
            self.notice(f"  generate_random (n={n}){'':>33s} {t:>8.2f} ms")

        ctx = ptg.create_s_stage_context(
            sv_mode="Sv39", asid=2,
            pa_base=0x80000000, pa_limit=0x90000000)
        ptg.generate_random(
            ctx, "S", va_start=0x20000, va_end=0x20000000,
            pa_start=0x88000000, pa_end=0x8C000000,
            sv_mode="Sv39", count=1000, seed=99, flags_a=1, flags_d=1)

        n_cb, sz_total = [0], [0]
        def _cb(pa, dptr, size, ud):
            n_cb[0] += 1
            sz_total[0] += size
            self.genThread.writePhysicalMemory(pa, ctypes.string_at(dptr, size), 0)

        WRITE_FN = ctypes.CFUNCTYPE(None, ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.c_void_p)
        timed_cb = WRITE_FN(_cb)
        t0 = time.perf_counter()
        ptg.handle._lib.ptg_dump_binary_write(
            ptg.handle._handle, ctx, 0, timed_cb, None)
        t_dump = time.perf_counter() - t0
        label = "  dump_binary_write (n=1000)"
        self.notice(label + " " * (40 - len(label)) + f"{t_dump*1e6:>8.2f} us")
        self.notice(f"    blocks={n_cb[0]}, size={sz_total[0]}, "
                    f"per_block={t_dump/n_cb[0]*1e6:.2f} us")

        reps = 1000
        t0 = time.perf_counter()
        for _ in range(reps):
            ptg.translate(ctx, 0x20000)
        t0 = (time.perf_counter() - t0) / reps * 1e6
        label = "  translate ctypes call"
        self.notice(label + " " * (45 - len(label)) + f"{t0:>8.2f} us")

        t0 = time.perf_counter()
        for _ in range(reps):
            ptg.handle.get_satp(ctx)
        t0 = (time.perf_counter() - t0) / reps * 1e6
        label = "  get_satp ctypes call"
        self.notice(label + " " * (45 - len(label)) + f"{t0:>8.2f} us")

        ptg.destroy()
        self.notice("=" * 70)
        self.notice("Benchmark complete")

    def _bench(self, label, fn, reps):
        t0 = time.perf_counter()
        for _ in range(reps):
            fn()
        self.notice(f"  {label:<45s} {((time.perf_counter()-t0)/reps*1e6):>8.2f} us")

    def _fill_struct(self, cfg):
        cfg.va_start = 0x10000
        cfg.va_end = 0x10000000
        cfg.pa_start = 0x88000000
        cfg.pa_end = 0x8C000000
        cfg.min_mappings = 100
        cfg.max_mappings = 100
        cfg.seed = 42
        cfg.sv_mode = 8
        cfg.access_types = 7
        cfg.default_perm = 0
        cfg.flags_a = 1
        cfg.flags_d = 1
        cfg.flags_g = cfg.flags_u = 0
        cfg.size_4kb_weight = 1.0
        cfg.size_2mb_weight = cfg.size_1gb_weight = cfg.size_512gb_weight = 0.0
        cfg.force_new = 1
        cfg.merge_probability = 1.0
        cfg.pbmte = cfg.adue = 1
        cfg.sum = cfg.mxr = cfg.sse = 0
        cfg.ss_probability = 0.0
        cfg.gs_inherit = cfg.gs_conflict_mode = 0
        cfg.fault_cause = cfg.fault_type = cfg.fault_level = 0
        cfg.fault_probability = 0.0
        cfg.fault_random_cause = 0
        cfg.fault_seed = 0

    def _fill_struct_kwargs(self, cfg, kwargs):
        cfg.va_start = 0x10000
        cfg.va_end = 0x10000000
        cfg.pa_start = 0x88000000
        cfg.pa_end = 0x8C000000
        cfg.min_mappings = 100
        cfg.max_mappings = 100
        cfg.seed = 42
        cfg.sv_mode = 8
        cfg.access_types = kwargs.get("access_types", 7)
        cfg.default_perm = kwargs.get("default_perm", 0)
        cfg.flags_a = kwargs.get("flags_a", 0)
        cfg.flags_d = kwargs.get("flags_d", 0)
        cfg.force_new = kwargs.get("force_new", 1)
        cfg.merge_probability = kwargs.get("merge_probability", 1.0)
        cfg.size_4kb_weight = kwargs.get("size_4kb_weight", 1.0)
        cfg.size_2mb_weight = kwargs.get("size_2mb_weight", 0.0)
        cfg.size_1gb_weight = kwargs.get("size_1gb_weight", 0.0)
        cfg.size_512gb_weight = kwargs.get("size_512gb_weight", 0.0)


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
