import ctypes
import os
import sys
import unittest
from unittest import mock

FORCE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(FORCE_ROOT, "py"))

from riscv.paging.PtgBackend import (  # noqa: E402
    PTG_FAULT_ACCESS_READ,
    PTG_FAULT_ADDRESS_STAGE_NATIVE,
    PTG_FAULT_BUFFER_TOO_SMALL,
    PTG_FAULT_INSUFFICIENT_CANDIDATES,
    PTG_FAULT_INVALID_ARGUMENT,
    PTG_FAULT_OK,
    PTG_FAULT_ONE_PER_WALK,
    PTG_FAULT_PRIV_S,
    PTG_FAULT_SCOPE_DIRECT,
    PTG_FAULT_SELECTION_EXACT_COUNT,
    PTG_FAULT_SELECTION_EXACT_ONE,
    PTG_FAULT_TARGET_NOT_FOUND,
    PTG_FAULT_UNSUITABLE_TARGET,
    PTG_FAULT_UNSUPPORTED_COMBINATION,
    PTG_FAULT_VALID_ACTUAL_MCAUSE,
    PTG_FAULT_VALID_EXPECTED_MCAUSE,
    PTG_FAULT_VALID_NEW_PTE,
    PTG_FAULT_VALID_OLD_PTE,
    PTG_FAULT_VALID_PTE_PA,
    PTG_FAULT_VERIFY_REQUIRE_FAULT,
    PTG_STAGE_S,
    PtgBackend,
    PtgAllocationError,
    PtgPlacement,
    PtgPlacementConfigV1,
    PtgLevelPlacementV1,
    PtgExportBlockV1,
    PtgFaultRequestV2,
    PtgFaultResultV2,
    PtgHandle,
    PtgMappingError,
    PtgMappingQueryV1,
    PtgMappingRecordV1,
    PtgVmConfigV2,
)


class PtgReservedPoolTest(unittest.TestCase):
    class Owner:
        def __init__(self, base=0x88000000):
            self.base = base
            self.events = []
            self.reservations = []
            self.writes = []
            self.locked = False

        def lockThreadScheduler(self):
            self.events.append("lock")
            self.locked = True

        def unlockThreadScheduler(self):
            self.events.append("unlock")
            self.locked = False

        def genPA(self, request):
            if not self.locked:
                raise AssertionError("selection outside scheduler lock")
            self.events.append(("select", request))
            return self.base

        def reserveMemoryRange(self, name, base, size, bank, is_virtual):
            if not self.locked:
                raise AssertionError("reservation outside scheduler lock")
            self.events.append("reserve")
            self.reservations.append((name, base, size, bank, is_virtual))

        def unreserveMemory(self, *args):
            raise AssertionError("PTG teardown must not release live ISS backing")

        def writePhysicalMemory(self, pa, data, bank):
            self.writes.append((pa, data, bank))

    def setUp(self):
        self.owner = self.Owner()

    def backend(self):
        backend = PtgBackend.with_reserved_table_pool(
            self.owner, "OwnedTables", 0x100000, 0x88000000, 0x89000000
        )
        self.addCleanup(backend.destroy)
        return backend

    def mapped(self):
        backend = self.backend()
        ctx = backend.create_two_stage_context(
            asid=1, vmid=1, gpa_base=0x90000000, gpa_limit=0x91000000
        )
        backend.handle.add_mapping(ctx, "VS", 0x40000000, 0x60000000, 0x1000, perm=0x63)
        backend.handle.add_mapping(ctx, "G", 0x60000000, 0xA0000000, 0x1000, perm=0x73)
        return backend, ctx

    def test_selection_reservation_and_endpoints(self):
        backend = self.backend()
        self.assertEqual(self.owner.events, ["lock", ("select", {
            "Size": 0x100000, "Align": 0x4000, "Type": "D", "Bank": 0,
            "ForceNewAddr": 1, "Range": "0x88000000-0x88ffffff",
        }), "reserve", "unlock"])
        self.assertEqual(self.owner.reservations,
                         [("OwnedTables", 0x88000000, 0x100000, 0, False)])
        self.assertEqual((backend.table_pool.base, backend.table_pool.limit),
                         (0x88000000, 0x88100000))
        backend.destroy()
        self.assertEqual(len(self.owner.reservations), 1)

    def test_invalid_pool_and_bad_allocator_output_never_reserve(self):
        for size, base, limit in ((0, 0x88000000, 0x89000000),
                                  (0x1001, 0x88000000, 0x89000000),
                                  (0x10000, 0, 0x100000),
                                  (0x10000, 0x88000000, 0x88001000)):
            with self.subTest(size=size, base=base), self.assertRaises(ValueError):
                PtgBackend.with_reserved_table_pool(self.owner, "bad", size, base, limit)
        self.assertEqual(self.owner.events, [])
        for result in (0x88000001, 0x87000000, 0x88FFC000):
            self.owner.base = result
            with self.assertRaisesRegex(RuntimeError, "outside its RAM constraint"):
                self.backend()
            self.assertFalse(self.owner.locked)
            self.assertEqual(self.owner.reservations, [])

    def test_selection_and_reservation_failures_unlock(self):
        for method in ("genPA", "reserveMemoryRange"):
            with mock.patch.object(self.owner, method, side_effect=OSError("host failure")):
                with mock.patch.object(
                    PtgHandle, "register_pa_region",
                    side_effect=AssertionError("registered after host failure")
                ):
                    with self.assertRaisesRegex(OSError, "host failure"):
                        self.backend()
            self.assertFalse(self.owner.locked)
            self.assertEqual(self.owner.reservations, [])

    def test_failed_ptg_registration_retains_reservation(self):
        with mock.patch.object(PtgHandle, "register_pa_region",
                               side_effect=RuntimeError("PTG registration failed")):
            with self.assertRaisesRegex(RuntimeError, "registration failed"):
                self.backend()
        self.assertFalse(self.owner.locked)
        self.assertEqual(len(self.owner.reservations), 1)

    def test_only_spa_not_gpa_is_authorized(self):
        backend, ctx = self.mapped()
        with backend.capture_export_layout(ctx, "VS") as vs:
            with backend.capture_export_layout(ctx, "G") as gs:
                blocks, _ = vs.read()
                self.assertTrue(all(b.source_address >= 0x90000000 for b in blocks))
                backend.load_export_layouts((vs, gs), self.owner)
        self.assertTrue(self.owner.writes)
        self.assertTrue(all(0x88000000 <= pa and pa + len(data) <= 0x88100000 and bank == 0
                            for pa, data, bank in self.owner.writes))

    def test_wrong_writer_bank_and_outside_spa_rejected_before_writes(self):
        backend, ctx = self.mapped()
        with backend.capture_export_layout(ctx, "VS") as layout:
            with self.assertRaises(ValueError):
                backend.load_export_layouts((layout,), self.Owner())
            with self.assertRaises(ValueError):
                backend.load_export_layouts((layout,), self.owner, mem_bank=1)
            read = layout.read
            for pa in (backend.table_pool.base - 0x1000, backend.table_pool.limit - 1):
                def outside():
                    blocks, data = read()
                    blocks[0].spa = pa
                    return blocks, data
                with mock.patch.object(layout, "read", side_effect=outside):
                    with self.assertRaisesRegex(ValueError, "outside the reserved table pool"):
                        backend.load_export_layouts((layout,), self.owner)
            self.assertEqual(self.owner.writes, [])

    def test_one_context_one_setup_no_legacy_escape(self):
        backend, ctx = self.mapped()
        h = backend.handle
        operations = (
            lambda: h.create_context(2, 1),
            lambda: h.set_s_stage(ctx, "Sv39"),
            lambda: h.set_gs_stage(ctx, "Sv39x4"),
            lambda: h.register_pa_region(0xA0000000, 0xB0000000),
            lambda: h.register_gpa_region(2, 0x90000000, 0x91000000),
            lambda: h.register_gpa_region(1, 0x90000000, 0x91000000),
            lambda: h.restore_state("not-opened"),
            lambda: backend.load_to_force(ctx, "VS", self.owner),
        )
        for operation in operations:
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(self.owner.writes, [])

    def test_bad_g_root_poisoned_before_export(self):
        backend = self.backend()
        with mock.patch.object(backend.handle, "get_hgatp",
                               return_value=(8 << 60) | (0x88001000 >> 12)):
            with self.assertRaisesRegex(RuntimeError, "G-stage root"):
                backend.create_two_stage_context(
                    vmid=1, gpa_base=0x90000000, gpa_limit=0x91000000
                )
        with self.assertRaisesRegex(RuntimeError, "setup failed"):
            backend.capture_export_layout(backend.handle._pool_context, "VS")
        self.assertEqual(self.owner.writes, [])
        self.assertEqual(len(self.owner.reservations), 1)


