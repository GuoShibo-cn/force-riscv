from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend
from riscv.Utils import LoadGPR64
import struct

SENTINEL = 0xDEADBEEFCAFE1234
GVA_TARGET = 0x90000000
GPA_TARGET = 0x90000000
SPA_TARGET = 0x90000000

VS_ROOT_PA = 0x90600000
G_ROOT_PA = 0x90800000


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("Manual two-stage walk: HLV.D reads sentinel")
        self.notice("=" * 60)

        pte_valid = 0x5F  # D=1, A=1, U=1, X=1, W=1, R=1, V=1 (bits 7,6,4,3,2,1,0)
        pte_table = 0x01

        vs_root = bytearray(4096)
        gva_idx2 = (GVA_TARGET >> 30) & 0x1FF
        vs_ppn2 = (GPA_TARGET >> 30) & 0x3FFFFFF
        vs_pte = (vs_ppn2 << 28) | pte_valid
        struct.pack_into("<Q", vs_root, gva_idx2 * 8, vs_pte)

        g_root = bytearray(4096)
        g_mid = bytearray(4096)
        G_MID_PA = G_ROOT_PA + 0x1000

        g_root_idx2 = (GPA_TARGET >> 30) & 0x1FF
        g_mid_ppn = G_MID_PA >> 12
        g_root_pte = (g_mid_ppn << 10) | pte_table
        struct.pack_into("<Q", g_root, g_root_idx2 * 8, g_root_pte)

        g_vs_root_idx2 = (VS_ROOT_PA >> 30) & 0x1FF
        if g_vs_root_idx2 != g_root_idx2:
            g_vs_mid_ppn = G_MID_PA >> 12
            g_vs_root_pte = (g_vs_mid_ppn << 10) | pte_table
            struct.pack_into("<Q", g_root, g_vs_root_idx2 * 8, g_vs_root_pte)

        g_data_idx1 = (GPA_TARGET >> 21) & 0x1FF
        g_data_ppn1 = (SPA_TARGET >> 21) & 0x1FF
        g_data_ppn2 = (SPA_TARGET >> 30) & 0x3FFFFFF
        g_data_pte = (g_data_ppn2 << 28) | (g_data_ppn1 << 19) | pte_valid
        struct.pack_into("<Q", g_mid, g_data_idx1 * 8, g_data_pte)

        g_vs_idx1 = (VS_ROOT_PA >> 21) & 0x1FF
        g_vs_ppn1 = (VS_ROOT_PA >> 21) & 0x1FF
        g_vs_ppn2 = (VS_ROOT_PA >> 30) & 0x3FFFFFF
        g_vs_pte = (g_vs_ppn2 << 28) | (g_vs_ppn1 << 19) | pte_valid
        struct.pack_into("<Q", g_mid, g_vs_idx1 * 8, g_vs_pte)

        g_vs_idx1 = (VS_ROOT_PA >> 21) & 0x1FF
        g_vs_ppn1 = (VS_ROOT_PA >> 21) & 0x1FF
        g_vs_ppn2 = (VS_ROOT_PA >> 30) & 0x3FFFFFF
        g_vs_pte = (g_vs_ppn2 << 28) | (g_vs_ppn1 << 19) | pte_valid
        struct.pack_into("<Q", g_mid, g_vs_idx1 * 8, g_vs_pte)

        self.genThread.writePhysicalMemory(VS_ROOT_PA, bytes(vs_root), 0)
        self.genThread.writePhysicalMemory(G_ROOT_PA, bytes(g_root), 0)
        self.genThread.writePhysicalMemory(G_MID_PA, bytes(g_mid), 0)

        sentinel_bytes = struct.pack("<Q", SENTINEL)
        self.genThread.writePhysicalMemory(SPA_TARGET, sentinel_bytes, 0)

        self.notice(f"  VS root PA=0x{VS_ROOT_PA:X}, PTE[{gva_idx2}]=0x{vs_pte:016X} (1GB superpage)")
        self.notice(f"  G root PA=0x{G_ROOT_PA:X}, mid PA=0x{G_MID_PA:X}")
        self.notice(f"    root PTE[{g_root_idx2}]=0x{g_root_pte:016X} (table -> mid)")
        self.notice(f"    mid data PTE[{g_data_idx1}]=0x{g_data_pte:016X} (2MB: GPA 0x{GPA_TARGET:X} -> SPA 0x{SPA_TARGET:X})")
        self.notice(f"    mid vs PTE[{g_vs_idx1}]=0x{g_vs_pte:016X} (2MB: GPA 0x{VS_ROOT_PA:X} -> PA 0x{VS_ROOT_PA:X})")
        self.notice(f"  sentinel PA=0x{SPA_TARGET:X}=0x{SENTINEL:016X}")
        self.notice(f"  GVA 0x{GVA_TARGET:X} -> GPA 0x{GPA_TARGET:X} -> SPA 0x{SPA_TARGET:X}")

        vsatp_val = (8 << 60) | (VS_ROOT_PA >> 12)
        hgatp_val = (8 << 60) | (G_ROOT_PA >> 12)
        self.notice(f"  vsatp=0x{vsatp_val:016X} hgatp=0x{hgatp_val:016X}")

        self.genThread.initializeRegister("x6", "", vsatp_val)
        self.genThread.initializeRegister("x7", "", hgatp_val)
        self.genThread.initializeRegister("x8", "", 0x80)

        self.genInstruction("CSRRW#register#RISCV", {"rd": 0, "rs1": 6, "csr": 0x280, "NoRestriction": 1})
        self.genInstruction("CSRRW#register#RISCV", {"rd": 0, "rs1": 7, "csr": 0x680, "NoRestriction": 1})
        self.genInstruction("CSRRW#register#RISCV", {"rd": 0, "rs1": 8, "csr": 0x600, "NoRestriction": 1})

        self.genThread.initializeRegister("x1", "", GVA_TARGET)
        self.genInstruction("HLV.D##RISCV", {"rs1": 1, "NoRestriction": 1})
        self.genInstruction("ADD##RISCV")

        self.notice("Done")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
