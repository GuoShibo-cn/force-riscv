from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.Utils import LoadGPR64
import struct

SENTINEL = 0xDEADBEEFCAFE1234
GPA_TARGET = 0x80000000
SPA_TARGET = 0x80600000
G_ROOT_PA = 0x80200000


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("G-stage only: HLV.D reads sentinel via Sv39x4")
        self.notice("=" * 60)

        pte_valid = 0xCF

        g_root = bytearray(4096)
        g_mid = bytearray(4096)
        G_MID_PA = G_ROOT_PA + 0x1000

        gpa_idx2 = (GPA_TARGET >> 30) & 0x7FF
        g_mid_ppn = G_MID_PA >> 12
        g_root_pte = (g_mid_ppn << 10) | 0x01
        struct.pack_into("<Q", g_root, gpa_idx2 * 8, g_root_pte)

        gpa_idx1 = (GPA_TARGET >> 21) & 0x1FF
        spa_ppn = SPA_TARGET >> 12
        g_leaf_pte = (spa_ppn << 10) | pte_valid
        struct.pack_into("<Q", g_mid, gpa_idx1 * 8, g_leaf_pte)

        self.genThread.writePhysicalMemory(G_ROOT_PA, bytes(g_root), 0)
        self.genThread.writePhysicalMemory(G_MID_PA, bytes(g_mid), 0)

        sentinel_bytes = struct.pack("<Q", SENTINEL)
        self.genThread.writePhysicalMemory(SPA_TARGET, sentinel_bytes, 0)

        self.notice(f"  G root PA=0x{G_ROOT_PA:X}, mid PA=0x{G_MID_PA:X}")
        self.notice(f"  root PTE[{gpa_idx2}]=0x{g_root_pte:016X}")
        self.notice(f"  mid PTE[{gpa_idx1}]=0x{g_leaf_pte:016X}")
        self.notice(f"  sentinel PA=0x{SPA_TARGET:X}")
        self.notice(f"  GPA 0x{GPA_TARGET:X} -> SPA 0x{SPA_TARGET:X}")

        hgatp_val = (8 << 60) | (G_ROOT_PA >> 12)
        self.notice(f"  hgatp=0x{hgatp_val:016X}")

        load_gpr_hg = LoadGPR64(self.genThread)
        load_gpr_hg.load(5, hgatp_val)
        self.genInstruction("CSRRW#register#RISCV", {
            "rd": 0, "rs1": 5, "csr": 0x680, "NoRestriction": 1,
        })

        self.genInstruction("CSRRW#register#RISCV", {
            "rd": 0, "rs1": 0, "csr": 0x280, "NoRestriction": 1,
        })

        hstatus_val = 0x80
        load_gpr_hs = LoadGPR64(self.genThread)
        load_gpr_hs.load(7, hstatus_val)
        self.genInstruction("CSRRW#register#RISCV", {
            "rd": 0, "rs1": 7, "csr": 0x600, "NoRestriction": 1,
        })

        load_gpr = LoadGPR64(self.genThread)
        load_gpr.load(1, GPA_TARGET)
        self.genInstruction("HLV.D##RISCV", {"rs1": 1})
        self.genInstruction("ADD##RISCV")

        self.notice("Done")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
