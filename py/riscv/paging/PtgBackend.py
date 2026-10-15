"""PtgBackend: Python ctypes wrapper for PTG (page_table_generator) libptg.so.

This module supplies the PTG page-table backend for FORCE-RISCV Hypervisor
integration. FORCE owns the adapter and memory/CSR synchronization, not a
second Hypervisor page-table generator.

BDD Usage:
    Given an initialized GenThread
    When  PtgBackend is configured with paging mode and mappings
    Then  page tables are generated and loaded to simulator physical memory
"""

import ctypes
import os
from collections import namedtuple

PTG_OK = 0
PTG_ERR_MAP = {
    0: "OK",
    -1: "INVALID_HANDLE",
    -2: "CTX_NOT_FOUND",
    -3: "TREE_NOT_FOUND",
    -4: "INVALID_PARAM",
    -5: "ALLOC_FAILED",
    -6: "IO_FAILED",
    -7: "NOT_INITIALIZED",
    -8: "ALREADY_EXISTS",
    -9: "NO_SPACE",
    -10: "INVALID_STAGE",
    -11: "UNSUPPORTED",
    -12: "TARGET_NOT_FOUND",
    -13: "FAULT_NOT_APPLIED",
    -14: "SEMANTIC_MISMATCH",
    106: "GS_CONFLICT",
    -99: "INTERNAL",
}

SV_MODE_MAP = {
    "Bare": 0,
    "Sv32": 1,
    "Sv39": 8,
    "Sv48": 9,
    "Sv57": 10,
    "Sv39x4": 8,
    "Sv48x4": 9,
    "Sv57x4": 10,
}

SATP_MODE_MAP = {
    "Bare": 0,
    "Sv32": 1,
    "Sv39": 8,
    "Sv48": 9,
    "Sv57": 10,
    "Sv39x4": 8,
    "Sv48x4": 9,
    "Sv57x4": 10,
}

STAGE_MAP = {"S": 0, "VS": 1, "G": 2}

PTG_FAULT_SELECTION_DISABLED = 0
PTG_FAULT_SELECTION_EXACT_ONE = 1
PTG_FAULT_SELECTION_EXACT_COUNT = 2
PTG_FAULT_SELECTION_PROBABILITY = 3

PTG_FAULT_SCOPE_DIRECT = 0
PTG_FAULT_SCOPE_GUEST_IMPLICIT = 1
PTG_FAULT_SCOPE_GUEST_EXPLICIT = 2

PTG_FAULT_ADDRESS_STAGE_NATIVE = 0
PTG_FAULT_ADDRESS_GVA = 1
PTG_FAULT_ADDRESS_GPA = 2

PTG_STAGE_S = 0
PTG_STAGE_VS = 1
PTG_STAGE_G = 2

PTG_FAULT_ACCESS_READ = 0
PTG_FAULT_ACCESS_WRITE = 1
PTG_FAULT_ACCESS_EXECUTE = 2

PTG_FAULT_PRIV_S = 0
PTG_FAULT_PRIV_U = 1
PTG_FAULT_PRIV_VS = 2
PTG_FAULT_PRIV_VU = 3

PTG_FAULT_VERIFY_MUTATION_ONLY = 0
PTG_FAULT_VERIFY_REQUIRE_FAULT = 1

PTG_FAULT_OK = 0
PTG_FAULT_INVALID_ARGUMENT = 1
PTG_FAULT_ABI_MISMATCH = 2
PTG_FAULT_UNSUPPORTED_COMBINATION = 3
PTG_FAULT_TARGET_NOT_FOUND = 4
PTG_FAULT_UNSUITABLE_TARGET = 5
PTG_FAULT_NO_MUTATION = 6
PTG_FAULT_PROBABILITY_MISS = 7
PTG_FAULT_INSUFFICIENT_CANDIDATES = 8
PTG_FAULT_BUFFER_TOO_SMALL = 9
PTG_FAULT_SEMANTIC_MISMATCH = 10
PTG_FAULT_INTERNAL_ERROR = 11

PTG_FAULT_STATUS_MAP = {
    PTG_FAULT_OK: "OK",
    PTG_FAULT_INVALID_ARGUMENT: "INVALID_ARGUMENT",
    PTG_FAULT_ABI_MISMATCH: "ABI_MISMATCH",
    PTG_FAULT_UNSUPPORTED_COMBINATION: "UNSUPPORTED_COMBINATION",
    PTG_FAULT_TARGET_NOT_FOUND: "TARGET_NOT_FOUND",
    PTG_FAULT_UNSUITABLE_TARGET: "UNSUITABLE_TARGET",
    PTG_FAULT_NO_MUTATION: "NO_MUTATION",
    PTG_FAULT_PROBABILITY_MISS: "PROBABILITY_MISS",
    PTG_FAULT_INSUFFICIENT_CANDIDATES: "INSUFFICIENT_CANDIDATES",
    PTG_FAULT_BUFFER_TOO_SMALL: "BUFFER_TOO_SMALL",
    PTG_FAULT_SEMANTIC_MISMATCH: "SEMANTIC_MISMATCH",
    PTG_FAULT_INTERNAL_ERROR: "INTERNAL_ERROR",
}

PTG_FAULT_ONE_PER_WALK = 1 << 0
PTG_FAULT_ALLOWED_FLAGS = PTG_FAULT_ONE_PER_WALK

PTG_VM_CONFIG_S_VS = 0
PTG_VM_CONFIG_G = 1
VM_CONFIG_TARGET_MAP = {"S_VS": PTG_VM_CONFIG_S_VS, "G": PTG_VM_CONFIG_G}

PTG_FAULT_VALID_REQUESTED_ADDRESS = 1 << 0
PTG_FAULT_VALID_RESOLVED_ADDRESS = 1 << 1
PTG_FAULT_VALID_FAILING_GPA = 1 << 2
PTG_FAULT_VALID_PTE_PA = 1 << 3
PTG_FAULT_VALID_OLD_PTE = 1 << 4
PTG_FAULT_VALID_NEW_PTE = 1 << 5
PTG_FAULT_VALID_EXPECTED_MCAUSE = 1 << 6
PTG_FAULT_VALID_ACTUAL_MCAUSE = 1 << 7


class PtgMapping(ctypes.Structure):
    _fields_ = [
        ("va", ctypes.c_uint64),
        ("pa", ctypes.c_uint64),
        ("size", ctypes.c_uint64),
        ("leaf_level", ctypes.c_uint8),
        ("perm", ctypes.c_uint8),
    ]


class PtgRandomConfig(ctypes.Structure):
    _fields_ = [
        ("va_start", ctypes.c_uint64),
        ("va_end", ctypes.c_uint64),
        ("pa_start", ctypes.c_uint64),
        ("pa_end", ctypes.c_uint64),
        ("min_mappings", ctypes.c_uint32),
        ("max_mappings", ctypes.c_uint32),
        ("seed", ctypes.c_uint64),
        ("sv_mode", ctypes.c_int),
        ("access_types", ctypes.c_uint8),
        ("default_perm", ctypes.c_uint8),
        ("flags_a", ctypes.c_uint8),
        ("flags_d", ctypes.c_uint8),
        ("flags_g", ctypes.c_uint8),
        ("flags_u", ctypes.c_uint8),
        ("size_4kb_weight", ctypes.c_double),
        ("size_2mb_weight", ctypes.c_double),
        ("size_1gb_weight", ctypes.c_double),
        ("size_512gb_weight", ctypes.c_double),
        ("fault_cause", ctypes.c_int),
        ("fault_type", ctypes.c_int),
        ("fault_level", ctypes.c_int),
        ("fault_probability", ctypes.c_double),
        ("fault_random_cause", ctypes.c_int),
        ("fault_seed", ctypes.c_uint64),
        ("force_new", ctypes.c_int),
        ("merge_probability", ctypes.c_double),
        ("pbmte", ctypes.c_int),
        ("adue", ctypes.c_int),
        ("sum", ctypes.c_int),
        ("mxr", ctypes.c_int),
        ("sse", ctypes.c_int),
        ("ss_probability", ctypes.c_double),
        ("gs_inherit", ctypes.c_int),
        ("gs_conflict_mode", ctypes.c_int),
    ]


class PtgFaultConfig(ctypes.Structure):
    _fields_ = [
        ("fault_cause", ctypes.c_int),
        ("fault_type", ctypes.c_int),
        ("fault_level", ctypes.c_int),
        ("fault_probability", ctypes.c_double),
        ("random_cause", ctypes.c_int),
        ("seed", ctypes.c_uint64),
        ("target_count", ctypes.c_uint32),
        ("per_leaf_only", ctypes.c_int),
        ("target_va", ctypes.c_uint64),
        ("dry_run", ctypes.c_int),
    ]


