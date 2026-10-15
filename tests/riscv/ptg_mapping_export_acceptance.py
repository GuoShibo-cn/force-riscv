"""Independent downstream checks for the public Mapping Query/Strict Export v1 contracts.

Run with an explicit --ptg-lib and a new --report path. This does not change the
production backend or rebuild/install the dependency. Expected ranges come from
fixed mappings, and PTE observations are checked against raw exported bytes.
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "py"))
from riscv.paging.PtgBackend import PtgHandle  # noqa: E402

OK, INVALID, ABI, NO_CONTEXT, NO_TREE, SMALL, STALE, NO_BACKING, INTERNAL = range(9)
FORWARD, REVERSE, ENUMERATE = range(3)
CURRENT, LOGICAL = range(2)
VALID_LOGICAL, VALID_CURRENT, VALID_PTE, VALID_MATCH, VALID_OBSERVED = (1, 2, 4, 8, 16)


class Query(c.Structure):
    _fields_ = [
        ("struct_size", c.c_uint32), ("abi_version", c.c_uint32),
        ("stage", c.c_int32), ("direction", c.c_int32), ("domain", c.c_int32),
        ("flags", c.c_uint32), ("address", c.c_uint64),
        ("reserved0", c.c_uint32), ("reserved1", c.c_uint32),
    ]


class MappingRange(c.Structure):
    _fields_ = [
        ("va_base", c.c_uint64), ("pa_base", c.c_uint64), ("page_size", c.c_uint64),
        ("leaf_level", c.c_int32), ("reserved0", c.c_uint32),
    ]


class Record(c.Structure):
    _fields_ = [
        ("struct_size", c.c_uint32), ("abi_version", c.c_uint32),
        ("valid_fields", c.c_uint32), ("stage", c.c_int32),
        ("input_kind", c.c_int32), ("output_kind", c.c_int32),
        ("pte_state", c.c_int32), ("observed_level", c.c_int32),
        ("tree_id", c.c_uint64), ("observed_va", c.c_uint64),
        ("logical", MappingRange), ("current", MappingRange),
        ("matched_va", c.c_uint64), ("matched_pa", c.c_uint64),
        ("pte_address", c.c_uint64), ("pte_value", c.c_uint64),
        ("raw_perm", c.c_uint32), ("pbmt", c.c_uint32),
        ("napot", c.c_uint32), ("reserved0", c.c_uint32),
    ]


class ExportRequest(c.Structure):
    _fields_ = [
        ("struct_size", c.c_uint32), ("abi_version", c.c_uint32),
        ("stage", c.c_int32), ("flags", c.c_uint32),
        ("reserved0", c.c_uint32), ("reserved1", c.c_uint32),
    ]


class ExportBlock(c.Structure):
    _fields_ = [
        ("struct_size", c.c_uint32), ("abi_version", c.c_uint32),
        ("stage", c.c_int32), ("source_kind", c.c_int32),
        ("source_address", c.c_uint64), ("spa", c.c_uint64),
        ("size", c.c_uint64), ("data_offset", c.c_uint64),
    ]


def canary(size):
    value = (c.c_ubyte * size)()
    c.memset(value, 0xA5, size)
    return value


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Contracts(unittest.TestCase):
    library = None

    def setUp(self):
        self.h = PtgHandle(str(self.library))
        self.addCleanup(self.h.destroy)
        self.lib = self.h._lib
        signatures = {
            "ptg_mapping_query_v1_init": [c.c_void_p, c.c_uint32],
            "ptg_mapping_query_v1": [
                c.c_void_p, c.c_uint32, c.c_void_p, c.c_void_p,
                c.c_uint32, c.c_uint32, c.c_void_p,
            ],
            "ptg_export_layout_v1_init": [c.c_void_p, c.c_uint32],
            "ptg_export_layout_create_v1": [c.c_void_p, c.c_uint32, c.c_void_p, c.c_void_p],
            "ptg_export_layout_read_v1": [
                c.c_void_p, c.c_uint64, c.c_void_p, c.c_uint32, c.c_uint32,
                c.c_void_p, c.c_uint64, c.c_void_p, c.c_void_p,
            ],
            "ptg_export_layout_free_v1": [c.c_void_p, c.c_uint64],
        }
        for name, args in signatures.items():
            fn = getattr(self.lib, name)
            fn.argtypes, fn.restype = args, c.c_int32
        self.lib.ptg_context_clear.argtypes = [c.c_void_p, c.c_uint32, c.c_int]
        self.lib.ptg_context_clear.restype = None
        self.lib.ptg_share_node_intra.argtypes = [
            c.c_void_p, c.c_uint32, c.c_int, c.c_uint64, c.c_uint64, c.c_uint16
        ]
        self.lib.ptg_share_node_intra.restype = c.c_int
        self.h.register_pa_region(0xA0000000, 0xB0000000)

    def ctx(self, stage="S", mode="Sv39", asid=1, vmid=0):
        ctx = self.h.create_context(asid, vmid)
        {"S": self.h.set_s_stage, "VS": self.h.set_vs_stage,
         "G": self.h.set_gs_stage}[stage](ctx, mode)
        self.assertEqual(self.h.last_error()[0], 0)
        return ctx

    def add(self, ctx, stage, va, pa, level=0, perm=0x63):
        self.h.add_mapping(ctx, stage, va, pa, 1 << (12 + 9 * level), level, perm)
        self.assertEqual(self.h.last_error()[0], 0)

    def raw(self, ctx, stage):
        layout = self.h.get_blocks(ctx, stage)
        self.assertEqual(self.h.last_error()[0], 0)
        if not layout:
            return {}
        try:
            return {
                block.pa: c.string_at(block.data, block.size)
                for block in layout.contents.blocks[:layout.contents.num_blocks]
            }
        finally:
            self.h.free_blocks(layout)

    def leaf(self, ctx, address, stage="S"):
        raw = self.raw(ctx, stage)
        csr = self.h.get_hgatp(ctx) if stage == "G" else self.h.get_satp(ctx)
        table = (csr & ((1 << 44) - 1)) << 12
        for level in (2, 1, 0):
            mask = 0x7FF if stage == "G" and level == 2 else 0x1FF
            slot = table + ((address >> (12 + 9 * level)) & mask) * 8
            chunk = next(buf[slot - base:slot - base + 8] for base, buf in raw.items()
                         if base <= slot and slot + 8 <= base + len(buf))
            pte = int.from_bytes(chunk, "little")
            if not pte & 1 or pte & 0xE:
                return slot, pte, level
            table = ((pte >> 10) & ((1 << 44) - 1)) << 12
        self.fail("no raw Sv39 leaf")

    def request(self, stage=0, direction=FORWARD, domain=CURRENT, address=0):
        query = Query()
        self.assertEqual(self.lib.ptg_mapping_query_v1_init(c.byref(query), c.sizeof(query)), OK)
        query.stage, query.direction = stage, direction
        query.domain, query.address = domain, address
        return query

    def query(self, ctx, stage=0, direction=FORWARD, domain=CURRENT, address=0):
        query = self.request(stage, direction, domain, address)
        required = c.c_uint32(777)
        fn = self.lib.ptg_mapping_query_v1
        self.assertEqual(fn(self.h._handle, ctx, c.byref(query), None, 0, 160,
                            c.byref(required)), OK)
        count = required.value
        if not count:
            return []
        records = (Record * count)()
        self.assertEqual(fn(self.h._handle, ctx, c.byref(query), records, count, 160,
                            c.byref(required)), OK)
        self.assertEqual(required.value, count)
        for record in records:
            self.assertEqual(
                (record.struct_size, record.abi_version, record.reserved0), (160, 1, 0)
            )
            self.assertTrue(record.valid_fields & VALID_OBSERVED)
            self.assertNotEqual(record.tree_id, 0)
        return list(records)

    def create(self, ctx, stage):
        req = ExportRequest()
        self.assertEqual(self.lib.ptg_export_layout_v1_init(c.byref(req), c.sizeof(req)), OK)
        req.stage = stage
        layout = c.c_uint64(999)
        status = self.lib.ptg_export_layout_create_v1(
            self.h._handle, ctx, c.byref(req), c.byref(layout)
        )
        return status, layout.value

    def pull(self, layout):
        count, size = c.c_uint32(777), c.c_uint64(888)
        fn = self.lib.ptg_export_layout_read_v1
        self.assertEqual(fn(self.h._handle, layout, None, 0, 48, None, 0,
                            c.byref(count), c.byref(size)), OK)
        expected = (count.value, size.value)
        if not count.value:
            return [], b""
        blocks, data = (ExportBlock * count.value)(), (c.c_ubyte * size.value)()
        self.assertEqual(fn(self.h._handle, layout, blocks, count.value, 48, data, size.value,
                            c.byref(count), c.byref(size)), OK)
        self.assertEqual((count.value, size.value), expected)
        return list(blocks), bytes(data)

    def two_stage(self, backing=0xA4000000, g_perm=0x73, vs_perm=0x63):
        self.h.register_gpa_region(1, 0x50000000, 0x50200000)
        ctx = self.ctx("G", "Sv39x4", vmid=1)
        # One predetermined G superpage backs all VS nodes; expected SPAs do not come from export.
        self.add(ctx, "G", 0x50000000, backing, level=1, perm=g_perm)
        self.h.set_vs_stage(ctx, "Sv39")
        self.add(ctx, "VS", 0x40000000, 0x60000000, perm=vs_perm)
        return ctx

    def assert_export(self, ctx, stage, blocks, data, backing=None):
        raw = self.raw(ctx, stage)
        self.assertEqual([block.source_address for block in blocks], sorted(raw))
        offset = 0
        for block in blocks:
            source = block.source_address
            expected_spa = source if backing is None else backing + source - 0x50000000
            self.assertEqual((block.struct_size, block.abi_version, block.stage), (48, 1, stage))
            self.assertEqual(block.source_kind, 2 if stage == 1 else 3)
            self.assertEqual((block.spa, block.size, block.data_offset),
                             (expected_spa, len(raw[source]), offset))
            self.assertEqual(data[offset:offset + block.size], raw[source])
            offset += block.size
        self.assertEqual(offset, len(data))

    def fault(self, ctx, stage, address, cause=1, level=0):
        req = self.h.create_fault_request_v2()
        req.stage, req.scope, req.address_kind = stage, 0, 0
        req.selection_mode, req.fault_cause = 1, cause
        req.access_type, req.privilege, req.verification_mode = 0, 0 if stage == 0 else 2, 0
        req.target_level, req.has_target_address = level, 1
        req.target_address, req.dry_run = address, 0
        status, records = self.h.inject_fault_v2(ctx, req)
        self.assertEqual(status, 0)
        self.assertEqual(len(records), 1)
        return records[0]

    def test_abi_offsets_initializers_and_unknown_tails(self):
        self.assertEqual(
            [c.sizeof(t) for t in (Query, MappingRange, Record, ExportRequest, ExportBlock)],
            [40, 32, 160, 24, 48],
        )
        self.assertEqual([getattr(Record, name).offset for name in
                          ("tree_id", "logical", "current", "matched_va", "pte_value", "napot")],
                         [32, 48, 80, 112, 136, 152])
        for typ, fn in ((Query, self.lib.ptg_mapping_query_v1_init),
                        (ExportRequest, self.lib.ptg_export_layout_v1_init)):
            n = c.sizeof(typ)
            buf = canary(n + 16)
            self.assertEqual(fn(buf, n + 16), OK)
            self.assertEqual(bytes(buf)[n:], b"\xA5" * 16)
            self.assertEqual(typ.from_buffer_copy(buf).abi_version, 1)
            short = canary(n)
            self.assertEqual(fn(short, n - 1), ABI)
            self.assertEqual(bytes(short), b"\xA5" * n)

    def test_zero_absence_reverse_aliases_and_superpage_offsets(self):
        ctx = self.ctx()
        self.add(ctx, "S", 0, 0)
        for va in (0x4000, 0x8000, 0xC000):
            self.add(ctx, "S", va, 0xA8000000)
        self.add(ctx, "S", 0x200000, 0xA4000000, level=1)
        self.add(ctx, "S", 0x40000000, 0x100000000, level=2)
        zero = self.query(ctx, address=0)
        self.assertEqual(len(zero), 1)
        self.assertEqual(
            (zero[0].valid_fields, zero[0].matched_va, zero[0].matched_pa), (31, 0, 0)
        )
        self.assertEqual(self.query(ctx, address=0x100000), [])
        aliases = self.query(ctx, direction=REVERSE, address=0xA8000008)
        self.assertEqual(sorted((r.matched_va, r.matched_pa) for r in aliases),
                         [(0x4008, 0xA8000008), (0x8008, 0xA8000008), (0xC008, 0xA8000008)])
        for address, expected_pa, size, level in (
            (0x201234, 0xA4001234, 0x200000, 1),
            (0x40123450, 0x100123450, 0x40000000, 2),
        ):
            record = self.query(ctx, address=address)[0]
            self.assertEqual(
                (record.matched_pa, record.current.page_size, record.current.leaf_level),
                (expected_pa, size, level),
            )
        for record in self.query(ctx, direction=ENUMERATE):
            self.assertFalse(record.valid_fields & VALID_MATCH)
            self.assertEqual((record.matched_va, record.matched_pa), (0, 0))

    def test_query_domains_contexts_and_canonical_address(self):
        ctx = self.two_stage()
        self.add(ctx, "G", 0x60000000, 0xA9000000, perm=0x73)
        vs = self.query(ctx, stage=1, address=0x40000008)[0]
        gs = self.query(ctx, stage=2, address=0x60000008)[0]
        self.assertEqual((vs.input_kind, vs.output_kind, vs.matched_pa), (1, 2, 0x60000008))
        self.assertEqual((gs.input_kind, gs.output_kind, gs.matched_pa), (2, 3, 0xA9000008))
        self.assertTrue(0x50000000 <= vs.pte_address < 0x50200000)
        self.assertTrue(0xA0000000 <= gs.pte_address < 0xB0000000)
        other = self.ctx(asid=9)
        negative = 0xFFFFFFC000004000
        self.add(other, "S", negative, 0xA7000000)
        self.assertEqual(self.query(other, address=negative + 8)[0].matched_pa, 0xA7000008)
        self.assertEqual(self.query(other, address=0x40000008), [])
        self.add(ctx, "G", (1 << 40) + 0x4000, 0xA7000000, perm=0x73)
        self.assertEqual(
            self.query(ctx, stage=2, address=(1 << 40) + 0x4008)[0].matched_pa, 0xA7000008
        )

    def test_sv48_sv57_current_ranges(self):
        for mode in ("Sv48", "Sv57"):
            ctx = self.ctx(mode=mode)
            self.add(ctx, "S", 0x4000, 0xA8000000)
            self.assertEqual(self.query(ctx, address=0x4007)[0].matched_pa, 0xA8000007)
            status, layout = self.create(ctx, 0)
            self.assertEqual(status, OK)
            self.assert_export(ctx, 0, *self.pull(layout))

    def test_clear_and_interior_remap_sync_indices(self):
        first, other = self.ctx(), self.ctx(asid=2)
        for ctx in (first, other):
            self.add(ctx, "S", 0x4000, 0xA8000000)
        self.h.remap_va(first, "S", 0x4008, 0xA9000000)
        self.assertEqual(self.h.last_error()[0], 0)
        self.assertEqual(self.h.mapping_index_pa(first, "S", 0x4000), 0xA9000000)
        self.assertEqual(self.h.mapping_index_vas(first, "S", 0xA8000000), [])
        self.assertEqual(self.query(first, address=0x4008)[0].matched_pa, 0xA9000008)
        self.lib.ptg_context_clear(self.h._handle, first, 0)
        self.assertEqual(self.h.mapping_index_vas(first, "S", 0xA9000000), [])
        for domain in (CURRENT, LOGICAL):
            self.assertEqual(self.query(first, direction=ENUMERATE, domain=domain), [])
        self.assertEqual(self.query(other, address=0x4008)[0].matched_pa, 0xA8000008)

    def test_ad_zero_queries_and_export_do_not_write_pte(self):
        ctx = self.ctx()
        self.add(ctx, "S", 0x4000, 0xA8000000, perm=3)
        before = self.raw(ctx, "S")
        slot, pte, level = self.leaf(ctx, 0x4000)
        self.assertEqual((pte & 0xCF, level), (7, 0))
        for domain in (CURRENT, LOGICAL):
            for direction, address in ((FORWARD, 0x4008), (REVERSE, 0xA8000008), (ENUMERATE, 0)):
                record = self.query(ctx, direction=direction, domain=domain, address=address)[0]
                self.assertEqual(record.raw_perm, 3)
                self.assertEqual(record.pte_value & 0xC0, 0)
                self.assertEqual((record.pte_address, record.pte_value), (slot, pte))
                self.assertTrue(record.valid_fields & VALID_CURRENT)
        status, layout = self.create(ctx, 0)
        self.assertEqual(status, OK)
        self.assert_export(ctx, 0, *self.pull(layout))
        self.assertEqual(self.raw(ctx, "S"), before)

    def test_fault_keeps_logical_but_not_current_validity(self):
        ctx = self.ctx()
        self.add(ctx, "S", 0x4000, 0xA8000000)
        self.fault(ctx, 0, 0x4000)
        before = self.raw(ctx, "S")
        slot, pte, level = self.leaf(ctx, 0x4000)
        self.assertEqual((pte & 1, level), (0, 0))
        for domain, fields in ((CURRENT, 21), (LOGICAL, 29)):
            record = self.query(ctx, domain=domain, address=0x4008)[0]
            self.assertEqual((record.valid_fields, record.pte_state), (fields, 1))
            self.assertEqual(
                (record.logical.va_base, record.logical.pa_base), (0x4000, 0xA8000000)
            )
            self.assertEqual((record.current.va_base, record.current.pa_base,
                              record.current.page_size, record.current.leaf_level), (0, 0, 0, -1))
            self.assertEqual((record.pte_address, record.pte_value), (slot, pte))
            self.assertEqual(record.pte_value & 1, 0)
        self.assertEqual(self.query(ctx, direction=REVERSE, address=0xA8000008), [])
        self.assertEqual(self.query(ctx, direction=REVERSE, domain=LOGICAL,
                                    address=0xA8000008)[0].matched_va, 0x4008)
        self.assertEqual(self.raw(ctx, "S"), before)

    def test_query_capacity_and_stride_canaries(self):
        ctx = self.ctx()
        for va in (0x4000, 0x8000, 0xC000):
            self.add(ctx, "S", va, 0xA8000000)
        req = self.request(direction=REVERSE, address=0xA8000008)
        count, buf = c.c_uint32(99), canary(4 * 192)
        fn = self.lib.ptg_mapping_query_v1
        self.assertEqual(fn(self.h._handle, ctx, c.byref(req), buf, 2, 192, c.byref(count)), SMALL)
        self.assertEqual(count.value, 3)
        self.assertEqual(bytes(buf), b"\xA5" * len(buf))
        self.assertEqual(fn(self.h._handle, ctx, c.byref(req), buf, 4, 192, c.byref(count)), OK)
        for i in range(3):
            self.assertEqual(bytes(buf)[i * 192 + 160:(i + 1) * 192], b"\xA5" * 32)
        self.assertEqual(bytes(buf)[3 * 192:], b"\xA5" * 192)

    def test_query_invalid_inputs_leave_buffers_unchanged(self):
        ctx = self.ctx()
        self.add(ctx, "S", 0x4000, 0xA8000000)
        fn = self.lib.ptg_mapping_query_v1
        for field, value, expected in (("abi_version", 2, ABI), ("struct_size", 39, ABI),
                                        ("flags", 1, INVALID), ("stage", 99, INVALID),
                                        ("direction", 9, INVALID), ("reserved1", 1, INVALID)):
            with self.subTest(field=field):
                req, count, buf = self.request(address=0x4000), c.c_uint32(99), canary(160)
                setattr(req, field, value)
                self.assertEqual(fn(self.h._handle, ctx, c.byref(req), buf, 1, 160,
                                    c.byref(count)), expected)
                self.assertEqual(bytes(buf), b"\xA5" * 160)
        req, count, buf = self.request(address=0x4000), c.c_uint32(99), canary(160)
        self.assertEqual(fn(self.h._handle, 0xFFFFFFFF, c.byref(req), buf, 1, 160,
                            c.byref(count)), NO_CONTEXT)
        self.assertEqual(count.value, 0)
        self.assertEqual(bytes(buf), b"\xA5" * 160)
        req.stage = 2
        self.assertEqual(fn(self.h._handle, ctx, c.byref(req), buf, 1, 160,
                            c.byref(count)), NO_TREE)

    def test_query_overlap_is_rejected_without_any_write(self):
        ctx = self.ctx()
        self.add(ctx, "S", 0x4000, 0xA8000000)
        buf = canary(192)
        req = self.request(address=0x4000)
        c.memmove(buf, c.byref(req), 40)
        before, count = bytes(buf), c.c_uint32(99)
        fn = self.lib.ptg_mapping_query_v1
        self.assertEqual(fn(self.h._handle, ctx, buf, buf, 1, 192, c.byref(count)), INVALID)
        self.assertEqual(bytes(buf), before)
        self.assertEqual(count.value, 99)
        self.assertEqual(fn(self.h._handle, ctx, c.byref(req), buf, 1, 192,
                            c.byref(buf, 180)), INVALID)
        self.assertEqual(bytes(buf), before)

    def test_strict_vs_spa_domain_and_zero_spa(self):
        for backing in (0xA4000000, 0):
            # Separate handles avoid reuse of the same VMID's configured GPA pool.
            if backing == 0:
                self.h.destroy()
                self.setUp()
            ctx = self.two_stage(backing)
            if backing == 0:
                # A valid zero SPA must also be in a declared PTG placement region.
                self.assertEqual(self.create(ctx, 1), (NO_BACKING, 0))
                self.h.register_pa_region(0, 0x200000)
            status, layout = self.create(ctx, 1)
            self.assertEqual(status, OK)
            blocks, data = self.pull(layout)
            self.assert_export(ctx, 1, blocks, data, backing)
            self.assertEqual(blocks[0].spa, backing)

    def test_vs_export_no_g_ad_write_and_required_write_permission(self):
        ctx = self.two_stage()
        config = self.h.create_vm_config_v2(target="G", adue=0)
        self.assertEqual(self.h.set_vm_config_v2(ctx, config), 0)
        changed = self.fault(ctx, 2, 0x50000000, cause=3, level=1)
        self.assertEqual(changed.new_pte & 0x40, 0)
        config.adue = 1
        self.assertEqual(self.h.set_vm_config_v2(ctx, config), 0)
        slot, pte, level = self.leaf(ctx, 0x50000000, stage="G")
        self.assertEqual((pte & 0x40, level), (0, 1))
        record = self.query(ctx, stage=2, address=0x50000000)[0]
        self.assertEqual((record.pte_address, record.pte_value), (slot, pte))
        before = self.raw(ctx, "G")
        status, layout = self.create(ctx, 1)
        self.assertEqual(status, OK)
        self.assert_export(ctx, 1, *self.pull(layout), backing=0xA4000000)
        self.assertEqual(self.raw(ctx, "G"), before)

    def test_vs_capture_rejects_readonly_g_when_ad_write_is_needed(self):
        ctx = self.two_stage(g_perm=0x71, vs_perm=3)
        config = self.h.create_vm_config_v2(target="S_VS", adue=1)
        self.assertEqual(self.h.set_vm_config_v2(ctx, config), 0)
        before = (self.raw(ctx, "VS"), self.raw(ctx, "G"))
        self.assertEqual(self.create(ctx, 1), (NO_BACKING, 0))
        self.assertEqual((self.raw(ctx, "VS"), self.raw(ctx, "G")), before)

    def test_g_remap_changes_current_query_not_captured_placement(self):
        ctx = self.two_stage()
        status, old = self.create(ctx, 1)
        self.assertEqual(status, OK)
        self.h.remap_va(ctx, "G", 0x50000008, 0xA6000000)
        self.assertEqual(self.h.last_error()[0], 0)
        self.assertEqual(self.query(ctx, stage=2, address=0x50000008)[0].matched_pa, 0xA6000008)
        self.assert_export(ctx, 1, *self.pull(old), backing=0xA4000000)
        status, fresh = self.create(ctx, 1)
        self.assertEqual(status, OK)
        self.assert_export(ctx, 1, *self.pull(fresh), backing=0xA6000000)

    def test_shared_root_path_aliases_follow_physical_leaf_remap(self):
        ctx = self.ctx()
        self.add(ctx, "S", 0x4000, 0xA8000000)
        root = (self.h.get_satp(ctx) & ((1 << 44) - 1)) << 12
        root_bytes = self.raw(ctx, "S")[root]
        child = ((int.from_bytes(root_bytes[:8], "little") >> 10) & ((1 << 44) - 1)) << 12
        self.assertEqual(self.lib.ptg_share_node_intra(self.h._handle, ctx, 0, child, root, 1), 0)
        self.assertEqual(sorted(r.matched_va for r in self.query(
            ctx, direction=REVERSE, address=0xA8000008)), [0x4008, 0x40004008])
        self.h.remap_va(ctx, "S", 0x40004008, 0xA9000000)
        self.assertEqual(self.h.last_error()[0], 0)
        self.assertEqual(self.query(ctx, direction=REVERSE, address=0xA8000008), [])
        self.assertEqual(sorted(r.matched_va for r in self.query(
            ctx, direction=REVERSE, address=0xA9000008)), [0x4008, 0x40004008])

    def test_frozen_export_survives_g_clear_and_copies_current_vs_bytes(self):
        ctx = self.two_stage()
        status, layout = self.create(ctx, 1)
        self.assertEqual(status, OK)
        old_blocks, old_data = self.pull(layout)
        self.lib.ptg_context_clear(self.h._handle, ctx, 2)
        self.assertEqual(self.create(ctx, 1), (NO_BACKING, 0))
        self.h.remap_va(ctx, "VS", 0x40000008, 0x61000000)
        self.assertEqual(self.h.last_error()[0], 0)
        blocks, data = self.pull(layout)
        self.assertEqual([bytes(b) for b in blocks], [bytes(b) for b in old_blocks])
        self.assertNotEqual(data, old_data)
        self.assert_export(ctx, 1, blocks, data, 0xA4000000)

    def test_topology_growth_stales_layout_without_partial_output(self):
        ctx = self.two_stage()
        status, layout = self.create(ctx, 1)
        self.assertEqual(status, OK)
        self.add(ctx, "VS", 0x40001000, 0x60001000)
        self.assert_export(ctx, 1, *self.pull(layout), backing=0xA4000000)
        self.add(ctx, "VS", 0x80000000, 0x62000000)
        blocks, data = canary(4096), canary(65536)
        count, size = c.c_uint32(99), c.c_uint64(99)
        status = self.lib.ptg_export_layout_read_v1(
            self.h._handle, layout, blocks, 32, 64, data, len(data), c.byref(count), c.byref(size)
        )
        self.assertEqual((status, count.value, size.value), (STALE, 0, 0))
        self.assertEqual(bytes(blocks), b"\xA5" * len(blocks))
        self.assertEqual(bytes(data), b"\xA5" * len(data))
        self.assertEqual(self.lib.ptg_export_layout_free_v1(self.h._handle, layout), OK)

    def test_export_capacity_stride_and_pointer_overlap(self):
        ctx = self.two_stage()
        status, layout = self.create(ctx, 1)
        self.assertEqual(status, OK)
        full_blocks, full_data = self.pull(layout)
        n, size = len(full_blocks), len(full_data)
        fn = self.lib.ptg_export_layout_read_v1
        for capacity, byte_capacity in ((n - 1, size), (n, size - 1)):
            blocks, data = canary((n + 1) * 64), canary(size)
            required, required_bytes = c.c_uint32(99), c.c_uint64(99)
            self.assertEqual(fn(self.h._handle, layout, blocks, capacity, 64, data,
                                byte_capacity, c.byref(required), c.byref(required_bytes)), SMALL)
            self.assertEqual((required.value, required_bytes.value), (n, size))
            self.assertEqual(bytes(blocks), b"\xA5" * len(blocks))
            self.assertEqual(bytes(data), b"\xA5" * len(data))
        self.assertEqual(fn(self.h._handle, layout, blocks, n + 1, 64, data, size,
                            c.byref(required), c.byref(required_bytes)), OK)
        for i in range(n):
            self.assertEqual(bytes(blocks)[i * 64 + 48:(i + 1) * 64], b"\xA5" * 16)
        self.assertEqual(bytes(blocks)[n * 64:], b"\xA5" * 64)
        before = bytes(blocks)
        required.value, required_bytes.value = 77, 88
        self.assertEqual(fn(self.h._handle, layout, blocks, n, 64, blocks, 8,
                            c.byref(required), c.byref(required_bytes)), INVALID)
        self.assertEqual((bytes(blocks), required.value, required_bytes.value), (before, 77, 88))

    def test_export_invalid_request_foreign_ids_and_double_free(self):
        ctx = self.two_stage()
        req, identity = ExportRequest(), c.c_uint64(99)
        self.lib.ptg_export_layout_v1_init(c.byref(req), 24)
        req.flags = 1
        self.assertEqual(self.lib.ptg_export_layout_create_v1(
            self.h._handle, ctx, c.byref(req), c.byref(identity)), INVALID)
        self.assertEqual(identity.value, 0)
        status, layout = self.create(ctx, 1)
        self.assertEqual(status, OK)
        other = PtgHandle(str(self.library))
        try:
            count, size = c.c_uint32(99), c.c_uint64(99)
            self.assertEqual(
                self.lib.ptg_export_layout_read_v1(
                    other._handle, layout, None, 0, 48, None, 0, c.byref(count), c.byref(size)
                ), INVALID,
            )
            self.assertEqual((count.value, size.value), (0, 0))
            self.assertEqual(self.lib.ptg_export_layout_free_v1(other._handle, layout), INVALID)
        finally:
            other.destroy()
        self.assertEqual(self.lib.ptg_export_layout_free_v1(self.h._handle, 0), OK)
        self.assertEqual(self.lib.ptg_export_layout_free_v1(self.h._handle, layout), OK)
        self.assertEqual(self.lib.ptg_export_layout_free_v1(self.h._handle, layout), INVALID)
        self.assertEqual(self.lib.ptg_export_layout_read_v1(
            self.h._handle, layout, None, 0, 48, None, 0, c.byref(count), c.byref(size)), INVALID)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ptg-lib", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if os.environ.get("FORCE_SOURCED") != "True":
        parser.error("source setenv.bash first")
    library = args.ptg_lib.resolve(strict=True)
    if args.report.exists():
        parser.error("report must be a new file")
    before = digest(library)
    Contracts.library = library
    started = time.time()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Contracts)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    after = digest(library)
    passed = result.wasSuccessful() and before == after
    report = {
        "passed": passed, "library": str(library), "sha256_before": before,
        "sha256_after": after, "test_source_sha256": digest(Path(__file__)),
        "started_at": started, "finished_at": time.time(), "tests": result.testsRun,
        "failures": [(str(test), detail) for test, detail in result.failures],
        "errors": [(str(test), detail) for test, detail in result.errors],
        "scope": "public ABI/current-logical/raw-PTE/pull; not ISS or host RAM allocation",
    }
    with args.report.open("x") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print("{}: {}".format("PASS" if passed else "FAIL", args.report))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
