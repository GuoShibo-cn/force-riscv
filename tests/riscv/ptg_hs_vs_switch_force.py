from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("Phase 3.7: HS/VS Privilege Chain (CSR-based)")
        self.notice("=" * 60)

        self.initializeRegister("hstatus", 0, "SPV")
        self.initializeRegister("hstatus", 0, "SPVP")

        def read_field(reg, field):
            val, valid = self.readRegister(reg, field)
            if not valid:
                self.notice("  WARNING: %s.%s not readable" % (reg, field))
                return 0
            return val

        self.notice("\n[Step 1] Write hstatus SPV=1, SPVP=1 and read back")
        self.writeRegister("hstatus", 1, "SPV")
        self.writeRegister("hstatus", 1, "SPVP")
        spv = read_field("hstatus", "SPV")
        spvp = read_field("hstatus", "SPVP")
        self.notice("  hstatus.SPV=%s (expect 1) match=%s" % (spv, spv == 1))
        self.notice("  hstatus.SPVP=%s (expect 1) match=%s" % (spvp, spvp == 1))
        self.genInstruction("ADDI##RISCV")

        self.notice("\n[Step 2] Verify hstatus write-back reset")
        self.writeRegister("hstatus", 0, "SPV")
        self.writeRegister("hstatus", 0, "SPVP")
        spv2 = read_field("hstatus", "SPV")
        spvp2 = read_field("hstatus", "SPVP")
        self.notice("  hstatus.SPV=%s (expect 0) match=%s" % (spv2, spv2 == 0))
        self.notice("  hstatus.SPVP=%s (expect 0) match=%s" % (spvp2, spvp2 == 0))
        self.genInstruction("ADDI##RISCV")

        self.notice("\n" + "=" * 60)
        self.notice("Phase 3.7 complete")
        self.notice("=" * 60)


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
