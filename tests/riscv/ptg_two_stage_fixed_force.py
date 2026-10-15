import struct

from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.Utils import LoadGPR64
from riscv.paging.PtgBackend import (
    PTG_MAPPING_KIND_GPA,
    PTG_MAPPING_KIND_SPA,
    PTG_MAPPING_VALID_CURRENT,
    PTG_MAPPING_VALID_MATCH,
    PtgBackend,
)


SENTINEL = 0xDEADBEEFCAFE1234
GIGAPAGE_SENTINEL = 0x0123456789ABCDEF
GVA_TARGET = 0x80200000
GPA_TARGET = 0x80200000
SPA_TARGET = 0xA0200000
MAPPING_SIZE = 0x200000
MAPPING_LEAF_LEVEL = 1
GIGAPAGE_GVA = 0x40000000
GIGAPAGE_GPA = 0xC0000000
GIGAPAGE_SPA = 0x100000000
GIGAPAGE_OFFSET = 0x123450
GIGAPAGE_SIZE = 0x40000000
GIGAPAGE_LEAF_LEVEL = 2
BOUNDARY_GVA = 0x20000000
BOUNDARY_GPA = 0x60000000
BOUNDARY_SPA = 0x140000000
BOUNDARY_OFFSET = 0xFFC
BOUNDARY_SENTINEL = 0xA5B6C7D8E9FA0B1C
MIXED_4K_2M_GVA = 0x21000000
MIXED_4K_2M_GPA = 0x62000000
MIXED_4K_2M_SPA = 0x142000000
MIXED_4K_2M_OFFSET = 0x678
MIXED_4K_2M_SENTINEL = 0xFEDCBA9876543210
MIXED_2M_4K_GVA = 0x21200000
MIXED_2M_4K_GPA = 0x62200000
MIXED_2M_4K_SPA = 0x144000000
MIXED_2M_4K_OFFSET = 0x1230
MIXED_2M_4K_SENTINEL = 0x0F1E2D3C4B5A6978


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("PTG two-stage end-to-end translation test")
        self.notice("=" * 60)

        ptg = PtgBackend()
        try:
            ctx = ptg.create_two_stage_context(
                vs_mode="Sv39",
                gs_mode="Sv39x4",
                asid=1,
                vmid=1,
                gpa_base=0x80000000,
                gpa_limit=0x100000000,
                pa_base=0xA0000000,
                pa_limit=0x180000000,
            )

            # Keep the data mapping away from PTG's page-table allocation ranges.
            # VS uses a supervisor page; G-stage leaves require U=1.
            vs_pte_perms = 0x67
            g_pte_perms = 0x77
            ptg.handle.add_mapping(
                ctx,
                "VS",
                GVA_TARGET,
                GPA_TARGET,
                MAPPING_SIZE,
                MAPPING_LEAF_LEVEL,
                vs_pte_perms,
            )
            ptg.handle.add_mapping(
                ctx,
                "G",
                GPA_TARGET,
                SPA_TARGET,
                MAPPING_SIZE,
                MAPPING_LEAF_LEVEL,
                g_pte_perms,
            )
            ptg.handle.add_mapping(
                ctx,
                "VS",
                GIGAPAGE_GVA,
                GIGAPAGE_GPA,
                GIGAPAGE_SIZE,
                GIGAPAGE_LEAF_LEVEL,
                vs_pte_perms,
            )
            ptg.handle.add_mapping(
                ctx,
                "G",
                GIGAPAGE_GPA,
                GIGAPAGE_SPA,
                GIGAPAGE_SIZE,
                GIGAPAGE_LEAF_LEVEL,
                g_pte_perms,
            )
            for page_offset in (0, 0x1000):
                ptg.handle.add_mapping(
                    ctx,
                    "VS",
                    BOUNDARY_GVA + page_offset,
                    BOUNDARY_GPA + page_offset,
                    0x1000,
                    0,
                    vs_pte_perms,
                )
                ptg.handle.add_mapping(
                    ctx,
                    "G",
                    BOUNDARY_GPA + page_offset,
                    BOUNDARY_SPA + page_offset,
                    0x1000,
                    0,
                    g_pte_perms,
                )
            ptg.handle.add_mapping(
                ctx,
                "VS",
                MIXED_4K_2M_GVA,
                MIXED_4K_2M_GPA,
                0x1000,
                0,
                vs_pte_perms,
            )
            ptg.handle.add_mapping(
                ctx,
                "G",
                MIXED_4K_2M_GPA,
                MIXED_4K_2M_SPA,
                0x200000,
                1,
                g_pte_perms,
            )
            ptg.handle.add_mapping(
                ctx,
                "VS",
                MIXED_2M_4K_GVA,
                MIXED_2M_4K_GPA,
                0x200000,
                1,
                vs_pte_perms,
            )
            ptg.handle.add_mapping(
                ctx,
                "G",
                MIXED_2M_4K_GPA + 0x1000,
                MIXED_2M_4K_SPA,
                0x1000,
                0,
                g_pte_perms,
            )

            translated_pa, fault_code, fault_level = ptg.handle.translate_sequential(
                ctx, GVA_TARGET, 0
            )
            if translated_pa != SPA_TARGET or fault_code != 0:
                self.error(
                    "PTG translation failed: "
                    f"PA=0x{translated_pa:X}, fault={fault_code}, level={fault_level}"
                )

            gigapage_pa, fault_code, fault_level = ptg.handle.translate_sequential(
                ctx, GIGAPAGE_GVA + GIGAPAGE_OFFSET, 0
            )
            expected_gigapage_pa = GIGAPAGE_SPA + GIGAPAGE_OFFSET
            if gigapage_pa != expected_gigapage_pa or fault_code != 0:
                self.error(
                    "PTG gigapage translation failed: "
                    f"PA=0x{gigapage_pa:X}, fault={fault_code}, level={fault_level}"
                )

            translation_checks = (
                (
                    BOUNDARY_GVA + BOUNDARY_OFFSET,
                    BOUNDARY_SPA + BOUNDARY_OFFSET,
                    "cross-page start",
                ),
                (
                    BOUNDARY_GVA + BOUNDARY_OFFSET + 7,
                    BOUNDARY_SPA + BOUNDARY_OFFSET + 7,
                    "cross-page end",
                ),
                (
                    MIXED_4K_2M_GVA + MIXED_4K_2M_OFFSET,
                    MIXED_4K_2M_SPA + MIXED_4K_2M_OFFSET,
                    "VS 4 KiB/G 2 MiB",
                ),
                (
                    MIXED_2M_4K_GVA + MIXED_2M_4K_OFFSET,
                    MIXED_2M_4K_SPA + (MIXED_2M_4K_OFFSET - 0x1000),
                    "VS 2 MiB/G 4 KiB",
                ),
            )
            for virtual_address, expected_pa, description in translation_checks:
                translated_pa, fault_code, fault_level = (
                    ptg.handle.translate_sequential(ctx, virtual_address, 0)
                )
                if translated_pa != expected_pa or fault_code != 0:
                    self.error(
                        f"PTG {description} translation failed: "
                        f"PA=0x{translated_pa:X}, fault={fault_code}, "
                        f"level={fault_level}"
                    )

            validation = ptg.validate(ctx)
            if not validation.all_ok:
                self.error(
                    "PTG validation failed: "
                    f"invalid addresses={validation.invalid_addr_nodes}, "
                    f"invalid PTEs={validation.invalid_pte_count}, "
                    f"orphans={validation.orphan_nodes}, "
                    f"GPA overlaps={validation.gpa_overlap_count}, "
                    f"unreachable GPAs={validation.gpa_unreachable}, "
                    f"missing flags={validation.leaf_missing_flags}"
                )

            # These are structural observations; the HLV instructions below are the access oracle.
            required = PTG_MAPPING_VALID_CURRENT | PTG_MAPPING_VALID_MATCH
            for gva, gpa, spa in (
                (GVA_TARGET, GPA_TARGET, SPA_TARGET),
                (GIGAPAGE_GVA + GIGAPAGE_OFFSET, GIGAPAGE_GPA + GIGAPAGE_OFFSET,
                 expected_gigapage_pa),
            ):
                for stage, address, expected, kind in (
                    ("VS", gva, gpa, PTG_MAPPING_KIND_GPA),
                    ("G", gpa, spa, PTG_MAPPING_KIND_SPA),
                ):
                    records = ptg.query_mappings(ctx, stage, address)
                    if (len(records) != 1 or records[0].valid_fields & required != required
                            or records[0].matched_pa != expected or records[0].output_kind != kind):
                        self.error(f"PTG Query v1 {stage} metadata mismatch for 0x{address:X}")
            with ptg.capture_export_layout(ctx, "VS") as vs_layout:
                with ptg.capture_export_layout(ctx, "G") as g_layout:
                    ptg.load_export_layouts((vs_layout, g_layout), self.genThread)
            self.notice("PTG STRICT EXPORT V1: normal VS/G snapshot loaded")
            self.genThread.writePhysicalMemory(SPA_TARGET, struct.pack("<Q", SENTINEL), 0)
            self.genThread.writePhysicalMemory(
                expected_gigapage_pa, struct.pack("<Q", GIGAPAGE_SENTINEL), 0
            )
            self.genThread.writePhysicalMemory(
                BOUNDARY_SPA + BOUNDARY_OFFSET,
                struct.pack("<Q", BOUNDARY_SENTINEL),
                0,
            )
            self.genThread.writePhysicalMemory(
                MIXED_4K_2M_SPA + MIXED_4K_2M_OFFSET,
                struct.pack("<Q", MIXED_4K_2M_SENTINEL),
                0,
            )
            self.genThread.writePhysicalMemory(
                MIXED_2M_4K_SPA + (MIXED_2M_4K_OFFSET - 0x1000),
                struct.pack("<Q", MIXED_2M_4K_SENTINEL),
                0,
            )

            self.genThread.setupPtgCSRs(
                ptg_handle=ptg.handle,
                ctx_id=ctx,
                vs_mode="Sv39",
                g_mode="Sv39x4",
            )

            # HU=1 permits HLV from M-mode; SPVP=1 selects VS supervisor mode.
            LoadGPR64(self.genThread).load(8, 0x300)
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

            self.notice(
                f"PTG mapping: GVA 0x{GVA_TARGET:X} -> GPA 0x{GPA_TARGET:X} "
                f"-> SPA 0x{SPA_TARGET:X}"
            )
            LoadGPR64(self.genThread).load(1, GVA_TARGET)
            self.genInstruction(
                "HLV.D##RISCV", {"rs1": 1, "rd": 2, "NoRestriction": 1}
            )

            x2_val, valid = self.readRegister("x2")
            if not valid or x2_val != SENTINEL:
                self.error(
                    f"HLV.D returned 0x{x2_val:016X}, expected 0x{SENTINEL:016X}"
                )

            self.notice(f"SUCCESS: x2 = 0x{x2_val:016X}")

            LoadGPR64(self.genThread).load(1, GIGAPAGE_GVA + GIGAPAGE_OFFSET)
            self.genInstruction(
                "HLV.D##RISCV", {"rs1": 1, "rd": 3, "NoRestriction": 1}
            )
            x3_val, valid = self.readRegister("x3")
            if not valid or x3_val != GIGAPAGE_SENTINEL:
                self.error(
                    "1 GiB HLV.D returned "
                    f"0x{x3_val:016X}, expected 0x{GIGAPAGE_SENTINEL:016X}"
                )

            self.notice(f"SUCCESS: 1 GiB x3 = 0x{x3_val:016X}")

            access_checks = (
                (
                    BOUNDARY_GVA + BOUNDARY_OFFSET,
                    4,
                    BOUNDARY_SENTINEL,
                    "cross-page HLV.D",
                ),
                (
                    MIXED_4K_2M_GVA + MIXED_4K_2M_OFFSET,
                    5,
                    MIXED_4K_2M_SENTINEL,
                    "VS 4 KiB/G 2 MiB HLV.D",
                ),
                (
                    MIXED_2M_4K_GVA + MIXED_2M_4K_OFFSET,
                    6,
                    MIXED_2M_4K_SENTINEL,
                    "VS 2 MiB/G 4 KiB HLV.D",
                ),
            )
            for virtual_address, register_index, expected_value, description in access_checks:
                LoadGPR64(self.genThread).load(1, virtual_address)
                self.genInstruction(
                    "HLV.D##RISCV",
                    {"rs1": 1, "rd": register_index, "NoRestriction": 1},
                )
                actual_value, valid = self.readRegister(f"x{register_index}")
                if not valid or actual_value != expected_value:
                    self.error(
                        f"{description} returned 0x{actual_value:016X}, "
                        f"expected 0x{expected_value:016X}"
                    )
                self.notice(
                    f"SUCCESS: {description} x{register_index} = "
                    f"0x{actual_value:016X}"
                )
        finally:
            ptg.destroy()


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
