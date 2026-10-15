"""Single-hart PTG context, structural translation queries and publish/activate lifecycle.

This GenThread adapter does not replace the C++ VmMapper or authorize accesses.
PTG constructs every PTE; queries observe PTG state, not an ISS TLB snapshot.
"""

from collections import namedtuple

from riscv.paging.PtgBackend import (
    PTG_MAPPING_VALID_CURRENT,
    PTG_MAPPING_VALID_LOGICAL,
    PTG_MAPPING_VALID_MATCH,
    PTG_MAPPING_VALID_PTE,
    PtgBackend,
    PtgPlacement,
)


PtgTranslationRange = namedtuple(
    "PtgTranslationRange", "gva_base gpa_base spa_base size vs_perm g_perm vs_level g_level"
)


def _uint(value, bits, name):
    if type(value) is not int or not 0 <= value < (1 << bits):
        raise ValueError("{} must be an unsigned {}-bit integer".format(name, bits))
    return value


def _region(region, limit, name):
    base, end = tuple(region)
    _uint(base, 64, name)
    _uint(end, 64, name)
    if not base < end <= limit or base % 0x1000 or end % 0x1000:
        raise ValueError("{} must be a nonempty page-aligned half-open region".format(name))
    return base, end


def _inside(base, size, region):
    return region[0] <= base and size > 0 and base + size <= region[1]


def _overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1]


def _current(record):
    required = PTG_MAPPING_VALID_CURRENT | PTG_MAPPING_VALID_MATCH | PTG_MAPPING_VALID_PTE
    return record.valid_fields & required == required and record.pte_state == 0


