"""Managed-context contracts against the actual PTG library; host allocation is a fixture."""

import os
import sys
import types
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.join(ROOT, "py"))

from riscv.paging.PtgVmContext import PtgVmContext


class Owner:
    genThreadID = 0

    def __init__(self):
        self.locked = False
        self.next_pa = {}
        self.reservations, self.writes, self.instructions = [], [], []
        self.privilege = 3

    def lockThreadScheduler(self):
        self.locked = True

    def unlockThreadScheduler(self):
        self.locked = False

    def genPA(self, request):
        assert self.locked
        low, high = (int(s, 16) for s in request["Range"].split("-"))
        alignment, size = request["Align"], request["Size"]
        value = (self.next_pa.get(low, low) + alignment - 1) & -alignment
        if value + size > high + 1:
            raise RuntimeError("fixture allocation exhausted")
        self.next_pa[low] = value + size
        return value

    def reserveMemoryRange(self, *args):
        assert self.locked
        self.reservations.append(args)

    def writePhysicalMemory(self, *args):
        self.writes.append(args)

    def getPEstate(self, name):
        assert name == "PrivilegeLevel"
        return self.privilege

    def genInstruction(self, name, args):
        self.instructions.append((name, args))


class Load:
    def __init__(self, owner):
        self.owner = owner

    def load(self, reg, value):
        self.owner.instructions.append(("load", (reg, value)))


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.owner = Owner()

    def context(self, **overrides):
        args = dict(name="context", asid=1, vmid=1, table_ram=(0x88000000, 0x89000000),
                    data_ram=(0x84000000, 0x88000000), gva_range=(0x40000000, 0x41000000),
                    gpa_range=(0x60000000, 0x61000000),
                    table_gpa_range=(0x90000000, 0x91000000))
        args.update(overrides)
        context = PtgVmContext(self.owner, **args)
        self.addCleanup(context.close)
        return context

    def test_range_validation_precedes_reservations(self):
        for args in (dict(gva_range=(0x8000000000, 0x8000001000)),
                     dict(data_ram=(0x88000000, 0x89000000)),
                     dict(table_gpa_range=(0x60000000, 0x60100000)), dict(vmid=-1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.context(**args)
        self.assertEqual(self.owner.reservations, [])
        self.owner.genThreadID = 1
        with self.assertRaisesRegex(ValueError, "hart 0"):
            self.context()

    def test_mapping_alias_query_and_no_shadow_translation(self):
        c = self.context()
        spa = c.map(0x40000000, 0x60000000)
        c.map_alias(0x40010000, 0x60000000)
        self.assertEqual(c.translate(0x40000008), spa + 8)
        self.assertEqual(c.reverse(spa + 8), (0x40000008, 0x40010008))
        self.assertIsNone(c.lookup(0x40020000))
        # A read-only query observes PTG's current PTE, not cached FORCE mapping requests.
        c._backend.handle.remap_va(c.context_id, "G", 0x60000000, spa + 0x1000)
        self.assertEqual(c.translate(0x40000008), spa + 0x1008)
        self.assertEqual(c.reverse(spa + 8), ())

    def test_both_mixed_leaf_ranges_cover_the_whole_requested_span(self):
        c = self.context()
        for slot, levels in enumerate(((1, 0), (0, 1))):
            va, ga = 0x40200000 + slot * 0x200000, 0x60200000 + slot * 0x200000
            pa = c.map(va, ga, 0x200000, vs_level=levels[0], g_level=levels[1])
            for offset in (0, 0x1238, 0x1FFFFF):
                info = c.lookup(va + offset)
                self.assertEqual(info.size, 0x1000)
                self.assertEqual(c.translate(va + offset), pa + offset)
                self.assertEqual((info.vs_level, info.g_level), levels)

    def test_invalid_requests_do_not_allocate_or_partially_map(self):
        c = self.context()
        spa = c.map(0x40000000, 0x60000000)
        count = len(self.owner.reservations)
        for call in (
            lambda: c.map(0x40000000, 0x60001000),
            lambda: c.map(0x40001000, 0x60000000),
            lambda: c.map(0x40000001, 0x60002000),
            lambda: c.map(0x41000000, 0x60002000),
            lambda: c.map(0x40002000, 0x90000000),
            lambda: c.map(0x40002000, 0x60002000, g_perm=0x63),
            lambda: c.map(0x40002000, 0x60002000, vs_perm=0x6B),
        ):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(len(self.owner.reservations), count)
        self.assertEqual(c.translate(0x40000000), spa)

    def test_structural_permissions_are_not_access_authorization(self):
        c = self.context()
        c.map(0x40000000, 0x60000000, vs_perm=0x64)
        self.assertEqual(c.lookup(0x40000000).vs_perm, 0x64)  # X-only, not readable by HLV.

    def test_zero_spa_is_distinct_from_absence(self):
        c = self.context(data_ram=(0, 0x100000))
        self.assertEqual(c.map(0x40000000, 0x60000000), 0)
        self.assertEqual(c.translate(0x40000000), 0)
        self.assertEqual(c.reverse(0), (0x40000000,))
        self.assertIsNone(c.translate(0x40001000))

    def test_payload_ownership_and_freeze(self):
        c = self.context()
        spa = c.map(0x40000000, 0x60000000)
        with self.assertRaises(ValueError):
            c.initialize_data(c.table_pool.base, bytes(8))
        c.initialize_data(spa, bytes(8))
        c.publish()
        with self.assertRaisesRegex(RuntimeError, "immutable"):
            c.initialize_data(spa, bytes(8))
        with self.assertRaisesRegex(RuntimeError, "immutable"):
            c.map(0x40001000, 0x60001000)
        count = len(self.owner.reservations)
        c.close()
        self.assertEqual(len(self.owner.reservations), count)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            c.lookup(0x40000000)

    def test_activation_has_no_host_rewrites_and_orders_csr_fences(self):
        c = self.context()
        c.map(0x40000000, 0x60000000)
        c.publish()
        writes = len(self.owner.writes)
        with mock.patch.dict(sys.modules, {"riscv.Utils": types.SimpleNamespace(LoadGPR64=Load)}):
            c.activate()
            c.activate()
        self.assertEqual(len(self.owner.writes), writes)
        ops = [(name, args.get("csr")) for name, args in self.owner.instructions if name != "load"]
        expected = [("CSRRW#register#RISCV", 0x280), ("HFENCE.VVMA##RISCV", None),
                    ("CSRRW#register#RISCV", 0x680), ("HFENCE.GVMA##RISCV", None),
                    ("CSRRW#register#RISCV", 0x280), ("HFENCE.VVMA##RISCV", None),
                    ("CSRRS#register#RISCV", 0x600)]
        self.assertEqual(ops, expected * 2)

    def test_mutated_snapshot_refuses_activation_before_instructions(self):
        c = self.context()
        spa = c.map(0x40000000, 0x60000000)
        c.publish()
        c._backend.handle.remap_va(c.context_id, "G", 0x60000000, spa + 0x1000)
        with self.assertRaisesRegex(RuntimeError, "changed outside"):
            c.activate()
        self.assertEqual(c.state, "failed")
        self.assertEqual(self.owner.instructions, [])

    def test_writer_and_mapping_failures_fail_closed(self):
        for operation in ("map", "publish"):
            c = self.context(name=operation)
            if operation == "map":
                with mock.patch.object(c._backend.handle, "add_mapping", side_effect=RuntimeError("PTG")):
                    with self.assertRaises(RuntimeError):
                        c.map(0x40000000, 0x60000000)
            else:
                c.map(0x40000000, 0x60000000)
                with mock.patch.object(self.owner, "writePhysicalMemory", side_effect=OSError("writer")):
                    with self.assertRaises(OSError):
                        c.publish()
            self.assertEqual(c.state, "failed")
            with self.assertRaises(RuntimeError):
                c.activate()
        self.assertFalse(self.owner.locked)

    def test_activation_preconditions_and_identity(self):
        c = self.context()
        for field in ("context_id", "vmid", "asid"):
            with self.assertRaises(AttributeError):
                setattr(c, field, 3)
        for scratch in (0, 32, True):
            with self.assertRaises(ValueError):
                c.activate(scratch)
        self.owner.privilege = 1
        with self.assertRaisesRegex(ValueError, "M-mode"):
            c.activate()
        self.assertEqual(self.owner.writes, [])

    def test_host_failures_unlock_and_prevent_activation(self):
        c = self.context()
        with mock.patch.object(self.owner, "genPA", side_effect=OSError("allocation")):
            with self.assertRaises(OSError):
                c.map(0x40000000, 0x60000000)
        self.assertEqual(c.state, "failed")
        self.assertFalse(self.owner.locked)
        other = self.context(name="other", vmid=2)
        spa = other.map(0x40000000, 0x60000000)
        with mock.patch.object(self.owner, "writePhysicalMemory", side_effect=OSError("data")):
            with self.assertRaises(OSError):
                other.initialize_data(spa, bytes(8))
        self.assertEqual(other.state, "failed")
        with self.assertRaises(RuntimeError):
            other.activate()


if __name__ == "__main__":
    unittest.main()