class PtgFaultStats(ctypes.Structure):
    _fields_ = [
        ("scanned", ctypes.c_uint32),
        ("rolled", ctypes.c_uint32),
        ("skipped", ctypes.c_uint32),
        ("injected", ctypes.c_uint32),
    ]


class PtgFaultRequestV2(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("abi_version", ctypes.c_uint32),
        ("stage", ctypes.c_int32),
        ("scope", ctypes.c_int32),
        ("address_kind", ctypes.c_int32),
        ("selection_mode", ctypes.c_int32),
        ("fault_cause", ctypes.c_int32),
        ("access_type", ctypes.c_int32),
        ("privilege", ctypes.c_int32),
        ("verification_mode", ctypes.c_int32),
        ("target_level", ctypes.c_int32),
        ("vs_walk_level", ctypes.c_int32),
        ("has_target_address", ctypes.c_uint32),
        ("target_count", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("reserved0", ctypes.c_uint32),
        ("target_address", ctypes.c_uint64),
        ("allowed_cause_mask", ctypes.c_uint64),
        ("allowed_level_mask", ctypes.c_uint64),
        ("seed", ctypes.c_uint64),
        ("probability", ctypes.c_double),
        ("dry_run", ctypes.c_int32),
        ("reserved1", ctypes.c_uint32),
    ]


class PtgFaultResultV2(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("abi_version", ctypes.c_uint32),
        ("valid_fields", ctypes.c_uint32),
        ("status", ctypes.c_int32),
        ("stage", ctypes.c_int32),
        ("scope", ctypes.c_int32),
        ("requested_cause", ctypes.c_int32),
        ("actual_cause", ctypes.c_int32),
        ("diagnostic_fault_type", ctypes.c_int32),
        ("requested_level", ctypes.c_int32),
        ("resolved_level", ctypes.c_int32),
        ("expected_mcause", ctypes.c_uint32),
        ("actual_mcause", ctypes.c_uint32),
        ("reserved0", ctypes.c_uint32),
        ("requested_address", ctypes.c_uint64),
        ("resolved_address", ctypes.c_uint64),
        ("failing_gpa", ctypes.c_uint64),
        ("pte_pa", ctypes.c_uint64),
        ("old_pte", ctypes.c_uint64),
        ("new_pte", ctypes.c_uint64),
    ]


class PtgVmConfigV2(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("abi_version", ctypes.c_uint32),
        ("target", ctypes.c_int32),
        ("pbmte", ctypes.c_uint32),
        ("adue", ctypes.c_uint32),
        ("sum", ctypes.c_uint32),
        ("mxr", ctypes.c_uint32),
        ("sse", ctypes.c_uint32),
        ("svnapot", ctypes.c_uint32),
        ("reserved0", ctypes.c_uint32),
        ("reserved1", ctypes.c_uint32),
        ("reserved2", ctypes.c_uint32),
    ]


class PtgGuestFaultDebug(ctypes.Structure):
    _fields_ = [
        ("vs_node_count", ctypes.c_uint32),
        ("gs_hit_count", ctypes.c_uint32),
        ("probability_passed", ctypes.c_uint32),
        ("invalidated", ctypes.c_uint32),
    ]


class PtgValidateResult(ctypes.Structure):
    _fields_ = [
        ("total_nodes", ctypes.c_uint32),
        ("total_ptes", ctypes.c_uint32),
        ("valid_ptes", ctypes.c_uint32),
        ("leaf_ptes", ctypes.c_uint32),
        ("nonleaf_ptes", ctypes.c_uint32),
        ("invalid_addr_nodes", ctypes.c_uint32),
        ("invalid_pte_count", ctypes.c_uint32),
        ("orphan_nodes", ctypes.c_uint32),
        ("gpa_overlap_count", ctypes.c_uint32),
        ("gpa_unreachable", ctypes.c_uint32),
        ("leaf_missing_flags", ctypes.c_uint32),
        ("all_ok", ctypes.c_uint8),
    ]


class PtgBlock(ctypes.Structure):
    _fields_ = [
        ("pa", ctypes.c_uint64),
        ("size", ctypes.c_size_t),
        ("data", ctypes.POINTER(ctypes.c_uint8)),
    ]


class PtgBinaryBlocks(ctypes.Structure):
    _fields_ = [
        ("num_blocks", ctypes.c_size_t),
        ("blocks", ctypes.POINTER(PtgBlock)),
    ]


WRITE_FN_TYPE = ctypes.CFUNCTYPE(
    None,
    ctypes.c_uint64,
    ctypes.POINTER(ctypes.c_uint8),
    ctypes.c_size_t,
    ctypes.c_void_p,
)


# Versioned mapping/export statuses are independent of legacy PtgStatus.
PTG_MAPPING_OK = 0
PTG_MAPPING_INVALID_ARGUMENT = 1
PTG_MAPPING_ABI_MISMATCH = 2
PTG_MAPPING_CONTEXT_NOT_FOUND = 3
PTG_MAPPING_TREE_NOT_FOUND = 4
PTG_MAPPING_BUFFER_TOO_SMALL = 5
PTG_MAPPING_STALE_LAYOUT = 6
PTG_MAPPING_BACKING_UNAVAILABLE = 7
PTG_MAPPING_INTERNAL_ERROR = 8
PTG_MAPPING_STATUS_MAP = dict(enumerate((
    "OK", "INVALID_ARGUMENT", "ABI_MISMATCH", "CONTEXT_NOT_FOUND", "TREE_NOT_FOUND",
    "BUFFER_TOO_SMALL", "STALE_LAYOUT", "BACKING_UNAVAILABLE", "INTERNAL_ERROR",
)))
PTG_MAPPING_FORWARD, PTG_MAPPING_REVERSE, PTG_MAPPING_ENUMERATE = range(3)
PTG_MAPPING_CURRENT, PTG_MAPPING_LOGICAL = range(2)
PTG_MAPPING_KIND_VA, PTG_MAPPING_KIND_GVA, PTG_MAPPING_KIND_GPA, PTG_MAPPING_KIND_SPA = range(4)
PTG_MAPPING_VALID_LOGICAL = 1
PTG_MAPPING_VALID_CURRENT = 2
PTG_MAPPING_VALID_PTE = 4
PTG_MAPPING_VALID_MATCH = 8
PTG_MAPPING_VALID_OBSERVED_VA = 16
PTG_MAPPING_PTE_VALID_LEAF, PTG_MAPPING_PTE_INVALID = 0, 1
PTG_MAPPING_PTE_MALFORMED, PTG_MAPPING_PTE_PATH_MISSING = 2, 3


class PtgMappingError(RuntimeError):
    """A versioned query/export status, separate from legacy PtgStatus/last_error."""

    def __init__(self, operation, status):
        self.operation = operation
        self.status = status
        super().__init__("{} failed: {} ({})".format(
            operation, PTG_MAPPING_STATUS_MAP.get(status, "UNKNOWN"), status
        ))


def _mapping_status(operation, status):
    if status != PTG_MAPPING_OK:
        raise PtgMappingError(operation, status)


def _mapping_uint(value, bits, name):
    if type(value) is not int or not 0 <= value < (1 << bits):
        raise ValueError("{} must be an unsigned {}-bit integer".format(name, bits))
    return value


def _mapping_stage(stage):
    code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
    if type(code) is not int or code not in (0, 1, 2):
        raise ValueError("mapping stage must be S, VS or G (0, 1 or 2)")
    return code


class PtgMappingQueryV1(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32), ("abi_version", ctypes.c_uint32),
        ("stage", ctypes.c_int32), ("direction", ctypes.c_int32), ("domain", ctypes.c_int32),
        ("flags", ctypes.c_uint32), ("address", ctypes.c_uint64),
        ("reserved0", ctypes.c_uint32), ("reserved1", ctypes.c_uint32),
    ]


class PtgMappingRangeV1(ctypes.Structure):
    _fields_ = [
        ("va_base", ctypes.c_uint64), ("pa_base", ctypes.c_uint64),
        ("page_size", ctypes.c_uint64), ("leaf_level", ctypes.c_int32),
        ("reserved0", ctypes.c_uint32),
    ]


class PtgMappingRecordV1(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32), ("abi_version", ctypes.c_uint32),
        ("valid_fields", ctypes.c_uint32), ("stage", ctypes.c_int32),
        ("input_kind", ctypes.c_int32), ("output_kind", ctypes.c_int32),
        ("pte_state", ctypes.c_int32), ("observed_level", ctypes.c_int32),
        ("tree_id", ctypes.c_uint64), ("observed_va", ctypes.c_uint64),
        ("logical", PtgMappingRangeV1), ("current", PtgMappingRangeV1),
        ("matched_va", ctypes.c_uint64), ("matched_pa", ctypes.c_uint64),
        ("pte_address", ctypes.c_uint64), ("pte_value", ctypes.c_uint64),
        ("raw_perm", ctypes.c_uint32), ("pbmt", ctypes.c_uint32),
        ("napot", ctypes.c_uint32), ("reserved0", ctypes.c_uint32),
    ]


