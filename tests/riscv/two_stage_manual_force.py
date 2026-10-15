from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.Utils import LoadGPR64
import struct

SENTINEL = 0xDEADBEEFCAFE1234
GVA_TARGET = 0x80200000
GPA_TARGET = 0x80200000
SPA_TARGET = 0x80200000

VS_ROOT_PA = 0x80300000


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("HLV.D two-stage walk (VS Sv39, G Bare)")
        self.notice("=" * 60)

        pte_rwad = 0x1F

        vs_root = bytearray(4096)
        gva_idx2 = (GVA_TARGET >> 30) & 0x1FF
        vs_ppn2 = (GPA_TARGET >> 30) & 0x3FFFFFF
        vs_pte = (vs_ppn2 << 28) | pte_rwad
        struct.pack_into("<Q", vs_root, gva_idx2 * 8, vs_pte)

        self.genThread.writePhysicalMemory(VS_ROOT_PA, bytes(vs_root), 0)

        sentinel_bytes = struct.pack("<Q", SENTINEL)
        self.genThread.writePhysicalMemory(SPA_TARGET, sentinel_bytes, 0)

        self.notice(f"  VS root PA=0x{VS_ROOT_PA:X} [{gva_idx2}]=0x{vs_pte:016X}")
        self.notice(f"  sentinel PA=0x{SPA_TARGET:X}=0x{SENTINEL:016X}")

        vsatp_val = (8 << 60) | (VS_ROOT_PA >> 12)
        self.notice(f"  vsatp=0x{vsatp_val:016X} hgatp=0 (Bare)")

        load_gpr = LoadGPR64(self.genThread)
        load_gpr.load(6, vsatp_val)
        self.genInstruction("CSRRW#register#RISCV", {
            "rd": 0, "rs1": 6, "csr": 0x280, "NoRestriction": 1,
        })

        self.genInstruction("CSRRW#register#RISCV", {
            "rd": 0, "rs1": 0, "csr": 0x680, "NoRestriction": 1,
        })

        load_gpr3 = LoadGPR64(self.genThread)
        load_gpr3.load(1, GVA_TARGET)
        self.genInstruction("HLV.D##RISCV", {"rs1": 1})
        self.genInstruction("ADD##RISCV")

        self.notice("Done")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
