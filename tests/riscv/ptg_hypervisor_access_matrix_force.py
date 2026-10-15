"""Strong H-extension access checks against PTG-generated page tables."""

import struct

from base.Sequence import Sequence
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from riscv.Utils import LoadGPR64
from riscv.paging.PtgBackend import PtgBackend, PtgPlacement


RW_GVA = 0x40200000
RW_GPA = 0x82200000
RW_SPA = 0x110200000
STORE_GVA = 0x40300000
STORE_GPA = 0x82300000
STORE_SPA = 0x110300000
X_GVA = 0x40400000
X_GPA = 0x82400000
X_SPA = 0x110400000

INITIAL_VALUE = 0x1122334455667788
STORED_VALUE = 0x8877665544332211
EXEC_WORD = 0xA1B2C3D4

VS_RW_UAD = 0x73
VS_X_UAD = 0x74
G_RWX_UAD = 0x77


class MainSequence(Sequence):
    def generate(self, **kargs):
        ptg = PtgBackend.with_reserved_table_pool(
            self.genThread, "PTGAccessTables", 0x100000, 0x88000000, 0x89000000
        )
        try:
            base = ptg.table_pool.base
            ptg.configure_pa_placement(PtgPlacement(levels=(
                (2, base + 0x10000, base + 0x14000),
                (1, base + 0x20000, base + 0x28000),
                (0, base + 0x30000, base + 0x38000),
            )))
            ctx = ptg.create_two_stage_context(
                vs_mode="Sv39",
                gs_mode="Sv39x4",
                asid=0x31,
                vmid=0x11,
                gpa_base=0x90000000,
                gpa_limit=0x91000000,
                gpa_placement=PtgPlacement(levels=(
                    (2, 0x90008000, 0x90009000),
                    (1, 0x90010000, 0x90018000),
                    (0, 0x90020000, 0x90028000),
                )),
            )
            roots = ptg.handle.get_vsatp(ctx), ptg.handle.get_hgatp(ctx)
            mask = (1 << 44) - 1
            if ((roots[0] & mask) << 12, (roots[1] & mask) << 12) != (
                    0x90008000, base + 0x10000):
                self.error("PTG placement did not select the requested VS/G root windows")

            ptg.handle.add_mapping(ctx, "VS", RW_GVA, RW_GPA, 0x1000, 0, VS_RW_UAD)
            ptg.handle.add_mapping(ctx, "G", RW_GPA, RW_SPA, 0x1000, 0, G_RWX_UAD)
            ptg.handle.add_mapping(
                ctx, "VS", STORE_GVA, STORE_GPA, 0x1000, 0, VS_RW_UAD
            )
            ptg.handle.add_mapping(
                ctx, "G", STORE_GPA, STORE_SPA, 0x1000, 0, G_RWX_UAD
            )
            ptg.handle.add_mapping(ctx, "VS", X_GVA, X_GPA, 0x1000, 0, VS_X_UAD)
            ptg.handle.add_mapping(ctx, "G", X_GPA, X_SPA, 0x1000, 0, G_RWX_UAD)

            validation = ptg.validate(ctx)
            if not validation.all_ok:
                self.error("PTG access-matrix page tables failed validation")

            with ptg.capture_export_layout(ctx, "VS") as vs_layout:
                with ptg.capture_export_layout(ctx, "G") as g_layout:
                    snapshots = [layout.read() for layout in (vs_layout, g_layout)]
                    ptg.configure_pa_placement(PtgPlacement(alignment=0x8000))
                    ptg.configure_gpa_placement(0x11, PtgPlacement(alignment=0x8000))
                    for layout, (blocks, data) in zip((vs_layout, g_layout), snapshots):
                        current, current_data = layout.read()
                        if ([bytes(b) for b in blocks], data) != (
                                [bytes(b) for b in current], current_data):
                            self.error("Online placement changed existing layout or PTE bytes")
                    if roots != (ptg.handle.get_vsatp(ctx), ptg.handle.get_hgatp(ctx)):
                        self.error("Online placement relocated an existing root")
                    ptg.load_export_layouts((vs_layout, g_layout), self.genThread)
            self.notice("PTG PLACEMENT V1: root windows and online non-relocation verified")
            self.notice("PTG STRICT EXPORT V1: access-matrix VS/G snapshot loaded")
            self.notice(
                f"PTG RESERVED TABLE POOL: 0x{ptg.table_pool.base:X}-"
                f"0x{ptg.table_pool.limit - 1:X} bank={ptg.table_pool.bank}"
            )
            self.genThread.writePhysicalMemory(
                RW_SPA, struct.pack("<Q", INITIAL_VALUE), 0
            )
            self.initializeMemory(
                addr=STORE_SPA,
                bank=0,
                size=8,
                data=0,
                is_instr=False,
                is_virtual=False,
            )
            self.genThread.writePhysicalMemory(X_SPA, struct.pack("<I", EXEC_WORD), 0)
            self.genThread.initializeRegister("hvip", "", 0x4)

            self.genThread.setupPtgCSRs(
                ptg_handle=ptg.handle,
                ctx_id=ctx,
                vs_mode="Sv39",
                g_mode="Sv39x4",
            )
            self._load_gpr(8, 0x200)  # hstatus.HU=1, SPVP=0 (VU access)
            self.genInstruction(
                "CSRRW#register#RISCV",
                {"rd": 0, "rs1": 8, "csr": 0x600, "NoRestriction": 1},
            )
            self.genInstruction(
                "HFENCE.VVMA##RISCV", {"rs1": 0, "rs2": 0, "NoRestriction": 1}
            )
            self.genInstruction(
                "HFENCE.GVMA##RISCV", {"rs1": 0, "rs2": 0, "NoRestriction": 1}
            )

            self._load_gpr(1, RW_GVA)
            self.genInstruction(
                "HLV.D##RISCV", {"rs1": 1, "rd": 2, "NoRestriction": 1}
            )
            self._assert_gpr(2, INITIAL_VALUE, "HLV.D")

            self._load_gpr(1, STORE_GVA)
            self._load_gpr(3, STORED_VALUE)
            self.genInstruction(
                "HSV.D##RISCV", {"rs1": 1, "rs2": 3, "NoRestriction": 1}
            )
            self.genInstruction(
                "HLV.D##RISCV", {"rs1": 1, "rd": 4, "NoRestriction": 1}
            )
            self._assert_gpr(4, STORED_VALUE, "HSV.D followed by HLV.D")
            self._load_gpr(6, STORE_SPA)
            self.genInstruction(
                "LD##RISCV",
                {"rd": 7, "rs1": 6, "simm12": 0, "NoRestriction": 1},
            )
            self._assert_gpr(7, STORED_VALUE, "HSV.D physical-memory result")

            self._load_gpr(1, X_GVA)
            self.genInstruction(
                "HLVX.WU##RISCV", {"rs1": 1, "rd": 5, "NoRestriction": 1}
            )
            self._assert_gpr(5, EXEC_WORD, "HLVX.WU on execute-only VS page")

            self.genInstruction(
                "CSRRS#register#RISCV",
                {"rd": 6, "rs1": 0, "csr": 0x645, "NoRestriction": 1},
            )
            self._assert_gpr(6, 0x4, "hvip name mapping")

            self.notice("HYPERVISOR ACCESS MATRIX: PASS")
        finally:
            ptg.destroy()

    def _load_gpr(self, register_index, value):
        LoadGPR64(self.genThread).load(register_index, value)

    def _assert_gpr(self, register_index, expected, operation):
        actual, valid = self.readRegister(f"x{register_index}")
        if not valid or actual != expected:
            self.error(
                f"{operation} failed: x{register_index}=0x{actual:016X}, "
                f"expected=0x{expected:016X}"
            )


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