class PtgExportLayoutRequestV1(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32), ("abi_version", ctypes.c_uint32),
        ("stage", ctypes.c_int32), ("flags", ctypes.c_uint32),
        ("reserved0", ctypes.c_uint32), ("reserved1", ctypes.c_uint32),
    ]


class PtgExportBlockV1(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32), ("abi_version", ctypes.c_uint32),
        ("stage", ctypes.c_int32), ("source_kind", ctypes.c_int32),
        ("source_address", ctypes.c_uint64), ("spa", ctypes.c_uint64),
        ("size", ctypes.c_uint64), ("data_offset", ctypes.c_uint64),
    ]


class PtgExportLayout:
    """Owned capture returned by capture_export_layout; placement is frozen, bytes are not.

    Use a context manager or close explicitly. Destroying the parent invalidates all
    captures. A stale read raises PtgMappingError; it never silently captures again.
    Calls and mutations on the parent handle must be serialized by the caller.
    """

    def __init__(self, owner, ctx_id, stage, layout_id):
        self._owner = owner
        self._ctx_id = ctx_id
        self._stage = stage
        self._layout_id = layout_id

    @property
    def closed(self):
        return not self._layout_id or not self._owner._handle

    def __enter__(self):
        if self.closed:
            raise RuntimeError("PTG export layout is closed or its handle is destroyed")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass  # Explicit close reports failures; finalization must not raise.

    def close(self):
        if not getattr(self, "_layout_id", 0):
            return
        if self._owner._handle:
            _mapping_status("free export layout", self._owner._lib.ptg_export_layout_free_v1(
                self._owner._handle, self._layout_id
            ))
        self._layout_id = 0

    def read(self):
        """Return caller-owned records and immutable bytes after a complete validated pull."""
        self.__enter__()
        count, size = ctypes.c_uint32(), ctypes.c_uint64()
        read = self._owner._lib.ptg_export_layout_read_v1
        stride = ctypes.sizeof(PtgExportBlockV1)
        _mapping_status("preflight export layout", read(
            self._owner._handle, self._layout_id, None, 0, stride, None, 0,
            ctypes.byref(count), ctypes.byref(size)
        ))
        expected = count.value, size.value
        if not count.value:
            if size.value:
                raise RuntimeError("PTG export returned bytes without blocks")
            return (), b""
        if not size.value:
            raise RuntimeError("PTG export returned blocks without bytes")
        blocks = (PtgExportBlockV1 * count.value)()
        data = (ctypes.c_uint8 * size.value)()
        _mapping_status("read export layout", read(
            self._owner._handle, self._layout_id, blocks, count.value, stride,
            data, size.value, ctypes.byref(count), ctypes.byref(size)
        ))
        if (count.value, size.value) != expected:
            raise RuntimeError("PTG export changed size during serialized pull")
        offset = 0
        source_kind = PTG_MAPPING_KIND_GPA if self._stage == 1 else PTG_MAPPING_KIND_SPA
        for block in blocks:
            if (block.struct_size != stride or block.abi_version != 1
                    or block.stage != self._stage or block.source_kind != source_kind
                    or block.data_offset != offset or block.size == 0
                    or block.size > size.value - offset
                    or block.spa + block.size > (1 << 64)
                    or block.source_address + block.size > (1 << 64)
                    or (self._stage != 1 and block.source_address != block.spa)):
                raise RuntimeError("PTG export returned invalid block metadata")
            offset += block.size
        if offset != size.value:
            raise RuntimeError("PTG export returned unaccounted bytes")
        return tuple(blocks), bytes(data)


PtgTablePool = namedtuple("PtgTablePool", "name base limit bank")


class PtgAllocationError(RuntimeError):
    """Checked allocation/placement PtgStatus, not a MappingStatus or FaultStatus."""

    def __init__(self, operation, status):
        self.operation = operation
        self.status = status
        super().__init__("{} failed: {} ({})".format(
            operation, PTG_ERR_MAP.get(status, "UNKNOWN"), status
        ))


def _allocation_status(operation, status):
    if status != PTG_OK:
        raise PtgAllocationError(operation, status)


class PtgPlacementConfigV1(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32), ("abi_version", ctypes.c_uint32),
        ("pt_base", ctypes.c_uint64), ("pt_limit", ctypes.c_uint64),
        ("pt_align", ctypes.c_uint64), ("flags", ctypes.c_uint32),
        ("reserved0", ctypes.c_uint32),
    ]


class PtgLevelPlacementV1(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32), ("abi_version", ctypes.c_uint32),
        ("level", ctypes.c_int32), ("reserved0", ctypes.c_uint32),
        ("base", ctypes.c_uint64), ("limit", ctypes.c_uint64),
    ]


class PtgPlacement(namedtuple("PtgPlacementFields", "base limit alignment levels")):
    """Immutable policy using absolute PA/GPA half-open windows.

    (base, limit) == (0, 0) selects all owned regions; alignment=0 means natural.
    levels is an ordered iterable of (level, base, limit) triples. PTG validates
    ownership and performs level-first/GENERAL fallback; FORCE never allocates PTEs.
    """

    __slots__ = ()

    def __new__(cls, base=0, limit=0, alignment=0, levels=()):
        for value, label in ((base, "placement base"), (limit, "placement limit"),
                             (alignment, "placement alignment")):
            _mapping_uint(value, 64, label)
        if (base, limit) != (0, 0) and base >= limit:
            raise ValueError("placement GENERAL interval must be half-open and nonempty")
        if alignment and alignment & (alignment - 1):
            raise ValueError("placement alignment must be zero or a power of two")
        windows = tuple(tuple(window) for window in levels)
        _mapping_uint(len(windows), 32, "placement window count")
        for window in windows:
            if len(window) != 3:
                raise ValueError("placement level window requires (level, base, limit)")
            level, low, high = window
            if type(level) is not int or not 0 <= level <= 4:
                raise ValueError("placement level must be in [0, 4]")
            _mapping_uint(low, 64, "level base")
            _mapping_uint(high, 64, "level limit")
            if low >= high:
                raise ValueError("placement level interval must be half-open and nonempty")
        spans = sorted((low, high) for _, low, high in windows)
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            raise ValueError("placement level windows overlap")
        return super().__new__(cls, base, limit, alignment, windows)


