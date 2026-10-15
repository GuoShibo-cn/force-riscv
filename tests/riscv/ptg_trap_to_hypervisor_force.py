"""Test hedeleg/hideleg CSR delegation configuration."""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("Phase 3.6 Hypervisor Delegation CSR Test")
        self.notice("=" * 60)

        self.initializeRegister("hedeleg", 0)
        self.writeRegister("hedeleg", 0xFFFF)
        val, _ = self.readRegister("hedeleg", "")
        self.notice(f"hedeleg = 0x{val:X}")

        self.initializeRegister("hideleg", 0)
        self.writeRegister("hideleg", 0x444)  # VS SWI + Timer + External
        val2, _ = self.readRegister("hideleg", "")
        self.notice(f"hideleg = 0x{val2:X}")

        for _ in range(5):
            self.genInstruction("ADDI##RISCV")

        self.notice("Delegation CSR test complete")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
