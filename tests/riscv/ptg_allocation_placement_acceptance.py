"""Downstream public-ABI acceptance for checked allocation and placement.

Uses fixed expected addresses and raw PTE/layout comparisons, not maintainer test
helpers. Includes the existing independent Mapping Query/Strict Export cases.
"""

import argparse
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest

from ptg_mapping_export_acceptance import Contracts, canary
from riscv.paging.PtgBackend import PtgHandle, PtgMapping, PtgRandomConfig


class Placement(c.Structure):
    _fields_ = [
        ("struct_size", c.c_uint32), ("abi_version", c.c_uint32),
        ("pt_base", c.c_uint64), ("pt_limit", c.c_uint64), ("pt_align", c.c_uint64),
        ("flags", c.c_uint32), ("reserved0", c.c_uint32),
    ]


class Level(c.Structure):
    _fields_ = [
        ("struct_size", c.c_uint32), ("abi_version", c.c_uint32),
        ("level", c.c_int32), ("reserved0", c.c_uint32),
        ("base", c.c_uint64), ("limit", c.c_uint64),
    ]


class AllocationContracts(Contracts):
    def setUp(self):
        super().setUp()
        signatures = {
            "ptg_placement_config_v1_init": [c.c_void_p, c.c_uint32],
            "ptg_level_placement_v1_init": [c.c_void_p, c.c_uint32],
            "ptg_configure_pa_placement_v1": [
                c.c_void_p, c.c_void_p, c.c_void_p, c.c_uint32, c.c_uint32,
            ],
            "ptg_configure_gpa_placement_v1": [
                c.c_void_p, c.c_uint16, c.c_void_p, c.c_void_p, c.c_uint32, c.c_uint32,
            ],
        }
        for name, args in signatures.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = c.c_int32, args
        self.lib.ptg_generate_deterministic.argtypes = [
            c.c_void_p, c.c_uint32, c.c_int, c.POINTER(PtgMapping), c.c_uint32,
        ]
        self.lib.ptg_generate_deterministic.restype = None

    def fresh(self):
        self.h.destroy()
        self.h = PtgHandle(str(self.library))
        self.addCleanup(self.h.destroy)
        # self.lib retains the public function declarations for the same shared object.

    def policy(self, base=0, limit=0, align=0, windows=()):
        cfg = Placement()
        self.assertEqual(self.lib.ptg_placement_config_v1_init(c.byref(cfg), 40), 0)
        cfg.pt_base, cfg.pt_limit, cfg.pt_align = base, limit, align
        levels = (Level * len(windows))()
        for entry, (level, low, high) in zip(levels, windows):
            self.assertEqual(self.lib.ptg_level_placement_v1_init(c.byref(entry), 32), 0)
            entry.level, entry.base, entry.limit = level, low, high
        return cfg, levels

    def apply(self, cfg, levels, vmid=None):
        args = (self.h._handle, c.byref(cfg), levels if len(levels) else None, len(levels), 32)
        if vmid is None:
            status = self.lib.ptg_configure_pa_placement_v1(*args)
        else:
            status = self.lib.ptg_configure_gpa_placement_v1(args[0], vmid, *args[1:])
        self.assertEqual(self.h.last_error()[0], status)
        return status

    def root(self, ctx, stage="S", mode=8):
        csr = {"S": self.h.get_satp, "VS": self.h.get_vsatp, "G": self.h.get_hgatp}[stage](ctx)
        return (csr & ((1 << (22 if mode == 1 else 44)) - 1)) << 12

    def snapshot(self, ctx):
        return self.h.get_satp(ctx), self.raw(ctx, "S"), bytes(self.query(ctx, address=0x4000)[0])

    def test_allocation_abi_signed_statuses_and_copied_inputs(self):
        self.assertEqual(
            (c.sizeof(Placement), c.alignment(Placement), c.sizeof(Level)), (40, 8, 32)
        )
        self.assertEqual([getattr(Placement, f).offset for f in
                          ("pt_base", "pt_limit", "pt_align", "flags", "reserved0")],
                         [8, 16, 24, 32, 36])
        for typ, init in ((Placement, self.lib.ptg_placement_config_v1_init),
                          (Level, self.lib.ptg_level_placement_v1_init)):
            n = c.sizeof(typ)
            buf = canary(n + 16)
            self.assertEqual(init(buf, n - 1), -4)
            self.assertEqual(bytes(buf), b"\xA5" * len(buf))
            self.assertEqual(init(buf, n + 16), 0)
            value = typ.from_buffer_copy(buf)
            self.assertEqual((value.struct_size, value.abi_version), (n + 16, 1))
            self.assertEqual(bytes(buf)[n:], b"\xA5" * 16)
        cfg, levels = self.policy(windows=((2, 0xA0008000, 0xA0009000),))
        self.assertEqual(self.apply(cfg, levels), 0)
        levels[0].base, levels[0].limit = 0xA0010000, 0xA0011000
        self.assertEqual(self.root(self.ctx()), 0xA0008000)
        cfg.abi_version = 2
        self.assertEqual(self.apply(cfg, ()), -11)

    def test_allocation_b003_alignment_and_padding_not_reissued(self):
        s_ctx = self.ctx()
        self.assertEqual(self.root(s_ctx), 0xA0000000)
        g_ctx = self.ctx("G", "Sv39x4", vmid=2)
        self.assertEqual(self.root(g_ctx, "G"), 0xA0004000)
        old_s, old_g = self.h.get_satp(s_ctx), self.h.get_hgatp(g_ctx)
        self.assertEqual(self.apply(*self.policy(0xA0001000, 0xA0004000)), 0)
        fresh = self.h.create_context(3, 0)
        self.h.set_s_stage(fresh, "Sv39")
        self.assertEqual(self.h.last_error()[0], -9)
        self.assertEqual(self.h.get_satp(fresh), 0)
        self.assertEqual((self.h.get_satp(s_ctx), self.h.get_hgatp(g_ctx)), (old_s, old_g))

    def test_allocation_b004_failure_then_append_and_retry(self):
        self.fresh()
        self.h.register_pa_region(0xA0000000, 0xA0001000)
        ctx = self.h.create_context(1, 2)
        self.h.set_gs_stage(ctx, "Sv39x4")
        self.assertEqual(self.h.last_error()[0], -9)
        self.assertEqual(self.h.get_hgatp(ctx), 0)
        self.h.register_pa_region(0xA0001000, 0xA0008000)
        self.assertEqual(self.h.last_error()[0], 0)
        self.h.set_gs_stage(ctx, "Sv39x4")
        self.assertEqual(self.h.last_error()[0], 0)
        self.assertEqual(self.root(ctx, "G"), 0xA0004000)
        # Failed G-root allocation did not consume the original 4 KiB region.
        self.assertEqual(self.root(self.ctx(asid=2)), 0xA0000000)

    def test_allocation_zero_root_and_ppn_boundaries(self):
        self.fresh()
        self.h.register_pa_region(0, 0x10000)
        ctx = self.ctx()
        self.assertEqual(self.root(ctx), 0)
        self.assertNotEqual(self.h.get_satp(ctx), 0)
        self.add(ctx, "S", 0x4000, 0x84000000)
        self.assertIn(0, self.raw(ctx, "S"))
        self.assertEqual(self.query(ctx, address=0x4008)[0].matched_pa, 0x84000008)
        for mode, bits in ((1, 34), (8, 56), (9, 56), (10, 56)):
            with self.subTest(mode=mode):
                self.fresh()
                cap = 1 << bits
                self.h.register_pa_region(cap - 0x1000, cap)
                ctx = self.ctx(mode=mode)
                self.assertEqual(self.root(ctx, mode=mode), cap - 0x1000)
                self.fresh()
                self.h.register_pa_region(cap - 0x800, cap + 0x1000)
                ctx = self.h.create_context(1, 0)
                self.h.set_s_stage(ctx, mode)
                self.assertEqual(self.h.last_error()[0], -9)
                self.assertEqual(self.h.get_satp(ctx), 0)
                self.h.register_pa_region(0x100000, 0x104000)
                self.h.set_s_stage(ctx, mode)
                self.assertEqual(self.h.last_error()[0], 0)
                self.assertEqual(self.root(ctx, mode=mode), 0x100000)

    def test_allocation_overlapping_regions_rejected_no_stitch(self):
        self.fresh()
        self.h.register_pa_region(0xA0000000, 0xA0002000)
        for base, limit in ((0xA0000000, 0xA0002000), (0xA0000000, 0xA0001000),
                            (0xA0001000, 0xA0003000), (0x9FFFF000, 0xA0004000)):
            self.h.register_pa_region(base, limit)
            self.assertEqual(self.h.last_error()[0], -8)
        self.h.register_pa_region(0xA0002000, 0xA0004000)
        self.assertEqual(self.h.last_error()[0], 0)
        ctx = self.h.create_context(1, 1)
        self.h.set_gs_stage(ctx, "Sv39x4")
        self.assertEqual(self.h.last_error()[0], -9)
        self.h.register_pa_region(0xB0000000, 0xB0004000)
        self.h.set_gs_stage(ctx, "Sv39x4")
        self.assertEqual(self.h.last_error()[0], 0)
        self.assertEqual(self.root(ctx, "G"), 0xB0000000)

    def test_allocation_region_order_and_custom_alignment(self):
        self.fresh()
        self.h.register_pa_region(0xB0000001, 0xB0040000)
        self.h.register_pa_region(0xA0000000, 0xA0040000)
        self.assertEqual(self.apply(*self.policy(align=0x10000)), 0)
        ctx = self.ctx()
        self.assertEqual(self.root(ctx), 0xB0010000)
        # Alignment padding is occupied even after reducing policy alignment.
        self.assertEqual(self.apply(*self.policy(0xB0000001, 0xB0010000)), 0)
        other = self.h.create_context(2, 0)
        self.h.set_s_stage(other, "Sv39")
        self.assertEqual(self.h.last_error()[0], -9)

    def test_allocation_per_level_priority_and_general_fallback(self):
        windows = ((2, 0xA0004000, 0xA0005000), (1, 0xA0008000, 0xA0009000),
                   (0, 0xA000C000, 0xA000D000))
        self.assertEqual(self.apply(*self.policy(windows=windows)), 0)
        ctx = self.ctx()
        self.add(ctx, "S", 0x4000, 0x84000000)
        self.assertEqual(self.root(ctx), 0xA0004000)
        raw = self.raw(ctx, "S")
        self.assertEqual(set(raw), {0xA0004000, 0xA0008000, 0xA000C000})
        slot, pte, level = self.leaf(ctx, 0x4000)
        self.assertEqual((slot, (pte >> 10) << 12, level), (0xA000C020, 0x84000000, 0))
        self.assertEqual(self.root(self.ctx(asid=2)), 0xA0000000)

    def test_allocation_level_window_order_not_address_sort(self):
        self.assertEqual(self.apply(*self.policy(windows=(
            (2, 0xA0008000, 0xA0009000), (2, 0xA0004000, 0xA0005000)
        ))), 0)
        self.assertEqual(self.root(self.ctx()), 0xA0008000)
        self.assertEqual(self.root(self.ctx(asid=2)), 0xA0004000)
        self.assertEqual(self.root(self.ctx(asid=3)), 0xA0000000)

    def test_allocation_general_never_borrows_other_level_and_append_view(self):
        for explicit in (False, True):
            with self.subTest(explicit=explicit):
                self.fresh()
                self.h.register_pa_region(0xA0000000, 0xA0004000)
                cfg, levels = self.policy(
                    0xA0000000 if explicit else 0, 0xA0004000 if explicit else 0,
                    windows=((0, 0xA0000000, 0xA0004000),),
                )
                self.assertEqual(self.apply(cfg, levels), 0)
                ctx = self.h.create_context(1, 0)
                self.h.set_s_stage(ctx, "Sv39")
                self.assertEqual(self.h.last_error()[0], -9)
                self.h.register_pa_region(0xA0004000, 0xA0008000)
                self.h.set_s_stage(ctx, "Sv39")
                self.assertEqual(self.h.last_error()[0], -9 if explicit else 0)
                if explicit:
                    cfg.pt_base, cfg.pt_limit = 0, 0
                    self.assertEqual(self.apply(cfg, levels), 0)
                    self.h.set_s_stage(ctx, "Sv39")
                    self.assertEqual(self.h.last_error()[0], 0)
                self.assertEqual(self.root(ctx), 0xA0004000)

    def test_allocation_online_policy_preserves_live_tree_layout_and_ledger(self):
        old_policy = self.policy(windows=((2, 0xA0004000, 0xA0005000),))
        self.assertEqual(self.apply(*old_policy), 0)
        ctx = self.ctx()
        self.add(ctx, "S", 0x4000, 0x84000000)
        before = self.snapshot(ctx)
        status, layout = self.create(ctx, 0)
        self.assertEqual(status, 0)
        blocks, data = self.pull(layout)
        self.assertEqual(self.apply(*self.policy(0xA0010000, 0xA0020000)), 0)
        self.assertEqual(self.snapshot(ctx), before)
        after_blocks, after_data = self.pull(layout)
        self.assertEqual(([bytes(b) for b in after_blocks], after_data),
                         ([bytes(b) for b in blocks], data))
        self.assertEqual(self.root(self.ctx(asid=2)), 0xA0010000)
        self.assertEqual(self.apply(*old_policy), 0)
        self.assertEqual(self.root(self.ctx(asid=3)), 0xA0002000)
        self.assertEqual(self.snapshot(ctx), before)

    def test_allocation_failed_stage_replacement_preserves_every_observable(self):
        self.fresh()
        self.h.register_pa_region(0xA0000000, 0xA0003000)
        ctx = self.ctx()
        self.add(ctx, "S", 0x4000, 0x84000000)
        before = self.snapshot(ctx)
        status, layout = self.create(ctx, 0)
        self.assertEqual(status, 0)
        self.h.set_s_stage(ctx, "Sv48")
        self.assertEqual(self.h.last_error()[0], -9)
        self.assertEqual(self.snapshot(ctx), before)
        self.assert_export(ctx, 0, *self.pull(layout))

    def test_allocation_vs_failure_preserves_existing_binding_and_layout(self):
        self.fresh()
        self.h.register_pa_region(0xA0000000, 0xA0010000)
        self.h.register_gpa_region(1, 0xB0000000, 0xB0003000)
        ctx = self.ctx("VS", vmid=1)
        self.h.set_gs_stage(ctx, "Sv39x4")
        self.assertEqual(self.h.last_error()[0], 0)
        self.add(ctx, "VS", 0x4000, 0x60000000)
        before = (self.h.get_vsatp(ctx), self.raw(ctx, "VS"), self.raw(ctx, "G"),
                  bytes(self.query(ctx, stage=1, address=0x4008)[0]))
        status, layout = self.create(ctx, 1)
        self.assertEqual(status, 0)
        blocks, data = self.pull(layout)
        self.h.set_vs_stage(ctx, "Sv48")
        self.assertEqual(self.h.last_error()[0], -9)
        self.assertEqual((self.h.get_vsatp(ctx), self.raw(ctx, "VS"), self.raw(ctx, "G"),
                          bytes(self.query(ctx, stage=1, address=0x4008)[0])), before)
        new_blocks, new_data = self.pull(layout)
        self.assertEqual(([bytes(b) for b in new_blocks], new_data),
                         ([bytes(b) for b in blocks], data))

    def test_allocation_g_failure_preserves_existing_binding_and_layout(self):
        self.fresh()
        self.h.register_pa_region(0xA0000000, 0xA0007000)
        ctx = self.ctx("G", "Sv39x4", vmid=1)
        self.add(ctx, "G", 0x4000, 0x84000000, perm=0x73)
        before = self.h.get_hgatp(ctx), self.raw(ctx, "G")
        status, layout = self.create(ctx, 2)
        self.assertEqual(status, 0)
        self.h.set_gs_stage(ctx, "Sv48x4")
        self.assertEqual(self.h.last_error()[0], -9)
        self.assertEqual((self.h.get_hgatp(ctx), self.raw(ctx, "G")), before)
        self.assertEqual(self.query(ctx, stage=2, address=0x4008)[0].matched_pa, 0x84000008)
        self.assert_export(ctx, 2, *self.pull(layout))

    def test_allocation_vs_requires_g_and_backfill_failure_is_reported(self):
        self.fresh()
        self.h.register_pa_region(0xA0000000, 0xA0004000)
        ctx = self.h.create_context(1, 1)
        self.h.set_vs_stage(ctx, "Sv39")
        self.assertEqual(self.h.last_error()[0], -7)
        self.assertEqual(self.h.get_vsatp(ctx), 0)
        self.h.register_gpa_region(1, 0xB0000000, 0xB0010000)
        self.h.set_vs_stage(ctx, "Sv39")
        self.assertEqual(self.h.last_error()[0], 0)
        self.h.set_gs_stage(ctx, "Sv39x4")
        self.assertEqual(self.h.last_error()[0], 0)
        self.h.add_mapping(ctx, "VS", 0x4000, 0x60000000, 0x1000, perm=0x63)
        self.assertEqual(self.h.last_error()[0], -9)
        # Source mapping was published before later GENERAL SPA backing ran out.
        self.assertEqual(self.query(ctx, stage=1, address=0x4008)[0].matched_pa, 0x60000008)
        self.assertFalse(self.h.get_blocks(ctx, "G"))
        self.assertEqual(self.h.last_error()[0], 0)
        # No G PTE graph has been materialized, so capture rejects the missing tree.
        self.assertEqual(self.create(ctx, 1), (4, 0))

    def test_allocation_gpa_policy_is_vmid_local(self):
        for vmid in (1, 2):
            self.h.register_gpa_region(vmid, 0xB0000000, 0xB0040000)
            self.assertEqual(self.h.last_error()[0], 0)
        self.assertEqual(
            self.apply(*self.policy(windows=((2, 0xB0010000, 0xB0011000),)), vmid=1), 0
        )
        self.assertEqual(self.apply(*self.policy(0xB0020000, 0xB0024000), vmid=2), 0)
        first, second = self.ctx("VS", vmid=1), self.ctx("VS", vmid=2)
        self.assertEqual(self.root(first, "VS"), 0xB0010000)
        self.assertEqual(self.root(second, "VS"), 0xB0020000)
        self.assertEqual(self.apply(*self.policy(), vmid=3), -7)
        self.assertEqual(self.root(first, "VS"), 0xB0010000)

    def test_allocation_invalid_policy_does_not_change_existing_tree(self):
        ctx = self.ctx()
        self.add(ctx, "S", 0x4000, 0x84000000)
        before = self.snapshot(ctx)
        for field, value, expected in (("abi_version", 2, -11), ("struct_size", 39, -4),
                                        ("flags", 1, -4), ("reserved0", 1, -4),
                                        ("pt_align", 3, -4)):
            cfg, levels = self.policy()
            setattr(cfg, field, value)
            with self.subTest(field=field):
                self.assertEqual(self.apply(cfg, levels), expected)
                self.assertEqual(self.snapshot(ctx), before)
        for windows in (((-1, 0xA0000000, 0xA0001000),),
                        ((0, 0xA0000000, 0xA0002000), (1, 0xA0001000, 0xA0003000)),
                        ((2, 0xC0000000, 0xC0001000),)):
            self.assertEqual(self.apply(*self.policy(windows=windows)), -4)
            self.assertEqual(self.snapshot(ctx), before)
        cfg, _ = self.policy()
        self.assertEqual(
            self.lib.ptg_configure_pa_placement_v1(None, c.byref(cfg), None, 0, 32), -1
        )
        self.assertEqual(self.lib.ptg_configure_pa_placement_v1(
            self.h._handle, c.byref(cfg), None, 0, 31), -4)
        self.fresh()
        self.assertEqual(self.apply(*self.policy()), -7)

    def test_allocation_unaligned_extended_overlapping_readonly_inputs(self):
        cfg, levels = self.policy(windows=((2, 0xA0008000, 0xA0009000),))
        cfg.struct_size = 64
        storage = canary(160)
        c.memmove(c.byref(storage, 1), c.byref(cfg), 40)
        c.memmove(c.byref(storage, 49), c.byref(levels[0]), 32)
        before = bytes(storage)
        self.assertEqual(self.lib.ptg_configure_pa_placement_v1(
            self.h._handle, c.byref(storage, 1), c.byref(storage, 49), 1, 48), 0)
        self.assertEqual(bytes(storage), before)
        self.assertEqual(self.root(self.ctx()), 0xA0008000)

    def test_allocation_deterministic_failure_stops_after_prior_commit(self):
        self.fresh()
        self.h.register_pa_region(0xA0000000, 0xA0003000)
        ctx = self.ctx()
        mappings = (PtgMapping * 3)(
            PtgMapping(0x4000, 0x84000000, 0x1000, 0, 0x63),
            PtgMapping(0x40000000, 0x85000000, 0x1000, 0, 0x63),
            PtgMapping(0x8000, 0x86000000, 0x1000, 0, 0x63),
        )
        self.lib.ptg_generate_deterministic(self.h._handle, ctx, 0, mappings, 3)
        self.assertEqual(self.h.last_error()[0], -9)
        self.assertEqual(self.query(ctx, address=0x4008)[0].matched_pa, 0x84000008)
        self.assertEqual(self.query(ctx, address=0x40000000), [])
        self.assertEqual(self.query(ctx, address=0x8000), [])

    def test_allocation_deterministic_duplicate_compatibility(self):
        ctx = self.ctx()
        self.add(ctx, "S", 0x4000, 0x84000000)
        mappings = (PtgMapping * 2)(
            PtgMapping(0x4000, 0x85000000, 0x1000, 0, 0x63),
            PtgMapping(0x8000, 0x86000000, 0x1000, 0, 0x63),
        )
        self.lib.ptg_generate_deterministic(self.h._handle, ctx, 0, mappings, 2)
        self.assertEqual(self.h.last_error()[0], 0)
        self.assertEqual(self.query(ctx, address=0x4000)[0].matched_pa, 0x84000000)
        self.assertEqual(self.query(ctx, address=0x8000)[0].matched_pa, 0x86000000)

    def test_allocation_random_failure_zero_count_untouched_output(self):
        self.fresh()
        self.h.register_pa_region(0xA0000000, 0xA0001000)
        ctx = self.ctx()
        cfg = PtgRandomConfig()
        cfg.va_start, cfg.va_end = 0x4000, 0x10000
        cfg.pa_start, cfg.pa_end = 0x84000000, 0x84010000
        cfg.min_mappings, cfg.max_mappings, cfg.seed, cfg.sv_mode = 2, 2, 1, 8
        cfg.access_types, cfg.flags_a, cfg.flags_d, cfg.flags_u = 3, 1, 1, 2
        cfg.size_4kb_weight, cfg.force_new = 1.0, 1
        output = canary(c.sizeof(PtgMapping) * 4)
        count = self.h._lib.ptg_random_generate(
            self.h._handle, ctx, 0, c.byref(cfg), c.cast(output, c.POINTER(PtgMapping)), 4
        )
        self.assertEqual((count, self.h.last_error()[0]), (0, -9))
        self.assertEqual(bytes(output), b"\xA5" * len(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ptg-lib", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if os.environ.get("FORCE_SOURCED") != "True":
        parser.error("source setenv.bash first")
    if args.report.exists():
        parser.error("report must be new")
    library = args.ptg_lib.resolve(strict=True)
    before = hashlib.sha256(library.read_bytes()).hexdigest()
    AllocationContracts.library = library
    started = time.time()
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(AllocationContracts)
    )
    after = hashlib.sha256(library.read_bytes()).hexdigest()
    passed = result.wasSuccessful() and before == after
    sources = (Path(__file__).resolve(),
               Path(__file__).with_name("ptg_mapping_export_acceptance.py"))
    report = {
        "passed": passed, "tests": result.testsRun, "library": str(library),
        "sha256_before": before, "sha256_after": after,
        "started_at": started, "finished_at": time.time(),
        "sources": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        "failures": [(str(test), message) for test, message in result.failures],
        "errors": [(str(test), message) for test, message in result.errors],
        "scope": "serial public ABI, allocation/placement and prior query/export contracts",
    }
    with args.report.open("x") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print("{}: {}".format("PASS" if passed else "FAIL", args.report))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