class PtgHandle:
    def __init__(self, lib_path=None):
        self._handle = None
        self._mapping_v1_ready = False
        self._placement_v1_ready = False
        self._placement_configured = False
        self._force_pool = None
        self._pool_writer = None
        self._pool_context = None
        self._pool_vmid = None
        self._pool_gpa_regions = []
        self._pool_stages = set()
        self._pool_failed = False
        if lib_path is None:
            lib_path = os.environ.get("PTG_LIB_PATH")
        if lib_path is None:
            force_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..")
            )
            candidates = (
                os.path.join(
                    force_root,
                    "3rd_party",
                    "page_table_generator",
                    "build",
                    "libptg.so",
                ),
                os.path.join(
                    os.path.dirname(force_root),
                    "page_table_generator",
                    "build",
                    "libptg.so",
                ),
            )
            lib_path = next((path for path in candidates if os.path.isfile(path)), None)
            if lib_path is None:
                raise FileNotFoundError(
                    "Unable to locate libptg.so; set PTG_LIB_PATH or build PTG at "
                    + " or ".join(candidates)
                )
        self._lib = ctypes.CDLL(lib_path)
        self._setup_signatures()
        self._handle = self._lib.ptg_create()
        if not self._handle:
            raise RuntimeError("ptg_create returned NULL")

    def _setup_signatures(self):
        """集中声明所有函数 argtypes 和 restype.

        ABI 对齐：Python 3.11+ 未声明 argtypes 会导致
        64-bit void* 参数被截断为 c_int，导致 segfault。
        """
        lib = self._lib

        lib.ptg_create.restype = ctypes.c_void_p
        lib.ptg_create.argtypes = []

        lib.ptg_destroy.restype = None
        lib.ptg_destroy.argtypes = [ctypes.c_void_p]

        lib.ptg_register_pa_region.restype = None
        lib.ptg_register_pa_region.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_uint64,
        ]

        lib.ptg_register_gpa_region.restype = None
        lib.ptg_register_gpa_region.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint16,
            ctypes.c_uint64,
            ctypes.c_uint64,
        ]

        lib.ptg_context_create.restype = ctypes.c_uint32
        lib.ptg_context_create.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint16,
            ctypes.c_uint16,
        ]

        lib.ptg_context_s_stage.restype = None
        lib.ptg_context_s_stage.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
        ]

        lib.ptg_context_vs_stage.restype = None
        lib.ptg_context_vs_stage.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
        ]

        lib.ptg_context_gs_stage.restype = None
        lib.ptg_context_gs_stage.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
        ]

        lib.ptg_context_satp.restype = ctypes.c_uint64
        lib.ptg_context_satp.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

        lib.ptg_context_vsatp.restype = ctypes.c_uint64
        lib.ptg_context_vsatp.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

        lib.ptg_context_hgatp.restype = ctypes.c_uint64
        lib.ptg_context_hgatp.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

        lib.ptg_add_mapping.restype = None
        lib.ptg_add_mapping.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_uint64,
            ctypes.c_uint64,
            ctypes.c_uint8,
            ctypes.c_uint8,
        ]

        lib.ptg_translate.restype = ctypes.c_uint64
        lib.ptg_translate.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint64,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8),
        ]

        lib.ptg_mapping_find_pa.restype = ctypes.c_uint64
        lib.ptg_mapping_find_pa.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint64
        ]
        lib.ptg_mapping_find_vas.restype = ctypes.c_uint32
        lib.ptg_mapping_find_vas.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_uint32,
        ]

        lib.ptg_random_generate.restype = ctypes.c_uint32
        lib.ptg_random_generate.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.POINTER(PtgRandomConfig),
            ctypes.POINTER(PtgMapping),
            ctypes.c_uint32,
        ]

        lib.ptg_inject_fault.restype = ctypes.c_uint32
        lib.ptg_inject_fault.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.POINTER(PtgFaultConfig),
        ]

        lib.ptg_fault_request_v2_init.restype = ctypes.c_int
        lib.ptg_fault_request_v2_init.argtypes = [
            ctypes.POINTER(PtgFaultRequestV2),
            ctypes.c_uint32,
        ]

        lib.ptg_vm_config_v2_init.restype = ctypes.c_int
        lib.ptg_vm_config_v2_init.argtypes = [
            ctypes.POINTER(PtgVmConfigV2),
            ctypes.c_uint32,
        ]

        lib.ptg_context_set_vm_config_v2.restype = ctypes.c_int
        lib.ptg_context_set_vm_config_v2.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(PtgVmConfigV2),
        ]

        lib.ptg_inject_fault_v2.restype = ctypes.c_int
        lib.ptg_inject_fault_v2.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(PtgFaultRequestV2),
            ctypes.POINTER(PtgFaultResultV2),
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]

        lib.ptg_fault_stats.restype = PtgFaultStats
        lib.ptg_fault_stats.argtypes = [ctypes.c_void_p]

        lib.ptg_validate.restype = PtgValidateResult
        lib.ptg_validate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

        lib.ptg_dump_binary.restype = None
        lib.ptg_dump_binary.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_char_p,
        ]

        lib.ptg_dump_json.restype = None
        lib.ptg_dump_json.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_char_p,
        ]

        lib.ptg_dump_binary_blocks.restype = ctypes.POINTER(PtgBinaryBlocks)
        lib.ptg_dump_binary_blocks.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
        ]

        lib.ptg_free_blocks.restype = None
        lib.ptg_free_blocks.argtypes = [ctypes.POINTER(PtgBinaryBlocks)]

        lib.ptg_dump_binary_write.restype = None
        lib.ptg_dump_binary_write.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            WRITE_FN_TYPE,
            ctypes.c_void_p,
        ]

        lib.ptg_last_error.restype = ctypes.c_int
        lib.ptg_last_error.argtypes = [ctypes.c_void_p]

        lib.ptg_error_string.restype = ctypes.c_char_p
        lib.ptg_error_string.argtypes = [ctypes.c_int]

        lib.ptg_sfence_vma.restype = None
        lib.ptg_sfence_vma.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint64,
            ctypes.c_uint16,
        ]

        lib.ptg_hfence_gvma.restype = None
        lib.ptg_hfence_gvma.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint16,
            ctypes.c_uint64,
        ]

        lib.ptg_remap_va.restype = None
        lib.ptg_remap_va.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_uint64,
        ]

        lib.ptg_context_set_vm_config.restype = None
        lib.ptg_context_set_vm_config.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]

        lib.ptg_save_state.restype = ctypes.c_int
        lib.ptg_save_state.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

        lib.ptg_restore_state.restype = ctypes.c_int
        lib.ptg_restore_state.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

        # Guest Fault 注入（两阶翻译关键 API）
        lib.ptg_inject_implicit_guest_fault.restype = ctypes.c_uint32
        lib.ptg_inject_implicit_guest_fault.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(PtgFaultConfig),
        ]

        lib.ptg_inject_explicit_guest_fault.restype = ctypes.c_uint32
        lib.ptg_inject_explicit_guest_fault.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(PtgFaultConfig),
        ]

        # 两阶顺序翻译
        lib.ptg_translate_sequential.restype = ctypes.c_uint64
        lib.ptg_translate_sequential.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint64,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.POINTER(ctypes.c_uint8),
        ]

        # Guest Fault 调试
        lib.ptg_debug_implicit_guest_fault.restype = PtgGuestFaultDebug
        lib.ptg_debug_implicit_guest_fault.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_double,
            ctypes.c_uint64,
        ]

        lib.ptg_debug_explicit_guest_fault.restype = PtgGuestFaultDebug
        lib.ptg_debug_explicit_guest_fault.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_double,
            ctypes.c_uint64,
        ]

        # G-stage VM config
        lib.ptg_context_set_gs_vm_config.restype = None
        lib.ptg_context_set_gs_vm_config.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]

        # Batch fault 注入
        lib.ptg_inject_faults.restype = ctypes.c_uint32
        lib.ptg_inject_faults.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.POINTER(PtgFaultConfig),
            ctypes.c_uint32,
        ]

        # TLB 失效
        lib.ptg_invalidate_by_asid.restype = None
        lib.ptg_invalidate_by_asid.argtypes = [ctypes.c_void_p, ctypes.c_uint16]

        lib.ptg_invalidate_by_vmid.restype = None
        lib.ptg_invalidate_by_vmid.argtypes = [ctypes.c_void_p, ctypes.c_uint16]

    def _require_placement_v1(self):
        if not self._handle:
            raise RuntimeError("PTG handle is destroyed")
        self._check_pool_ready()
        if self._placement_v1_ready:
            return
        if (ctypes.sizeof(PtgPlacementConfigV1), ctypes.sizeof(PtgLevelPlacementV1),
                ctypes.alignment(PtgPlacementConfigV1)) != (40, 32, 8):
            raise RuntimeError("PTG placement v1 requires the LP64 ABI")
        config_ptr = ctypes.POINTER(PtgPlacementConfigV1)
        levels_ptr = ctypes.POINTER(PtgLevelPlacementV1)
        signatures = {
            "ptg_placement_config_v1_init": [config_ptr, ctypes.c_uint32],
            "ptg_level_placement_v1_init": [levels_ptr, ctypes.c_uint32],
            "ptg_configure_pa_placement_v1": [
                ctypes.c_void_p, config_ptr, levels_ptr, ctypes.c_uint32, ctypes.c_uint32,
            ],
            "ptg_configure_gpa_placement_v1": [
                ctypes.c_void_p, ctypes.c_uint16, config_ptr, levels_ptr,
                ctypes.c_uint32, ctypes.c_uint32,
            ],
        }
        try:
            functions = {name: getattr(self._lib, name) for name in signatures}
        except AttributeError as error:
            raise RuntimeError("PTG library lacks checked allocation/placement v1") from error
        for name, function in functions.items():
            function.argtypes = signatures[name]
            function.restype = ctypes.c_int32
        self._placement_v1_ready = True

    def _configure_placement(self, policy, vmid=None):
        self._require_placement_v1()
        if not isinstance(policy, PtgPlacement):
            raise TypeError("policy must be a PtgPlacement")
        # Revalidate even values constructed through namedtuple._replace/_make.
        policy = PtgPlacement(*policy)
        if vmid is not None:
            _mapping_uint(vmid, 16, "placement VMID")
            if self._force_pool is not None and vmid != self._pool_vmid:
                raise ValueError("GPA placement must use the reserved pool's VMID")
        config = PtgPlacementConfigV1()
        _allocation_status("initialize placement config", self._lib.ptg_placement_config_v1_init(
            ctypes.byref(config), ctypes.sizeof(config)
        ))
        config.pt_base, config.pt_limit, config.pt_align = policy[:3]
        levels = (PtgLevelPlacementV1 * len(policy.levels))()
        for entry, (level, low, high) in zip(levels, policy.levels):
            _allocation_status("initialize placement level", self._lib.ptg_level_placement_v1_init(
                ctypes.byref(entry), ctypes.sizeof(entry)
            ))
            entry.level, entry.base, entry.limit = level, low, high
        args = (ctypes.byref(config), levels if len(levels) else None,
                len(levels), ctypes.sizeof(PtgLevelPlacementV1))
        if vmid is None:
            status = self._lib.ptg_configure_pa_placement_v1(self._handle, *args)
        else:
            status = self._lib.ptg_configure_gpa_placement_v1(self._handle, vmid, *args)
        # A rejected policy is atomic: do not poison an otherwise usable owned pool.
        _allocation_status("configure {} placement".format("PA" if vmid is None else "GPA"), status)
        self._placement_configured = True

    def configure_pa_placement(self, policy):
        """Set policy inside registered PA ownership; no allocation, relocation or fence."""
        self._configure_placement(policy)

    def configure_gpa_placement(self, vmid, policy):
        """Set a VMID-local GPA policy. Calls and other handle operations must be serialized."""
        self._configure_placement(policy, vmid)

    def _require_mapping_v1(self):
        if not self._handle:
            raise RuntimeError("PTG handle is destroyed")
        self._check_pool_ready()
        if self._mapping_v1_ready:
            return
        signatures = {
            "ptg_mapping_query_v1_init": [ctypes.POINTER(PtgMappingQueryV1), ctypes.c_uint32],
            "ptg_mapping_query_v1": [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(PtgMappingQueryV1),
                ctypes.POINTER(PtgMappingRecordV1), ctypes.c_uint32, ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32),
            ],
            "ptg_export_layout_v1_init": [
                ctypes.POINTER(PtgExportLayoutRequestV1), ctypes.c_uint32,
            ],
            "ptg_export_layout_create_v1": [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(PtgExportLayoutRequestV1),
                ctypes.POINTER(ctypes.c_uint64),
            ],
            "ptg_export_layout_read_v1": [
                ctypes.c_void_p, ctypes.c_uint64, ctypes.POINTER(PtgExportBlockV1),
                ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8),
                ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint64),
            ],
            "ptg_export_layout_free_v1": [ctypes.c_void_p, ctypes.c_uint64],
        }
        try:
            functions = {name: getattr(self._lib, name) for name in signatures}
        except AttributeError as error:
            raise RuntimeError("PTG library lacks Mapping Query/Strict Export v1") from error
        for name, function in functions.items():
            function.argtypes = signatures[name]
            function.restype = ctypes.c_int32
        self._mapping_v1_ready = True

    def query_mappings(self, ctx_id, stage, address=0, direction="forward", domain="current"):
        """Read structural metadata, NOT access authorization; VS output/PTE addresses are GPA.

        An empty list means no record. PA=0 is valid. Inspect valid_fields before
        using current/logical ranges or matched addresses. No legacy query fallback.
        """
        self._require_mapping_v1()
        ctx_id = _mapping_uint(ctx_id, 32, "context")
        stage = _mapping_stage(stage)
        direction = {"forward": 0, "reverse": 1, "enumerate": 2}.get(direction, direction)
        domain = {"current": 0, "logical": 1}.get(domain, domain)
        if type(direction) is not int or direction not in (0, 1, 2):
            raise ValueError("invalid mapping query direction")
        if type(domain) is not int or domain not in (0, 1):
            raise ValueError("invalid mapping query domain")
        address = _mapping_uint(address, 64, "address")
        if direction == PTG_MAPPING_ENUMERATE and address != 0:
            raise ValueError("enumerate requires address=0")
        query = PtgMappingQueryV1()
        _mapping_status("initialize mapping query", self._lib.ptg_mapping_query_v1_init(
            ctypes.byref(query), ctypes.sizeof(query)
        ))
        query.stage, query.direction = stage, direction
        query.domain, query.address = domain, address
        required = ctypes.c_uint32()
        stride = ctypes.sizeof(PtgMappingRecordV1)
        _mapping_status("preflight mapping query", self._lib.ptg_mapping_query_v1(
            self._handle, ctx_id, ctypes.byref(query), None, 0, stride, ctypes.byref(required)
        ))
        count = required.value
        if not count:
            return []
        records = (PtgMappingRecordV1 * count)()
        _mapping_status("read mapping query", self._lib.ptg_mapping_query_v1(
            self._handle, ctx_id, ctypes.byref(query), records, count, stride,
            ctypes.byref(required)
        ))
        if required.value != count:
            raise RuntimeError("PTG mapping query changed count during serialized read")
        input_kind, output_kind = ((0, 3), (1, 2), (2, 3))[stage]
        for record in records:
            if (record.struct_size != stride or record.abi_version != 1
                    or record.stage != stage or record.input_kind != input_kind
                    or record.output_kind != output_kind or record.valid_fields & ~31
                    or not record.valid_fields & PTG_MAPPING_VALID_OBSERVED_VA
                    or not record.tree_id or record.reserved0
                    or record.pte_state not in (0, 1, 2, 3)):
                raise RuntimeError("PTG query returned invalid record metadata")
        return list(records)

    def capture_export_layout(self, ctx_id, stage):
        """Capture healthy managed backing before fault mutation; caller owns host RAM policy."""
        self._require_mapping_v1()
        ctx_id = _mapping_uint(ctx_id, 32, "context")
        stage = _mapping_stage(stage)
        request = PtgExportLayoutRequestV1()
        _mapping_status("initialize export request", self._lib.ptg_export_layout_v1_init(
            ctypes.byref(request), ctypes.sizeof(request)
        ))
        request.stage = stage
        identity = ctypes.c_uint64()
        _mapping_status("capture export layout", self._lib.ptg_export_layout_create_v1(
            self._handle, ctx_id, ctypes.byref(request), ctypes.byref(identity)
        ))
        if not identity.value:
            raise RuntimeError("PTG capture succeeded without a layout ID")
        return PtgExportLayout(self, ctx_id, stage, identity.value)

    def load_export_layouts(self, layouts, gen_thread, mem_bank=0):
        """Pull every layout before any host write. No recapture, fallback or write rollback.

        This initial batch interface accepts one context and disjoint SPA blocks.
        A pool-bound handle additionally requires its owning writer/bank and reserved SPA range.
        """
        self._require_mapping_v1()
        _mapping_uint(mem_bank, 32, "memory bank")
        if self._force_pool is not None:
            if gen_thread is not self._pool_writer or mem_bank != self._force_pool.bank:
                raise ValueError("strict export must use the reserved pool's writer and bank")
        layouts = tuple(layouts)
        if not layouts:
            raise ValueError("at least one captured layout is required")
        if any(not isinstance(layout, PtgExportLayout) or layout._owner is not self
               for layout in layouts):
            raise ValueError("export layouts must belong to this PTG handle")
        if len({layout._ctx_id for layout in layouts}) != 1:
            raise ValueError("export layouts must belong to one context")
        snapshots = [layout.read() for layout in layouts]
        spans = sorted((block.spa, block.spa + block.size)
                       for blocks, _ in snapshots for block in blocks)
        if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
            raise ValueError("strict export SPA blocks overlap")
        if self._force_pool is not None:
            if any(start < self._force_pool.base or end > self._force_pool.limit
                   for start, end in spans):
                raise ValueError("strict export SPA block is outside the reserved table pool")
        for blocks, data in snapshots:
            for block in blocks:
                gen_thread.writePhysicalMemory(
                    block.spa, data[block.data_offset:block.data_offset + block.size], mem_bank
                )

    def destroy(self):
        if self._handle:
            self._lib.ptg_destroy(self._handle)
            self._handle = None
        # The FORCE reservation outlives the PTG handle: an ISS may still use its page tables.
        self._pool_writer = None

    def __del__(self):
        self.destroy()

    def register_pa_region(self, base, limit):
        if self._force_pool is not None:
            raise ValueError("a reserved table pool cannot register another PA region")
        self._lib.ptg_register_pa_region(self._handle, base, limit)
        if self._placement_configured:
            _allocation_status("register PA region", self.last_error()[0])

    def register_gpa_region(self, vmid, base, limit):
        if self._force_pool is not None:
            self._check_pool_ready()
            _mapping_uint(vmid, 14, "VMID")
            _mapping_uint(base, 64, "GPA base")
            _mapping_uint(limit, 64, "GPA limit")
            if base == 0 or base >= limit or base % 0x1000 or limit % 0x1000:
                raise ValueError("GPA pool must be nonzero and 4 KiB aligned with exclusive limit")
            if self._pool_vmid is not None and vmid != self._pool_vmid:
                raise ValueError("a reserved table pool supports one VMID")
            if any(base < old_limit and old_base < limit
                   for old_base, old_limit in self._pool_gpa_regions):
                raise ValueError("reserved-pool GPA regions overlap")
        self._lib.ptg_register_gpa_region(self._handle, vmid, base, limit)
        if self._force_pool is not None:
            self._check_pool_call("register GPA region")
            self._pool_vmid = vmid
            self._pool_gpa_regions.append((base, limit))
        elif self._placement_configured:
            _allocation_status("register GPA region", self.last_error()[0])

    def create_context(self, asid=0, vmid=0):
        if self._force_pool is not None:
            self._check_pool_ready()
            if self._pool_context is not None:
                raise ValueError("a reserved table pool currently supports one VS/G context")
            _mapping_uint(asid, 16, "ASID")
            _mapping_uint(vmid, 14, "VMID")
            if vmid != self._pool_vmid:
                raise ValueError("register the reserved pool's GPA region before its context")
        context = self._lib.ptg_context_create(self._handle, asid, vmid)
        if self._force_pool is not None:
            self._check_pool_call("create reserved-pool context")
            self._pool_context = context
        elif self._placement_configured:
            _allocation_status("create context", self.last_error()[0])
        return context

    def set_s_stage(self, ctx_id, mode):
        if self._force_pool is not None:
            raise ValueError("reserved table pools currently support VS/G stages only")
        sv_code = SV_MODE_MAP.get(mode, mode) if isinstance(mode, str) else mode
        self._lib.ptg_context_s_stage(self._handle, ctx_id, sv_code)
        if self._placement_configured:
            _allocation_status("configure S stage", self.last_error()[0])

    def set_vs_stage(self, ctx_id, mode):
        sv_code = SV_MODE_MAP.get(mode, mode) if isinstance(mode, str) else mode
        self._begin_pool_stage(ctx_id, 1, sv_code)
        self._lib.ptg_context_vs_stage(self._handle, ctx_id, sv_code)
        if self._force_pool is not None:
            self._check_pool_call("configure VS stage")
        elif self._placement_configured:
            _allocation_status("configure VS stage", self.last_error()[0])

    def set_gs_stage(self, ctx_id, mode):
        sv_code = SV_MODE_MAP.get(mode, mode) if isinstance(mode, str) else mode
        self._begin_pool_stage(ctx_id, 2, sv_code)
        self._lib.ptg_context_gs_stage(self._handle, ctx_id, sv_code)
        if self._force_pool is not None:
            self._check_pool_call("configure G stage")
            hgatp = self.get_hgatp(ctx_id)
            root = (hgatp & ((1 << 44) - 1)) << 12
            if (hgatp >> 60 != sv_code or root % 0x4000 or root < self._force_pool.base
                    or root + 0x4000 > self._force_pool.limit):
                self._pool_failed = True
                raise RuntimeError("PTG G-stage root is not aligned inside the reserved pool")
        elif self._placement_configured:
            _allocation_status("configure G stage", self.last_error()[0])

    def _check_pool_ready(self):
        if self._force_pool is not None and (not self._handle or self._pool_failed):
            raise RuntimeError("reserved PTG pool is destroyed or its setup failed")

    def _check_pool_call(self, operation):
        code, _ = self.last_error()
        if code != PTG_OK:
            self._pool_failed = True
            raise PtgAllocationError(operation, code)

    def _begin_pool_stage(self, ctx_id, stage, mode):
        if self._force_pool is None:
            return
        self._check_pool_ready()
        _mapping_uint(ctx_id, 32, "context")
        if (ctx_id != self._pool_context or stage in self._pool_stages
                or type(mode) is not int or mode not in (8, 9, 10)):
            raise ValueError("reserved-pool stages require the owning context and one RV64 setup")
        self._pool_stages.add(stage)

    def get_satp(self, ctx_id):
        return self._lib.ptg_context_satp(self._handle, ctx_id)

    def get_vsatp(self, ctx_id):
        return self._lib.ptg_context_vsatp(self._handle, ctx_id)

    def get_hgatp(self, ctx_id):
        return self._lib.ptg_context_hgatp(self._handle, ctx_id)

    def set_vm_config(self, ctx_id, pbmte=1, adue=1, sum=0, mxr=0, sse=0):
        self._lib.ptg_context_set_vm_config(
            self._handle, ctx_id, pbmte, adue, sum, mxr, sse
        )

    def add_mapping(self, ctx_id, stage, va, pa, size, leaf_level=0, perm=7):
        self._check_pool_ready()
        stage_code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
        self._lib.ptg_add_mapping(
            self._handle, ctx_id, stage_code, va, pa, size, leaf_level, perm
        )
        if self._force_pool is not None:
            self._check_pool_call("add reserved-pool mapping")
        elif self._placement_configured:
            _allocation_status("add mapping", self.last_error()[0])

    def translate(self, ctx_id, va, access=0):
        fault_code = ctypes.c_uint8(0)
        pa = self._lib.ptg_translate(
            self._handle, ctx_id, va, access, ctypes.byref(fault_code)
        )
        return pa, fault_code.value

    def mapping_index_pa(self, ctx_id, stage, va):
        """Return an exact legacy index value, NOT a live translation or permission check.

        Zero ambiguously means PA=0 or no index entry. Entries can remain stale after
        clear/remap; see docs/PTG_MAPPING_QUERY_CONTRACT_REPORT.md. Do not use this
        diagnostic API to implement VmMapper validity/range queries.
        """
        stage_code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
        pa = self._lib.ptg_mapping_find_pa(self._handle, ctx_id, stage_code, va)
        code, message = self.last_error()
        if code != PTG_OK:
            raise RuntimeError(
                "PTG mapping index ctx={} stage={} failed: {} ({})".format(
                    ctx_id, stage, message, code
                )
            )
        return pa

    def mapping_index_vas(self, ctx_id, stage, pa):
        """Return all exact legacy index aliases; not live reverse address translation.

        The caller must serialize access to this handle. Reject a changed count between
        sizing and filling rather than returning a truncated or partly initialized list.
        The index limitations documented by mapping_index_pa also apply here.
        """
        stage_code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
        count = self._lib.ptg_mapping_find_vas(self._handle, ctx_id, stage_code, pa, None, 0)
        code, message = self.last_error()
        if code != PTG_OK:
            raise RuntimeError(
                "PTG mapping index ctx={} stage={} failed: {} ({})".format(
                    ctx_id, stage, message, code
                )
            )
        if count == 0:
            return []
        values = (ctypes.c_uint64 * count)()
        actual = self._lib.ptg_mapping_find_vas(
            self._handle, ctx_id, stage_code, pa, values, count
        )
        code, message = self.last_error()
        if code != PTG_OK:
            raise RuntimeError(
                "PTG mapping index ctx={} stage={} failed: {} ({})".format(
                    ctx_id, stage, message, code
                )
            )
        if actual != count:
            raise RuntimeError("PTG mapping index changed during alias query")
        return list(values)

    def random_generate(self, ctx_id, stage, config, max_mappings=1024):
        self._check_pool_ready()
        stage_code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
        out = (PtgMapping * max_mappings)()
        count = self._lib.ptg_random_generate(
            self._handle,
            ctx_id,
            stage_code,
            ctypes.byref(config),
            out,
            max_mappings,
        )
        if self._placement_configured:
            _allocation_status("random generation", self.last_error()[0])
        return count, out

    def inject_fault(self, ctx_id, stage, config):
        stage_code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
        return self._lib.ptg_inject_fault(
            self._handle, ctx_id, stage_code, ctypes.byref(config)
        )

    def create_fault_request_v2(self):
        request = PtgFaultRequestV2()
        status = self._lib.ptg_fault_request_v2_init(
            ctypes.byref(request), ctypes.sizeof(request)
        )
        if status != PTG_FAULT_OK:
            raise RuntimeError(
                "ptg_fault_request_v2_init failed: "
                + PTG_FAULT_STATUS_MAP.get(status, str(status))
            )
        return request

    def create_vm_config_v2(
        self, target="S_VS", pbmte=1, adue=1, sum=0, mxr=0, sse=0, svnapot=0
    ):
        config = PtgVmConfigV2()
        status = self._lib.ptg_vm_config_v2_init(
            ctypes.byref(config), ctypes.sizeof(config)
        )
        if status != PTG_FAULT_OK:
            raise RuntimeError(
                "ptg_vm_config_v2_init failed: "
                + PTG_FAULT_STATUS_MAP.get(status, str(status))
            )
        if isinstance(target, str):
            if target not in VM_CONFIG_TARGET_MAP:
                raise ValueError("V2 VM target must be 'S_VS' or 'G'")
            target = VM_CONFIG_TARGET_MAP[target]
        if target not in (PTG_VM_CONFIG_S_VS, PTG_VM_CONFIG_G):
            raise ValueError(
                "V2 VM target must be PTG_VM_CONFIG_S_VS or PTG_VM_CONFIG_G"
            )
        config.target = target
        config.pbmte = pbmte
        config.adue = adue
        config.sum = sum
        config.mxr = mxr
        config.sse = sse
        config.svnapot = svnapot
        return config

    def set_vm_config_v2(self, ctx_id, config):
        if not isinstance(config, PtgVmConfigV2):
            raise TypeError("config must be a PtgVmConfigV2")
        if config.target not in (PTG_VM_CONFIG_S_VS, PTG_VM_CONFIG_G):
            raise ValueError(
                "V2 exposes only shared S_VS and G VM configuration targets"
            )
        return self._lib.ptg_context_set_vm_config_v2(
            self._handle, ctx_id, ctypes.byref(config)
        )

    def inject_fault_v2(self, ctx_id, request, allow_per_mutation_verification=False):
        """Execute a V2 request using the required two-call result protocol."""
        if not isinstance(request, PtgFaultRequestV2):
            raise TypeError("request must be a PtgFaultRequestV2")
        batch_mode = request.selection_mode in (
            PTG_FAULT_SELECTION_EXACT_COUNT,
            PTG_FAULT_SELECTION_PROBABILITY,
        )
        if (
            batch_mode
            and request.verification_mode == PTG_FAULT_VERIFY_REQUIRE_FAULT
            and not (request.flags & PTG_FAULT_ONE_PER_WALK)
            and not allow_per_mutation_verification
        ):
            raise ValueError(
                "batch REQUIRE_FAULT needs PTG_FAULT_ONE_PER_WALK; pass "
                "allow_per_mutation_verification=True to accept per-mutation-only verification"
            )

        result_size = ctypes.sizeof(PtgFaultResultV2)
        out_count = ctypes.c_uint32(0)
        status = self._lib.ptg_inject_fault_v2(
            self._handle,
            ctx_id,
            ctypes.byref(request),
            None,
            0,
            result_size,
            ctypes.byref(out_count),
        )
        if status == PTG_FAULT_OK and out_count.value == 0:
            return status, ()
        if status != PTG_FAULT_BUFFER_TOO_SMALL:
            return status, ()
        if out_count.value == 0:
            raise RuntimeError("ptg_inject_fault_v2 requested an empty result buffer")

        capacity = out_count.value
        result_array = (PtgFaultResultV2 * capacity)()
        status = self._lib.ptg_inject_fault_v2(
            self._handle,
            ctx_id,
            ctypes.byref(request),
            result_array,
            capacity,
            result_size,
            ctypes.byref(out_count),
        )
        if status == PTG_FAULT_BUFFER_TOO_SMALL or out_count.value > capacity:
            raise RuntimeError(
                "ptg_inject_fault_v2 result count changed after preflight"
            )
        results = tuple(
            PtgFaultResultV2.from_buffer_copy(result_array[index])
            for index in range(out_count.value)
        )
        return status, results

    def get_fault_stats(self):
        return self._lib.ptg_fault_stats(self._handle)

    def validate(self, ctx_id):
        return self._lib.ptg_validate(self._handle, ctx_id)

    def sfence_vma(self, ctx_id, va=0, asid=0):
        self._lib.ptg_sfence_vma(self._handle, ctx_id, va, asid)

    def hfence_gvma(self, vmid=0, gpa=0):
        self._lib.ptg_hfence_gvma(self._handle, vmid, gpa)

    def inject_implicit_guest_fault(self, ctx_id, config):
        return self._lib.ptg_inject_implicit_guest_fault(
            self._handle, ctx_id, ctypes.byref(config)
        )

    def inject_explicit_guest_fault(self, ctx_id, config):
        return self._lib.ptg_inject_explicit_guest_fault(
            self._handle, ctx_id, ctypes.byref(config)
        )

    def translate_sequential(self, ctx_id, va, access=0):
        fault_code = ctypes.c_uint8(0)
        fault_level = ctypes.c_uint8(0)
        pa = self._lib.ptg_translate_sequential(
            self._handle,
            ctx_id,
            va,
            access,
            ctypes.byref(fault_code),
            ctypes.byref(fault_level),
        )
        return pa, fault_code.value, fault_level.value

    def debug_implicit_guest_fault(self, ctx_id, probability, seed):
        return self._lib.ptg_debug_implicit_guest_fault(
            self._handle, ctx_id, probability, seed
        )

    def debug_explicit_guest_fault(self, ctx_id, probability, seed):
        return self._lib.ptg_debug_explicit_guest_fault(
            self._handle, ctx_id, probability, seed
        )

    def set_gs_vm_config(self, ctx_id, pbmte=1, adue=1, sum=0, mxr=0, sse=0):
        return self._lib.ptg_context_set_gs_vm_config(
            self._handle, ctx_id, pbmte, adue, sum, mxr, sse
        )

    def inject_faults(self, ctx_id, stage, configs):
        stage_code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
        count = len(configs)
        arr = (PtgFaultConfig * count)(*configs)
        return self._lib.ptg_inject_faults(self._handle, ctx_id, stage_code, arr, count)

    def invalidate_by_asid(self, asid):
        return self._lib.ptg_invalidate_by_asid(self._handle, asid)

    def invalidate_by_vmid(self, vmid):
        return self._lib.ptg_invalidate_by_vmid(self._handle, vmid)

    def remap_va(self, ctx_id, stage, va, new_pa):
        stage_code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
        self._lib.ptg_remap_va(self._handle, ctx_id, stage_code, va, new_pa)

    def load_to_force(self, ctx_id, stage, gen_thread, mem_bank=0):
        """Export first, then write in Python so ctypes cannot swallow writer exceptions.

        A writer failure stops further writes but does not roll back earlier ones.
        Legacy PTG VS export still requires valid G-stage backing; see the strict-export
        requirement in docs/PTG_FORCE_INTEGRATION_REQUIREMENTS.md.
        """
        if self._force_pool is not None:
            raise ValueError("reserved table pools require captured strict export layouts")
        for pa, data in self.get_force_blocks(ctx_id, stage):
            gen_thread.writePhysicalMemory(pa, data, mem_bank)

    def get_force_blocks(self, ctx_id, stage):
        """Return page-table blocks at the physical addresses used by FORCE."""
        stage_code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
        blocks = []
        callback_errors = []

        @WRITE_FN_TYPE
        def _collect_callback(pa, data_ptr, size, userdata):
            if callback_errors:
                return
            try:
                blocks.append((pa, ctypes.string_at(data_ptr, size)))
            except BaseException as error:
                # Exceptions must be raised after leaving the C callback boundary.
                callback_errors.append(error)

        self._lib.ptg_dump_binary_write(
            self._handle, ctx_id, stage_code, _collect_callback, None
        )
        if callback_errors:
            raise callback_errors[0]
        code, message = self.last_error()
        if code != PTG_OK:
            raise RuntimeError(
                "PTG export ctx={} stage={} failed: {} ({})".format(ctx_id, stage, message, code)
            )
        return blocks

    def save_state(self, filename):
        return self._lib.ptg_save_state(self._handle, filename.encode())

    def restore_state(self, filename):
        if self._force_pool is not None:
            raise ValueError("restoring a reserved-pool handle is not supported")
        return self._lib.ptg_restore_state(self._handle, filename.encode())

    def dump_binary(self, ctx_id, stage, filename):
        stage_code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
        self._lib.ptg_dump_binary(self._handle, ctx_id, stage_code, filename.encode())

    def dump_json(self, ctx_id, stage, filename):
        stage_code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
        self._lib.ptg_dump_json(self._handle, ctx_id, stage_code, filename.encode())

    def get_blocks(self, ctx_id, stage):
        stage_code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
        return self._lib.ptg_dump_binary_blocks(self._handle, ctx_id, stage_code)

    def free_blocks(self, blocks):
        self._lib.ptg_free_blocks(blocks)

    def last_error(self):
        code = self._lib.ptg_last_error(self._handle)
        return code, self._lib.ptg_error_string(code).decode()


