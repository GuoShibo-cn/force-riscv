from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence

class MainSequence(Sequence):
    def generate(self, **kargs):
        self.genInstruction("HFENCE.VVMA##RISCV")
        self.genInstruction("ADDI##RISCV")

MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