class PtgVmContext:
    """One immutable-after-publication Sv39/Sv39x4 context per reserved table pool.

    Caller-approved table/data RAM must be disjoint. GVA is limited to Sv39's
    lower canonical half; GPA data and GPA table storage must be disjoint.
    Each context uses its own PTG handle. No RAM or VMID is recycled by close().
    Methods and other operations on the owning GenThread must be serialized.
    """

    def __init__(self, gen_thread, name, asid, vmid, table_ram, data_ram,
                 gva_range, gpa_range, table_gpa_range, table_size=0x100000,
                 lib_path=None):
        self._backend = None
        self._layouts = ()
        self._snapshots = ()
        self._state = "building"
        self._owner = gen_thread
        self._name = name
        self._data = []
        self._roots = None
        if gen_thread.genThreadID != 0:
            raise ValueError("PTG managed contexts support hart 0 only")
        _uint(asid, 16, "ASID")
        _uint(vmid, 14, "VMID")
        self._asid, self._vmid = asid, vmid
        self._table_ram = _region(table_ram, 1 << 56, "table RAM")
        self._data_ram = _region(data_ram, 1 << 56, "data RAM")
        self._gva = _region(gva_range, 1 << 38, "GVA range")
        self._gpa = _region(gpa_range, 1 << 41, "GPA range")
        self._table_gpa = _region(table_gpa_range, 1 << 41, "GPA table range")
        if _overlaps(self._table_ram, self._data_ram) or _overlaps(self._gpa, self._table_gpa):
            raise ValueError("table and payload address domains must not overlap")
        try:
            self._backend = PtgBackend.with_reserved_table_pool(
                gen_thread, name, table_size, *self._table_ram, lib_path=lib_path
            )
            self._context_id = self._backend.create_two_stage_context(
                asid=asid, vmid=vmid, gpa_base=self._table_gpa[0],
                gpa_limit=self._table_gpa[1], gpa_placement=PtgPlacement()
            )
        except BaseException:
            self.close()
            raise

    @property
    def state(self):
        return self._state

    @property
    def asid(self):
        return self._asid

    @property
    def vmid(self):
        return self._vmid

    @property
    def context_id(self):
        return self._context_id

    @property
    def table_pool(self):
        return self._backend.table_pool if self._backend is not None else None

    def _check(self, building=False):
        if self._state in ("closed", "failed"):
            raise RuntimeError("PTG context is " + self._state)
        if building and self._state != "building":
            raise RuntimeError("published PTG contexts are immutable")

    def _check_mapping(self, gva, gpa, size, vs_level, g_level, vs_perm, g_perm):
        self._check(building=True)
        for value, name in ((gva, "GVA"), (gpa, "GPA"), (size, "size")):
            _uint(value, 64, name)
        for level in (vs_level, g_level):
            if type(level) is not int or level not in (0, 1, 2):
                raise ValueError("Sv39 leaf level must be 0, 1 or 2")
        alignment = 1 << (12 + 9 * max(vs_level, g_level))
        if gva % alignment or gpa % alignment or not size or size % alignment:
            raise ValueError("mapping must align to and cover complete VS/G leaves")
        if not _inside(gva, size, self._gva) or not _inside(gpa, size, self._gpa):
            raise ValueError("mapping is outside context address constraints")
        for perm in (vs_perm, g_perm):
            _uint(perm, 7, "raw permissions")
            if perm & 8 or not perm & 7 or perm & 2 and not perm & 1 or perm & 0x60 != 0x60:
                raise ValueError("managed mappings require legal leaf permissions and A/D set")
        if not g_perm & 0x10:
            raise ValueError("G-stage leaves require U=1")
        return alignment

    def _reject_existing(self, stage, address, size):
        records = self._backend.query_mappings(
            self.context_id, stage, direction="enumerate", domain="logical"
        )
        for record in records:
            if record.valid_fields & PTG_MAPPING_VALID_LOGICAL:
                r = record.logical
                if _overlaps((address, address + size), (r.va_base, r.va_base + r.page_size)):
                    raise ValueError("mapping overlaps an existing PTG logical range")

    def map(self, gva, gpa, size=0x1000, vs_level=0, g_level=0,
            vs_perm=0x63, g_perm=0x73):
        """Reserve SPA using FORCE and map constrained GVA/GPA through PTG. Return SPA.

        Mapping failures may leave partial PTG publications. The context then fails
        closed, while all host reservations remain held. No implicit rollback.
        """
        alignment = self._check_mapping(gva, gpa, size, vs_level, g_level, vs_perm, g_perm)
        self._reject_existing("VS", gva, size)
        self._reject_existing("G", gpa, size)
        owner = self._owner
        owner.lockThreadScheduler()
        try:
            spa = owner.genPA({"Size": size, "Align": alignment, "Type": "D", "Bank": 0,
                               "ForceNewAddr": 1,
                               "Range": "0x%x-0x%x" % (self._data_ram[0], self._data_ram[1] - 1)})
            _uint(spa, 64, "selected SPA")
            if spa % alignment or not _inside(spa, size, self._data_ram):
                raise RuntimeError("FORCE allocator returned data outside its constraint")
            owner.reserveMemoryRange(self._name + ".data." + str(len(self._data)),
                                     spa, size, 0, False)
            self._data.append((spa, spa + size))
        except BaseException:
            self._state = "failed"
            raise
        finally:
            owner.unlockThreadScheduler()
        try:
            self._install_leaves("G", gpa, spa, size, g_level, g_perm)
            self._install_leaves("VS", gva, gpa, size, vs_level, vs_perm)
        except BaseException:
            self._state = "failed"
            raise
        return spa

    def _install_leaves(self, stage, source, target, size, level, perm):
        # ptg_add_mapping installs one leaf. A range request delegates each leaf to PTG.
        page_size = 1 << (12 + 9 * level)
        for offset in range(0, size, page_size):
            self._backend.handle.add_mapping(self.context_id, stage, source + offset,
                                             target + offset, page_size, level, perm)

    def map_alias(self, gva, gpa, size=0x1000, vs_perm=0x63):
        """Create 4-KiB VS aliases of already mapped, owned payload backing."""
        self._check_mapping(gva, gpa, size, 0, 0, vs_perm, 0x73)
        self._reject_existing("VS", gva, size)
        for offset in range(0, size, 0x1000):
            record = self._one_current("G", gpa + offset)
            if record is None or not any(_inside(record.matched_pa, 0x1000, r) for r in self._data):
                raise ValueError("alias requires existing context-owned GPA backing")
        try:
            self._install_leaves("VS", gva, gpa, size, 0, vs_perm)
        except BaseException:
            self._state = "failed"
            raise

    def initialize_data(self, spa, data):
        self._check(building=True)
        _uint(spa, 64, "SPA")
        data = bytes(data)
        if not any(_inside(spa, len(data), r) for r in self._data):
            raise ValueError("initialization must lie in context-owned payload RAM")
        try:
            self._owner.writePhysicalMemory(spa, data, 0)
        except BaseException:
            self._state = "failed"
            raise

    def _one_current(self, stage, address):
        records = self._backend.query_mappings(self.context_id, stage, address)
        current = [r for r in records if _current(r)]
        if len(current) > 1:
            raise RuntimeError("ambiguous PTG current forward query")
        return current[0] if current else None

    def lookup(self, gva):
        """Compose PTG CURRENT leaf ranges. Return metadata, NOT access authorization."""
        self._check()
        _uint(gva, 64, "GVA")
        if not _inside(gva, 1, self._gva):
            return None
        vs = self._one_current("VS", gva)
        if vs is None:
            return None
        gs = self._one_current("G", vs.matched_pa)
        if gs is None:
            return None
        v, g = vs.current, gs.current
        # Intersect the VS output range with the G input range, then pull back to GVA.
        low = max(v.pa_base, g.va_base)
        high = min(v.pa_base + v.page_size, g.va_base + g.page_size)
        if not low <= vs.matched_pa < high:
            raise RuntimeError("PTG returned inconsistent composed ranges")
        return PtgTranslationRange(v.va_base + low - v.pa_base, low,
                                   g.pa_base + low - g.va_base, high - low,
                                   vs.raw_perm, gs.raw_perm, v.leaf_level, g.leaf_level)

    def translate(self, gva):
        info = self.lookup(gva)
        return None if info is None else info.spa_base + gva - info.gva_base

    def reverse(self, spa):
        """Return all current in-context GVA aliases, without a FORCE mapping cache."""
        self._check()
        _uint(spa, 64, "SPA")
        values = set()
        for gs in self._backend.query_mappings(self.context_id, "G", spa, direction="reverse"):
            if not _current(gs):
                continue
            for vs in self._backend.query_mappings(
                    self.context_id, "VS", gs.matched_va, direction="reverse"):
                if _current(vs) and _inside(vs.matched_va, 1, self._gva):
                    values.add(vs.matched_va)
        return tuple(sorted(values))

    def publish(self):
        """Freeze PTG topology and initialize table bytes in FORCE/ISS/ELF exactly once."""
        self._check(building=True)
        try:
            self._layouts = (self._backend.capture_export_layout(self.context_id, "VS"),)
            self._layouts += (self._backend.capture_export_layout(self.context_id, "G"),)
            self._snapshots = tuple(self._snapshot(layout) for layout in self._layouts)
            self._roots = self._read_roots()
            self._backend.load_export_layouts(self._layouts, self._owner)
            self._state = "published"
        except BaseException:
            self._state = "failed"
            raise

    @staticmethod
    def _snapshot(layout):
        records, data = layout.read()
        return tuple(bytes(r) for r in records), data

    def _read_roots(self):
        h = self._backend.handle
        vsatp, hgatp = h.get_vsatp(self.context_id), h.get_hgatp(self.context_id)
        if (vsatp >> 60 != 8 or hgatp >> 60 != 8
                or (vsatp >> 44) & 0xFFFF != self.asid
                or (hgatp >> 44) & 0x3FFF != self.vmid):
            raise RuntimeError("PTG root mode/ASID/VMID does not match the context")
        return vsatp, hgatp

    def activate(self, scratch=5):
        """Emit M-mode CSR/global-fence activation. Never rewrite published table bytes."""
        self._check()
        if type(scratch) is not int or not 1 <= scratch < 32:
            raise ValueError("activation requires a nonzero scratch GPR")
        if self._owner.getPEstate("PrivilegeLevel") != 3:
            raise ValueError("managed activation requires M-mode")
        if self._state == "building":
            self.publish()
        try:
            if self._read_roots() != self._roots or tuple(
                    self._snapshot(layout) for layout in self._layouts) != self._snapshots:
                raise RuntimeError("published PTG context changed outside the managed API")
            from riscv.Utils import LoadGPR64
            owner = self._owner
            def csr(number, value):
                if value:
                    LoadGPR64(owner).load(scratch, value)
                owner.genInstruction("CSRRW#register#RISCV", {
                    "rd": 0, "rs1": scratch if value else 0, "csr": number, "NoRestriction": 1,
                })
            def fence(name):
                owner.genInstruction(name + "##RISCV", {
                    "rs1": 0, "rs2": 0, "NoRestriction": 1,
                })
            csr(0x280, 0)
            fence("HFENCE.VVMA")
            csr(0x680, self._roots[1])
            fence("HFENCE.GVMA")
            csr(0x280, self._roots[0])
            fence("HFENCE.VVMA")
            LoadGPR64(owner).load(scratch, 0x100)  # HSTATUS.SPVP selects VS accesses.
            owner.genInstruction("CSRRS#register#RISCV", {
                "rd": 0, "rs1": scratch, "csr": 0x600, "NoRestriction": 1,
            })
        except BaseException:
            self._state = "failed"
            raise

    def close(self):
        closing = getattr(self._owner, "_ptgContextClosing", None)
        if closing is not None:
            closing(self)
        for layout in self._layouts:
            layout.close()
        self._layouts = ()
        if self._backend is not None:
            self._backend.destroy()
        self._state = "closed"