class PtgBackend:
    def __init__(self, lib_path=None):
        self.handle = None
        self._ctx_ids = []
        self.handle = PtgHandle(lib_path)

    def destroy(self):
        self._ctx_ids.clear()
        if self.handle is not None:
            self.handle.destroy()

    def __del__(self):
        self.destroy()

    @classmethod
    def with_reserved_table_pool(cls, gen_thread, name, size, ram_base, ram_limit,
                                 mem_bank=0, lib_path=None):
        """Create a fresh backend with a FORCE-reserved, explicitly approved RAM pool.

        Limits are exclusive. Selection and reservation occur under the FORCE scheduler lock.
        RAM/MMIO classification is the caller's responsibility; FORCE's usable space alone
        is not a RAM declaration. The reservation lasts for the generation, even on destroy
        or a later setup failure. This first owned-pool contract supports one VS/G context.
        """
        if not isinstance(name, str) or not name:
            raise ValueError("a unique, nonempty FORCE reservation name is required")
        for value, bits, label in ((size, 64, "pool size"), (ram_base, 64, "RAM base"),
                                   (ram_limit, 64, "RAM limit"), (mem_bank, 32, "memory bank")):
            _mapping_uint(value, bits, label)
        if (size < 0x4000 or size % 0x4000 or ram_base == 0 or ram_base >= ram_limit
                or size > ram_limit - ram_base):
            raise ValueError("pool needs a nonzero RAM range and a positive 16 KiB-multiple size")
        backend = cls(lib_path)
        try:
            backend.handle._require_mapping_v1()
            backend.handle._require_placement_v1()
            gen_thread.lockThreadScheduler()
            try:
                base = gen_thread.genPA({
                    "Size": size, "Align": 0x4000, "Type": "D", "Bank": mem_bank,
                    "ForceNewAddr": 1, "Range": "0x%x-0x%x" % (ram_base, ram_limit - 1),
                })
                _mapping_uint(base, 64, "selected pool base")
                if base % 0x4000 or base < ram_base or base + size > ram_limit:
                    raise RuntimeError(
                        "FORCE allocator returned a pool outside its RAM constraint"
                    )
                gen_thread.reserveMemoryRange(name, base, size, mem_bank, False)
            finally:
                gen_thread.unlockThreadScheduler()
            backend.handle.register_pa_region(base, base + size)
            backend.handle._check_pool_call("register reserved PA pool")
            backend.handle._force_pool = PtgTablePool(name, base, base + size, mem_bank)
            backend.handle._pool_writer = gen_thread
            backend.configure_pa_placement(PtgPlacement())
            return backend
        except BaseException:
            backend.destroy()
            raise

    @property
    def table_pool(self):
        return self.handle._force_pool if self.handle is not None else None

    def create_s_stage_context(
        self, sv_mode="Sv39", asid=0, vmid=0, pa_base=None, pa_limit=None
    ):
        if pa_base is not None and pa_limit is not None:
            self.handle.register_pa_region(pa_base, pa_limit)
        ctx_id = self.handle.create_context(asid=asid, vmid=vmid)
        self.handle.set_s_stage(ctx_id, sv_mode)
        self._ctx_ids.append(ctx_id)
        return ctx_id

    def create_two_stage_context(
        self,
        vs_mode="Sv39",
        gs_mode="Sv39x4",
        asid=0,
        vmid=0,
        pa_base=None,
        pa_limit=None,
        gpa_base=None,
        gpa_limit=None,
        pa_placement=None,
        gpa_placement=None,
    ):
        for policy in (pa_placement, gpa_placement):
            if policy is not None:
                if not isinstance(policy, PtgPlacement):
                    raise TypeError("policy must be a PtgPlacement")
                PtgPlacement(*policy)
                self.handle._require_placement_v1()
        checked = (self.handle._placement_configured or pa_placement is not None
                   or gpa_placement is not None)
        if checked:
            _mapping_uint(asid, 16, "ASID")
            _mapping_uint(vmid, 14, "VMID")
            for base, limit in ((pa_base, pa_limit), (gpa_base, gpa_limit)):
                if (base is None) != (limit is None):
                    raise ValueError("provide both region base and exclusive limit")
                if base is not None:
                    _mapping_uint(base, 64, "region base")
                    _mapping_uint(limit, 64, "region limit")
                    if base >= limit:
                        raise ValueError("region must be nonempty")
        if pa_base is not None and pa_limit is not None:
            self.handle.register_pa_region(pa_base, pa_limit)
            if checked:
                _allocation_status("register PA region", self.handle.last_error()[0])
        if gpa_base is not None and gpa_limit is not None:
            self.handle.register_gpa_region(vmid, gpa_base, gpa_limit)
            if checked:
                _allocation_status("register GPA region", self.handle.last_error()[0])
        if pa_placement is not None:
            self.configure_pa_placement(pa_placement)
        if gpa_placement is not None:
            self.configure_gpa_placement(vmid, gpa_placement)
        ctx_id = self.handle.create_context(asid=asid, vmid=vmid)
        if self.handle._placement_configured:
            self.handle.set_gs_stage(ctx_id, gs_mode)
            self.handle.set_vs_stage(ctx_id, vs_mode)
        else:
            self.handle.set_vs_stage(ctx_id, vs_mode)
            self.handle.set_gs_stage(ctx_id, gs_mode)
        self._ctx_ids.append(ctx_id)
        return ctx_id

    def generate_random(
        self,
        ctx_id,
        stage,
        va_start,
        va_end,
        pa_start,
        pa_end,
        sv_mode="Sv39",
        count=10,
        seed=None,
        **kwargs,
    ):
        cfg = PtgRandomConfig()
        cfg.va_start = va_start
        cfg.va_end = va_end
        cfg.pa_start = pa_start
        cfg.pa_end = pa_end
        cfg.min_mappings = count
        cfg.max_mappings = count
        cfg.seed = seed if seed is not None else 42
        cfg.sv_mode = (
            SV_MODE_MAP.get(sv_mode, sv_mode) if isinstance(sv_mode, str) else sv_mode
        )
        cfg.access_types = kwargs.get("access_types", 7)
        cfg.default_perm = kwargs.get("default_perm", 0)
        cfg.flags_a = kwargs.get("flags_a", 0)
        cfg.flags_d = kwargs.get("flags_d", 0)
        cfg.flags_g = kwargs.get("flags_g", 0)
        cfg.flags_u = kwargs.get("flags_u", 0)
        cfg.force_new = kwargs.get("force_new", 1)
        cfg.merge_probability = kwargs.get("merge_probability", 1.0)
        cfg.pbmte = kwargs.get("pbmte", 1)
        cfg.adue = kwargs.get("adue", 1)
        cfg.sum = kwargs.get("sum", 0)
        cfg.mxr = kwargs.get("mxr", 0)
        cfg.sse = kwargs.get("sse", 0)
        cfg.size_4kb_weight = kwargs.get("size_4kb_weight", 1.0)
        cfg.size_2mb_weight = kwargs.get("size_2mb_weight", 0.0)
        cfg.size_1gb_weight = kwargs.get("size_1gb_weight", 0.0)
        cfg.size_512gb_weight = kwargs.get("size_512gb_weight", 0.0)
        cfg.ss_probability = kwargs.get("ss_probability", 0.0)
        cfg.gs_inherit = kwargs.get("gs_inherit", 0)
        cfg.gs_conflict_mode = kwargs.get("gs_conflict_mode", 0)
        cfg.fault_cause = kwargs.get("fault_cause", 0)
        return self.handle.random_generate(ctx_id, stage, cfg)

    def load_to_force(self, ctx_id, stage, gen_thread, mem_bank=0):
        return self.handle.load_to_force(ctx_id, stage, gen_thread, mem_bank)

    def configure_pa_placement(self, policy):
        return self.handle.configure_pa_placement(policy)

    def configure_gpa_placement(self, vmid, policy):
        return self.handle.configure_gpa_placement(vmid, policy)

    def query_mappings(self, ctx_id, stage, address=0, direction="forward", domain="current"):
        return self.handle.query_mappings(ctx_id, stage, address, direction, domain)

    def capture_export_layout(self, ctx_id, stage):
        return self.handle.capture_export_layout(ctx_id, stage)

    def load_export_layouts(self, layouts, gen_thread, mem_bank=0):
        return self.handle.load_export_layouts(layouts, gen_thread, mem_bank)

    def validate(self, ctx_id):
        return self.handle.validate(ctx_id)

    def translate(self, ctx_id, va, access=0):
        return self.handle.translate(ctx_id, va, access)

    def create_fault_request_v2(self):
        return self.handle.create_fault_request_v2()

    def create_vm_config_v2(
        self, target="S_VS", pbmte=1, adue=1, sum=0, mxr=0, sse=0, svnapot=0
    ):
        return self.handle.create_vm_config_v2(
            target=target,
            pbmte=pbmte,
            adue=adue,
            sum=sum,
            mxr=mxr,
            sse=sse,
            svnapot=svnapot,
        )

    def set_vm_config_v2(self, ctx_id, config):
        return self.handle.set_vm_config_v2(ctx_id, config)

    def inject_fault_v2(self, ctx_id, request, allow_per_mutation_verification=False):
        return self.handle.inject_fault_v2(
            ctx_id,
            request,
            allow_per_mutation_verification=allow_per_mutation_verification,
        )