class PtgPlacementWrapperTest(unittest.TestCase):
    def setUp(self):
        self.backend = PtgBackend()
        self.addCleanup(self.backend.destroy)
        self.h = self.backend.handle

    def root(self, ctx, stage="S"):
        csr = {"S": self.h.get_satp, "VS": self.h.get_vsatp, "G": self.h.get_hgatp}[stage](ctx)
        return (csr & ((1 << 44) - 1)) << 12

    def test_abi_and_negative_status_domain(self):
        self.assertEqual((ctypes.sizeof(PtgPlacementConfigV1),
                          ctypes.sizeof(PtgLevelPlacementV1)), (40, 32))
        self.assertEqual(PtgPlacementConfigV1.pt_align.offset, 24)
        self.assertEqual(PtgLevelPlacementV1.base.offset, 16)
        with self.assertRaises(PtgAllocationError) as failure:
            self.backend.configure_pa_placement(PtgPlacement())
        self.assertEqual(failure.exception.status, -7)
        self.assertNotIsInstance(failure.exception, PtgMappingError)

    def test_immutable_input_and_python_validation(self):
        windows = [[2, 0x2000, 0x3000], [1, 0x1000, 0x2000]]
        policy = PtgPlacement(levels=windows)
        windows[0][1] = 99
        self.assertEqual(policy.levels, ((2, 0x2000, 0x3000), (1, 0x1000, 0x2000)))
        with self.assertRaises(AttributeError):
            policy.alignment = 3
        for kwargs in ({"alignment": 3}, {"base": -1}, {"base": True},
                       {"limit": 1 << 64}, {"base": 2, "limit": 1},
                       {"levels": ((5, 1, 2),)}, {"levels": ((True, 1, 2),)},
                       {"levels": ((0, 1, 3), (1, 2, 4))}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                PtgPlacement(**kwargs)
        with self.assertRaises(ValueError):
            self.backend.configure_pa_placement(policy._replace(alignment=3))

    def test_zero_root_is_valid(self):
        self.h.register_pa_region(0, 0x10000)
        self.backend.configure_pa_placement(PtgPlacement(0, 0x4000))
        ctx = self.backend.create_s_stage_context()
        self.assertEqual(self.root(ctx), 0)
        self.assertEqual(self.h.get_satp(ctx) >> 60, 8)

    def test_level_priority_order_and_general_fallback(self):
        self.h.register_pa_region(0xA0000000, 0xA0100000)
        self.backend.configure_pa_placement(PtgPlacement(levels=(
            (2, 0xA0020000, 0xA0021000), (2, 0xA0010000, 0xA0011000),
        )))
        roots = [self.root(self.backend.create_s_stage_context(asid=i)) for i in (1, 2, 3)]
        self.assertEqual(roots, [0xA0020000, 0xA0010000, 0xA0000000])

    def test_vmid_local_policies_before_two_stage_setup(self):
        self.h.register_pa_region(0xA0000000, 0xA0100000)
        for vmid, base in ((1, 0x50000000), (2, 0x60000000)):
            ctx = self.backend.create_two_stage_context(
                asid=vmid, vmid=vmid, gpa_base=base, gpa_limit=base + 0x100000,
                gpa_placement=PtgPlacement(levels=((2, base + 0x8000, base + 0x9000),)),
            )
            self.assertEqual(self.root(ctx, "VS"), base + 0x8000)

    def test_no_space_is_not_false_success(self):
        self.h.register_pa_region(0xA0000000, 0xA0001000)
        self.backend.configure_pa_placement(PtgPlacement())
        ctx = self.h.create_context(1, 1)
        with self.assertRaises(PtgAllocationError) as failure:
            self.h.set_gs_stage(ctx, "Sv39x4")
        self.assertEqual(failure.exception.status, -9)
        self.assertEqual(self.h.get_hgatp(ctx), 0)

    def test_online_policy_does_not_move_or_stale_export(self):
        self.h.register_pa_region(0xA0000000, 0xA0100000)
        self.backend.configure_pa_placement(PtgPlacement())
        ctx = self.backend.create_s_stage_context()
        self.h.add_mapping(ctx, "S", 0x4000, 0x80000000, 0x1000)
        csr = self.h.get_satp(ctx)
        with self.backend.capture_export_layout(ctx, "S") as layout:
            before, data = layout.read()
            self.backend.configure_pa_placement(PtgPlacement(0xA0080000, 0xA0100000, 0x8000))
            after, current = layout.read()
            self.assertEqual(([bytes(b) for b in before], data),
                             ([bytes(b) for b in after], current))
            with self.assertRaises(PtgAllocationError) as failure:
                self.backend.configure_pa_placement(PtgPlacement(0xB0000000, 0xB0010000))
            self.assertEqual(failure.exception.status, -4)
            self.assertEqual(self.h.get_satp(ctx), csr)
            layout.read()
        new = self.backend.create_s_stage_context(asid=2)
        self.assertEqual(self.root(new), 0xA0080000)

    def test_mapping_failure_keeps_prior_mapping_and_stage_failure_keeps_root(self):
        self.h.register_pa_region(0xA0000000, 0xA0003000)
        self.backend.configure_pa_placement(PtgPlacement())
        ctx = self.backend.create_s_stage_context()
        self.h.add_mapping(ctx, "S", 0x4000, 0x84000000, 0x1000, perm=0x63)
        csr = self.h.get_satp(ctx)
        for operation in (
            lambda: self.h.add_mapping(ctx, "S", 0x40000000, 0x85000000, 0x1000),
            lambda: self.h.set_s_stage(ctx, "Sv48"),
        ):
            with self.assertRaises(PtgAllocationError) as failure:
                operation()
            self.assertEqual(failure.exception.status, -9)
            self.assertEqual(self.h.get_satp(ctx), csr)
            self.assertEqual(self.backend.query_mappings(ctx, "S", 0x4008)[0].matched_pa,
                             0x84000008)

    def test_random_allocation_failure_is_not_empty_success(self):
        self.h.register_pa_region(0xA0000000, 0xA0001000)
        self.backend.configure_pa_placement(PtgPlacement())
        ctx = self.backend.create_s_stage_context()
        with self.assertRaises(PtgAllocationError) as failure:
            self.backend.generate_random(ctx, "S", 0x4000, 0x10000, 0x84000000, 0x84010000,
                                         count=2, seed=1, access_types=3, flags_a=1,
                                         flags_d=1, flags_u=2)
        self.assertEqual(failure.exception.status, -9)

    def test_owned_pool_failed_policy_preserves_reservation_and_usability(self):
        owner = PtgReservedPoolTest.Owner()
        backend = PtgBackend.with_reserved_table_pool(
            owner, "placement", 0x100000, 0x88000000, 0x89000000
        )
        self.addCleanup(backend.destroy)
        with self.assertRaises(PtgAllocationError):
            backend.configure_pa_placement(PtgPlacement(0xA0000000, 0xA0010000))
        self.assertFalse(backend.handle._pool_failed)
        ctx = backend.create_two_stage_context(vmid=1, gpa_base=0x90000000, gpa_limit=0x91000000)
        with self.assertRaises(ValueError):
            backend.configure_gpa_placement(2, PtgPlacement())
        self.assertNotEqual(backend.handle.get_hgatp(ctx), 0)
        backend.destroy()
        self.assertEqual(len(owner.reservations), 1)

    def test_missing_capability_before_host_reservation(self):
        owner = PtgReservedPoolTest.Owner()
        with mock.patch.object(PtgHandle, "_require_placement_v1",
                               side_effect=RuntimeError("placement v1 unavailable")):
            with self.assertRaisesRegex(RuntimeError, "placement v1 unavailable"):
                PtgBackend.with_reserved_table_pool(
                    owner, "placement", 0x100000, 0x88000000, 0x89000000
                )
        self.assertEqual(owner.events, [])

    def test_missing_symbol_and_destroyed_handle(self):
        real_lib = self.h._lib
        class MissingPlacement:
            def __getattr__(self, name):
                if name == "ptg_configure_pa_placement_v1":
                    raise AttributeError(name)
                return getattr(real_lib, name)
        self.h._lib = MissingPlacement()
        with self.assertRaisesRegex(RuntimeError, "lacks checked allocation/placement"):
            self.backend.configure_pa_placement(PtgPlacement())
        self.assertFalse(self.h._placement_v1_ready)
        self.h._lib = real_lib
        self.h.destroy()
        with self.assertRaisesRegex(RuntimeError, "destroyed"):
            self.backend.configure_pa_placement(PtgPlacement())


class PtgContractsWrapperTest(unittest.TestCase):
    def setUp(self):
        self.backend = PtgBackend()
        self.addCleanup(self.backend.destroy)
        self.h = self.backend.handle
        self.h.register_pa_region(0xA0000000, 0xB0000000)
        self.ctx = self.backend.create_s_stage_context("Sv39")
        self.h.add_mapping(self.ctx, "S", 0x4000, 0xA8000000, 0x1000, perm=3)
        self.assertEqual(self.h.last_error()[0], 0)

    def writer(self, fail_at=None):
        class Writer:
            def __init__(self):
                self.calls = []

            def writePhysicalMemory(self, address, data, bank):
                self.calls.append((address, data, bank))
                if fail_at == len(self.calls):
                    raise OSError("target RAM write failed")

        return Writer()

    def raw(self, ctx, stage):
        layout = self.h.get_blocks(ctx, stage)
        self.assertTrue(layout)
        try:
            return {
                block.pa: ctypes.string_at(block.data, block.size)
                for block in layout.contents.blocks[:layout.contents.num_blocks]
            }
        finally:
            self.h.free_blocks(layout)

    def two_stage(self):
        self.h.register_gpa_region(1, 0x50000000, 0x50200000)
        ctx = self.h.create_context(1, 1)
        self.h.set_gs_stage(ctx, "Sv39x4")
        self.h.add_mapping(ctx, "G", 0x50000000, 0xA4000000, 0x200000, 1, 0x73)
        self.h.set_vs_stage(ctx, "Sv39")
        self.h.add_mapping(ctx, "VS", 0x40000000, 0x60000000, 0x1000, perm=0x63)
        self.assertEqual(self.h.last_error()[0], 0)
        return ctx

    def test_new_abi_and_query_zero_aliases_no_ad_write(self):
        self.assertEqual((ctypes.sizeof(PtgMappingQueryV1), ctypes.sizeof(PtgMappingRecordV1),
                          ctypes.sizeof(PtgExportBlockV1)), (40, 160, 48))
        self.h.add_mapping(self.ctx, "S", 0, 0, 0x1000, perm=0x63)
        self.h.add_mapping(self.ctx, "S", 0x8000, 0xA8000000, 0x1000, perm=3)
        before = self.raw(self.ctx, "S")
        zero = self.backend.query_mappings(self.ctx, "S", 0)
        self.assertEqual((len(zero), zero[0].valid_fields, zero[0].matched_pa), (1, 31, 0))
        self.assertEqual(self.backend.query_mappings(self.ctx, "S", 0x10000), [])
        records = self.backend.query_mappings(self.ctx, "S", 0xA8000008, direction="reverse")
        self.assertEqual(sorted(r.matched_va for r in records), [0x4008, 0x8008])
        self.assertTrue(all(r.raw_perm == 3 for r in records))
        self.assertEqual(self.raw(self.ctx, "S"), before)
        records[0].matched_pa = 99
        self.assertEqual(self.backend.query_mappings(self.ctx, "S", 0x4008)[0].matched_pa,
                         0xA8000008)

    def test_logical_current_fault_metadata(self):
        req = self.h.create_fault_request_v2()
        req.stage, req.scope, req.address_kind, req.selection_mode = 0, 0, 0, 1
        req.fault_cause, req.verification_mode = 1, 0
        req.target_level, req.has_target_address, req.target_address, req.dry_run = 0, 1, 0x4000, 0
        self.assertEqual(self.h.inject_fault_v2(self.ctx, req)[0], 0)
        current = self.backend.query_mappings(self.ctx, "S", 0x4008)[0]
        logical = self.backend.query_mappings(self.ctx, "S", 0x4008, domain="logical")[0]
        self.assertEqual((current.valid_fields, current.current.leaf_level), (21, -1))
        self.assertEqual((logical.valid_fields, logical.matched_pa), (29, 0xA8000008))

    def test_versioned_status_does_not_consult_legacy_error(self):
        with mock.patch.object(self.h, "last_error", side_effect=AssertionError("legacy status")):
            with self.assertRaises(PtgMappingError) as error:
                self.backend.query_mappings(0xFFFFFFFF, "S", 0)
            self.assertEqual(error.exception.status, 3)

    def test_input_ranges_fail_before_native_conversion(self):
        for args in ((-1, "S", 0), (1 << 32, "S", 0), (self.ctx, "invalid", 0),
                     (self.ctx, "S", -1), (self.ctx, "S", 1 << 64)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.backend.query_mappings(*args)
        with self.assertRaises(ValueError):
            self.backend.query_mappings(self.ctx, "S", 8, direction="enumerate")

    def test_missing_capability_fails_without_legacy_fallback(self):
        library = self.h._lib

        class Missing:
            def __getattr__(self, name):
                if name == "ptg_export_layout_read_v1":
                    raise AttributeError(name)
                return getattr(library, name)

        with mock.patch.object(self.h, "_lib", Missing()):
            with self.assertRaisesRegex(RuntimeError, "lacks Mapping Query/Strict Export v1"):
                self.backend.capture_export_layout(self.ctx, "S")
        self.assertFalse(self.h._mapping_v1_ready)

    def test_close_once_and_closed_reads_rejected(self):
        layout = self.backend.capture_export_layout(self.ctx, "S")
        free = self.h._lib.ptg_export_layout_free_v1
        with mock.patch.object(self.h._lib, "ptg_export_layout_free_v1", wraps=free) as release:
            with self.assertRaisesRegex(OSError, "consumer failure"):
                with layout:
                    raise OSError("consumer failure")
            layout.close()
            self.assertEqual(release.call_count, 1)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            layout.read()

    def test_parent_destroy_invalidates_captures_without_double_free(self):
        layout = self.backend.capture_export_layout(self.ctx, "S")
        self.backend.destroy()
        self.assertTrue(layout.closed)
        with mock.patch.object(self.h._lib, "ptg_export_layout_free_v1",
                               side_effect=AssertionError("double free")):
            layout.close()
            with self.assertRaisesRegex(RuntimeError, "destroyed"):
                self.backend.capture_export_layout(self.ctx, "S")

    def test_free_failure_is_reported_by_explicit_close(self):
        layout = self.backend.capture_export_layout(self.ctx, "S")
        with mock.patch.object(self.h._lib, "ptg_export_layout_free_v1", return_value=1):
            with self.assertRaises(PtgMappingError) as error:
                layout.close()
            self.assertEqual(error.exception.status, 1)
            self.assertFalse(layout.closed)
        layout.close()

    def test_frozen_vs_spa_survives_g_fault_with_current_bytes(self):
        ctx = self.two_stage()
        with self.backend.capture_export_layout(ctx, "VS") as vs, \
                self.backend.capture_export_layout(ctx, "G") as gs:
            self.h._lib.ptg_context_clear.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int
            ]
            self.h._lib.ptg_context_clear.restype = None
            self.h._lib.ptg_context_clear(self.h._handle, ctx, 2)
            with self.assertRaises(PtgMappingError) as error:
                self.backend.capture_export_layout(ctx, "VS")
            self.assertEqual(error.exception.status, 7)
            self.h.remap_va(ctx, "VS", 0x40000008, 0x61000000)
            writer = self.writer()
            with mock.patch.object(self.h._lib, "ptg_dump_binary_write",
                                   side_effect=AssertionError("legacy fallback")):
                self.backend.load_export_layouts((vs, gs), writer)
            expected = {
                0xA4000000 + gpa - 0x50000000: data
                for gpa, data in self.raw(ctx, "VS").items()
            }
            expected.update(self.raw(ctx, "G"))
            self.assertEqual({pa: data for pa, data, bank in writer.calls}, expected)
            self.assertTrue(all(bank == 0 for _, _, bank in writer.calls))

    def test_batch_stale_second_stage_writes_nothing_and_never_recaptures(self):
        self.h.set_gs_stage(self.ctx, "Sv39x4")
        self.h.add_mapping(self.ctx, "G", 0x8000, 0xA9000000, 0x1000, perm=0x73)
        with self.backend.capture_export_layout(self.ctx, "S") as first, \
                self.backend.capture_export_layout(self.ctx, "G") as second:
            self.h.add_mapping(self.ctx, "G", 0x40000000, 0xA9001000, 0x1000, perm=0x73)
            writer = self.writer()
            with mock.patch.object(self.h._lib, "ptg_export_layout_create_v1",
                                   side_effect=AssertionError("automatic recapture")):
                with self.assertRaises(PtgMappingError) as error:
                    self.backend.load_export_layouts((first, second), writer)
            self.assertEqual(error.exception.status, 6)
            self.assertEqual(writer.calls, [])

    def test_writer_failure_stops_and_does_not_claim_rollback(self):
        with self.backend.capture_export_layout(self.ctx, "S") as layout:
            blocks, data = layout.read()
            self.assertGreater(len(blocks), 2)
            writer = self.writer(fail_at=2)
            with self.assertRaisesRegex(OSError, "target RAM write failed"):
                self.backend.load_export_layouts((layout,), writer, mem_bank=2)
            self.assertEqual(len(writer.calls), 2)
            self.assertEqual(writer.calls[0], (blocks[0].spa, data[:blocks[0].size], 2))

    def test_zero_spa_is_written_as_a_valid_address(self):
        ctx = self.two_stage()
        self.h.register_pa_region(0, 0x200000)
        self.h.remap_va(ctx, "G", 0x50000000, 0)
        self.assertEqual(self.h.last_error()[0], 0)
        with self.backend.capture_export_layout(ctx, "VS") as layout:
            writer = self.writer()
            self.backend.load_export_layouts((layout,), writer)
            self.assertEqual(writer.calls[0][0], 0)
            self.assertEqual(writer.calls[0][1], self.raw(ctx, "VS")[0x50000000])

    def test_foreign_mixed_context_and_overlapping_batches_rejected(self):
        other = PtgBackend()
        self.addCleanup(other.destroy)
        other_ctx = other.create_s_stage_context("Sv39", pa_base=0xC0000000, pa_limit=0xD0000000)
        other.handle.add_mapping(other_ctx, "S", 0x4000, 0xC8000000, 0x1000, perm=0x63)
        ctx2 = self.h.create_context(2, 0)
        self.h.set_s_stage(ctx2, "Sv39")
        self.h.add_mapping(ctx2, "S", 0x8000, 0xA7000000, 0x1000, perm=0x63)
        writer = self.writer()
        with self.backend.capture_export_layout(self.ctx, "S") as first, \
                self.backend.capture_export_layout(ctx2, "S") as second, \
                other.capture_export_layout(other_ctx, "S") as foreign:
            for layouts in ((), (foreign,), (first, second), (first, first)):
                with self.subTest(layouts=layouts), self.assertRaises(ValueError):
                    self.backend.load_export_layouts(layouts, writer)
        self.assertEqual(writer.calls, [])

    def test_bad_export_metadata_never_reaches_writer(self):
        with self.backend.capture_export_layout(self.ctx, "S") as layout:
            read = self.h._lib.ptg_export_layout_read_v1

            def corrupt(*args):
                status = read(*args)
                if args[2] is not None and status == 0:
                    args[2][0].source_kind = 2  # S must use SPA, not GPA.
                return status

            writer = self.writer()
            with mock.patch.object(self.h._lib, "ptg_export_layout_read_v1", side_effect=corrupt):
                with self.assertRaisesRegex(RuntimeError, "invalid block metadata"):
                    self.backend.load_export_layouts((layout,), writer)
            self.assertEqual(writer.calls, [])

    def test_query_size_change_is_not_silently_truncated(self):
        self.h._require_mapping_v1()
        query = self.h._lib.ptg_mapping_query_v1

        def change_count(*args):
            status = query(*args)
            if args[3] is not None and status == 0:
                ctypes.cast(args[6], ctypes.POINTER(ctypes.c_uint32)).contents.value += 1
            return status

        with mock.patch.object(self.h._lib, "ptg_mapping_query_v1", side_effect=change_count):
            with self.assertRaisesRegex(RuntimeError, "changed count"):
                self.backend.query_mappings(self.ctx, "S", 0x4000)

    def test_query_fill_error_and_malformed_domain_are_rejected(self):
        self.h._require_mapping_v1()
        query = self.h._lib.ptg_mapping_query_v1

        def bad_domain(*args):
            status = query(*args)
            if args[3] is not None and status == 0:
                args[3][0].output_kind = 2  # S queries return SPA, not GPA.
            return status

        with mock.patch.object(self.h._lib, "ptg_mapping_query_v1", side_effect=bad_domain):
            with self.assertRaisesRegex(RuntimeError, "invalid record metadata"):
                self.backend.query_mappings(self.ctx, "S", 0x4000)

        def small_fill(*args):
            return 5 if args[3] is not None else query(*args)

        with mock.patch.object(self.h._lib, "ptg_mapping_query_v1", side_effect=small_fill):
            with self.assertRaises(PtgMappingError) as error:
                self.backend.query_mappings(self.ctx, "S", 0x4000)
            self.assertEqual((error.exception.status, error.exception.operation),
                             (5, "read mapping query"))

    def test_export_size_change_and_native_capacity_error_propagate(self):
        with self.backend.capture_export_layout(self.ctx, "S") as layout:
            read = self.h._lib.ptg_export_layout_read_v1

            def change_size(*args):
                status = read(*args)
                if args[2] is not None and status == 0:
                    ctypes.cast(args[8], ctypes.POINTER(ctypes.c_uint64)).contents.value -= 1
                return status

            with mock.patch.object(
                self.h._lib, "ptg_export_layout_read_v1", side_effect=change_size
            ):
                with self.assertRaisesRegex(RuntimeError, "changed size"):
                    layout.read()
            with mock.patch.object(self.h._lib, "ptg_export_layout_read_v1", return_value=5):
                with self.assertRaises(PtgMappingError) as error:
                    layout.read()
                self.assertEqual(error.exception.status, 5)


class PtgFaultV2CtypesTest(unittest.TestCase):
    def setUp(self):
        self.ptg = PtgHandle()
        self.ptg.register_pa_region(0x80000000, 0x90000000)
        self.context = self.ptg.create_context(asid=1)
        self.ptg.set_s_stage(self.context, "Sv39")
        self.ptg.add_mapping(
            self.context, "S", 0x4000, 0x84000000, 0x1000, leaf_level=0, perm=7
        )
        self.assertEqual(self.ptg.last_error()[0], 0)

    def tearDown(self):
        self.ptg.destroy()

    def snapshot(self):
        return tuple(sorted(self.ptg.get_force_blocks(self.context, "S")))

    def test_force_memory_write_failure_propagates_and_stops(self):
        blocks = self.ptg.get_force_blocks(self.context, "S")
        self.assertGreater(len(blocks), 2)

        class Writer:
            def __init__(self):
                self.calls = []

            def writePhysicalMemory(self, pa, data, bank):
                self.calls.append((pa, data, bank))
                if len(self.calls) == 2:
                    raise OSError("FORCE memory write failed")

        writer = Writer()
        with self.assertRaisesRegex(OSError, "FORCE memory write failed"):
            self.ptg.load_to_force(self.context, "S", writer, mem_bank=2)
        self.assertEqual(writer.calls, [(pa, data, 2) for pa, data in blocks[:2]])

    def test_force_export_error_is_not_an_empty_success(self):
        class Writer:
            def writePhysicalMemory(self, pa, data, bank):
                raise AssertionError("export failure must precede FORCE writes")

        with self.assertRaisesRegex(RuntimeError, r"ctx=4294967295 stage=S.*\(-2\)"):
            self.ptg.get_force_blocks(0xFFFFFFFF, "S")
        with self.assertRaisesRegex(RuntimeError, r"ctx=4294967295 stage=S.*\(-2\)"):
            self.ptg.load_to_force(0xFFFFFFFF, "S", Writer())

    def test_force_export_callback_exception_propagates(self):
        with mock.patch(
            "riscv.paging.PtgBackend.ctypes.string_at",
            side_effect=MemoryError("snapshot allocation failed"),
        ) as copy_bytes:
            with self.assertRaisesRegex(MemoryError, "snapshot allocation failed"):
                self.ptg.get_force_blocks(self.context, "S")
            copy_bytes.assert_called_once()
        self.assertTrue(self.ptg.get_force_blocks(self.context, "S"))

    def test_mapping_index_exact_keys_aliases_and_no_pte_mutation(self):
        aliases = [0x4000] + [0x10000 + index * 0x1000 for index in range(10)]
        aliases.append(0xFFFFFFC000004000)
        for va in aliases[1:]:
            self.ptg.add_mapping(self.context, "S", va, 0x84000000, 0x1000, perm=0x67)
            self.assertEqual(self.ptg.last_error()[0], 0)
        before = self.snapshot()
        for va in aliases:
            self.assertEqual(self.ptg.mapping_index_pa(self.context, "S", va), 0x84000000)
        self.assertEqual(
            sorted(self.ptg.mapping_index_vas(self.context, "S", 0x84000000)), sorted(aliases)
        )
        self.assertEqual(self.ptg.mapping_index_vas(self.context, "S", 0x88000000), [])
        self.assertEqual(self.snapshot(), before)

    def test_mapping_index_context_stage_and_64bit_addresses(self):
        self.ptg.register_gpa_region(1, 0x90000000, 0xA0000000)
        ctx = self.ptg.create_context(asid=2, vmid=1)
        self.ptg.set_vs_stage(ctx, "Sv39")
        self.ptg.set_gs_stage(ctx, "Sv39x4")
        self.ptg.add_mapping(ctx, "VS", 0x40000000, 0x10082000000, 0x1000, perm=0x67)
        self.assertEqual(self.ptg.last_error()[0], 0)
        self.ptg.add_mapping(ctx, "G", 0x10082000000, 0x184000000, 0x1000, perm=0x77)
        self.assertEqual(self.ptg.last_error()[0], 0)
        self.assertEqual(self.ptg.mapping_index_pa(ctx, "VS", 0x40000000), 0x10082000000)
        self.assertEqual(self.ptg.mapping_index_pa(ctx, "G", 0x10082000000), 0x184000000)
        self.assertEqual(self.ptg.mapping_index_vas(ctx, "VS", 0x10082000000), [0x40000000])
        self.assertEqual(self.ptg.mapping_index_vas(ctx, "G", 0x184000000), [0x10082000000])
        self.assertEqual(self.ptg.mapping_index_vas(ctx, "VS", 0x84000000), [])

    def test_mapping_index_errors_are_not_missing_entries(self):
        for query in (self.ptg.mapping_index_pa, self.ptg.mapping_index_vas):
            with self.subTest(query=query.__name__):
                with self.assertRaisesRegex(RuntimeError, r"ctx=4294967295.*\(-2\)"):
                    query(0xFFFFFFFF, "S", 0)
                with self.assertRaisesRegex(RuntimeError, r"stage=G.*\(-3\)"):
                    query(self.context, "G", 0)
        self.ptg.destroy()
        for query in (self.ptg.mapping_index_pa, self.ptg.mapping_index_vas):
            with self.assertRaisesRegex(RuntimeError, r"\(-1\)"):
                query(self.context, "S", 0)

    def test_mapping_index_rejects_changing_alias_counts(self):
        for counts in ([1, 0], [1, 2]):
            with self.subTest(counts=counts), mock.patch.object(
                self.ptg._lib, "ptg_mapping_find_vas", side_effect=counts
            ) as query:
                with self.assertRaisesRegex(RuntimeError, "changed during alias query"):
                    self.ptg.mapping_index_vas(self.context, "S", 0x84000000)
                self.assertEqual(query.call_count, 2)

    def exact_request(self, dry_run=1):
        request = self.ptg.create_fault_request_v2()
        request.stage = PTG_STAGE_S
        request.scope = PTG_FAULT_SCOPE_DIRECT
        request.address_kind = PTG_FAULT_ADDRESS_STAGE_NATIVE
        request.selection_mode = PTG_FAULT_SELECTION_EXACT_ONE
        request.fault_cause = 1
        request.access_type = PTG_FAULT_ACCESS_READ
        request.privilege = PTG_FAULT_PRIV_S
        request.verification_mode = PTG_FAULT_VERIFY_REQUIRE_FAULT
        request.target_level = 0
        request.has_target_address = 1
        request.target_address = 0x4000
        request.dry_run = dry_run
        return request

    def assert_rejected_without_mutation(self, request, expected_status):
        for dry_run in (0, 1):
            with self.subTest(dry_run=dry_run):
                request.dry_run = dry_run
                before = self.snapshot()
                status, results = self.ptg.inject_fault_v2(self.context, request)
                self.assertEqual(status, expected_status)
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].status, expected_status)
                self.assertEqual(self.snapshot(), before)

    def test_abi_layout_and_initializers(self):
        self.assertEqual(
            [name for name, _ in PtgFaultRequestV2._fields_],
            [
                "struct_size",
                "abi_version",
                "stage",
                "scope",
                "address_kind",
                "selection_mode",
                "fault_cause",
                "access_type",
                "privilege",
                "verification_mode",
                "target_level",
                "vs_walk_level",
                "has_target_address",
                "target_count",
                "flags",
                "reserved0",
                "target_address",
                "allowed_cause_mask",
                "allowed_level_mask",
                "seed",
                "probability",
                "dry_run",
                "reserved1",
            ],
        )
        self.assertEqual(
            [name for name, _ in PtgFaultResultV2._fields_],
            [
                "struct_size",
                "abi_version",
                "valid_fields",
                "status",
                "stage",
                "scope",
                "requested_cause",
                "actual_cause",
                "diagnostic_fault_type",
                "requested_level",
                "resolved_level",
                "expected_mcause",
                "actual_mcause",
                "reserved0",
                "requested_address",
                "resolved_address",
                "failing_gpa",
                "pte_pa",
                "old_pte",
                "new_pte",
            ],
        )
        self.assertEqual(ctypes.sizeof(PtgFaultRequestV2), 112)
        self.assertEqual(ctypes.sizeof(PtgFaultResultV2), 104)
        self.assertEqual(ctypes.sizeof(PtgVmConfigV2), 48)
        self.assertEqual(PtgFaultRequestV2.target_address.offset, 64)
        self.assertEqual(PtgFaultRequestV2.probability.offset, 96)
        self.assertEqual(PtgFaultRequestV2.dry_run.offset, 104)
        self.assertEqual(PtgFaultResultV2.requested_address.offset, 56)
        self.assertEqual(PtgFaultResultV2.new_pte.offset, 96)
        self.assertEqual(PtgVmConfigV2.svnapot.offset, 32)

        request = self.ptg.create_fault_request_v2()
        self.assertEqual(request.struct_size, 112)
        self.assertEqual(request.abi_version, 2)
        self.assertEqual(request.target_level, -1)
        self.assertEqual(request.vs_walk_level, -1)

        config = self.ptg.create_vm_config_v2()
        self.assertEqual(config.struct_size, 48)
        self.assertEqual(config.abi_version, 2)
        self.assertEqual(config.pbmte, 1)
        self.assertEqual(config.adue, 1)
        self.assertEqual(self.ptg.set_vm_config_v2(self.context, config), PTG_FAULT_OK)
        with self.assertRaises(ValueError):
            self.ptg.create_vm_config_v2(target="S")
        with self.assertRaises(ValueError):
            self.ptg.create_vm_config_v2(target="VS")

    def test_disabled_and_invalid_request_results(self):
        disabled = self.ptg.create_fault_request_v2()
        status, results = self.ptg.inject_fault_v2(self.context, disabled)
        self.assertEqual(status, PTG_FAULT_OK)
        self.assertEqual(results, ())

        invalid = self.exact_request()
        invalid.target_level = -1
        before = self.snapshot()
        status, results = self.ptg.inject_fault_v2(self.context, invalid)
        self.assertEqual(status, PTG_FAULT_INVALID_ARGUMENT)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, PTG_FAULT_INVALID_ARGUMENT)
        self.assertEqual(self.snapshot(), before)

    def test_two_call_dry_run_and_commit(self):
        request = self.exact_request(dry_run=1)
        before = self.snapshot()
        count = ctypes.c_uint32(0)
        result_size = ctypes.sizeof(PtgFaultResultV2)
        status = self.ptg._lib.ptg_inject_fault_v2(
            self.ptg._handle,
            self.context,
            ctypes.byref(request),
            None,
            0,
            result_size,
            ctypes.byref(count),
        )
        self.assertEqual(status, PTG_FAULT_BUFFER_TOO_SMALL)
        self.assertEqual(count.value, 1)
        self.assertEqual(self.snapshot(), before)

        status, dry_results = self.ptg.inject_fault_v2(self.context, request)
        self.assertEqual(status, PTG_FAULT_OK)
        self.assertEqual(len(dry_results), 1)
        dry_result = dry_results[0]
        required_fields = (
            PTG_FAULT_VALID_PTE_PA
            | PTG_FAULT_VALID_OLD_PTE
            | PTG_FAULT_VALID_NEW_PTE
            | PTG_FAULT_VALID_EXPECTED_MCAUSE
            | PTG_FAULT_VALID_ACTUAL_MCAUSE
        )
        self.assertEqual(dry_result.valid_fields & required_fields, required_fields)
        self.assertNotEqual(dry_result.old_pte, dry_result.new_pte)
        self.assertEqual(dry_result.expected_mcause, 13)
        self.assertEqual(dry_result.actual_mcause, 13)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.ptg.translate(self.context, 0x4000)[1], 0)

        request.dry_run = 0
        status, commit_results = self.ptg.inject_fault_v2(self.context, request)
        self.assertEqual(status, PTG_FAULT_OK)
        self.assertEqual(len(commit_results), 1)
        self.assertEqual(bytes(commit_results[0]), bytes(dry_result))
        self.assertNotEqual(self.snapshot(), before)
        self.assertNotEqual(self.ptg.translate(self.context, 0x4000)[1], 0)

    def test_unsupported_combination_preserves_page_tables(self):
        request = self.exact_request()
        # MPT denial is intentionally outside the PTE V2 mutation matrix.
        request.fault_cause = 13
        self.assert_rejected_without_mutation(
            request, PTG_FAULT_UNSUPPORTED_COMBINATION
        )

    def test_exact_target_miss_preserves_page_tables(self):
        request = self.exact_request()
        request.target_address = 0x8000
        self.assert_rejected_without_mutation(request, PTG_FAULT_TARGET_NOT_FOUND)

    def test_exact_unsuitable_target_preserves_page_tables(self):
        request = self.exact_request()
        request.fault_cause = 4
        request.target_level = 1
        self.assert_rejected_without_mutation(request, PTG_FAULT_UNSUITABLE_TARGET)

    def test_exact_count_insufficient_candidates_is_atomic(self):
        request = self.ptg.create_fault_request_v2()
        request.selection_mode = PTG_FAULT_SELECTION_EXACT_COUNT
        request.allowed_cause_mask = 1 << 1
        request.allowed_level_mask = 1 << 0
        request.target_count = 2
        request.flags = PTG_FAULT_ONE_PER_WALK
        self.assert_rejected_without_mutation(
            request, PTG_FAULT_INSUFFICIENT_CANDIDATES
        )

    def test_batch_require_fault_guard(self):
        request = self.ptg.create_fault_request_v2()
        request.selection_mode = PTG_FAULT_SELECTION_EXACT_COUNT
        request.allowed_cause_mask = 1 << 1
        request.allowed_level_mask = 1 << 0
        request.target_count = 1
        request.dry_run = 1

        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.ptg.inject_fault_v2(self.context, request)
        self.assertEqual(self.snapshot(), before)

        request.flags = PTG_FAULT_ONE_PER_WALK
        status, results = self.ptg.inject_fault_v2(self.context, request)
        self.assertEqual(status, PTG_FAULT_OK)
        self.assertEqual(len(results), 1)
        self.assertEqual(self.ptg.translate(self.context, 0x4000)[1], 0)


if __name__ == "__main__":
    unittest.main()
