from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.Utils import LoadGPR64
import struct

G_ROOT_PA = 0x80200000


class MainSequence(Sequence):
    def generate(self, **kargs):
        g_root = bytearray(4096)
        struct.pack_into('<Q', g_root, 2 * 8, 0xDEADBEEFCAFEBABE)

        self.genThread.writePhysicalMemory(G_ROOT_PA, bytes(g_root), 0)

        load_gpr = LoadGPR64(self.genThread)
        load_gpr.load(1, G_ROOT_PA + 16)
        self.genInstruction("LD##RISCV", {"rd": 2, "rs1": 1, "NoRestriction": 1})
        self.genInstruction("ADD##RISCV")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
