"""
Two-Stage Address Translation Example

This template demonstrates the use of two-stage address translation
(GVA -> GPA -> SPA) in RISC-V Hypervisor Extension.

Two-stage translation is used when the H-extension is enabled:
  Stage 1 (VS-stage): Guest Virtual Address (GVA) -> Guest Physical Address (GPA)
  Stage 2 (G-stage):  Guest Physical Address (GPA) -> System Physical Address (SPA)

Usage:
  Run with the riscv_rv64_twostage.config configuration file to enable
  both Sv39 (VS-stage) and Sv39x4 (G-stage) page table support.
"""

from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence

EnvClass = EnvRISCV
GenThreadClass = GenThreadRISCV


class TwoStageSetup(Sequence):
    """Setup two-stage translation environment.

    Configures both VS-stage (GVA->GPA) and G-stage (GPA->SPA) page tables.
    This sequence should be run at the beginning of a test that requires
    hypervisor-mode address translation.
    """

    def generate(self, **kwargs):
        # Configure VS-stage paging (GVA -> GPA)
        self.genThread.setupVsStagePaging(mode="Sv39")

        # Configure G-stage paging (GPA -> SPA)
        self.genThread.setupGStagePaging(mode="Sv39x4")

        # Generate some hypervisor instructions to exercise two-stage translation
        for _ in range(50):
            self.genInstruction("HFENCE_VVMA##RISCV")
            self.genInstruction("HLV_B##RISCV")
            self.genInstruction("HSV_B##RISCV")


class MainTest(Sequence):
    """Main test sequence with two-stage translation.

    Generates regular instructions that will go through the two-stage
    address translation pipeline (GVA -> GPA -> SPA).
    """

    def generate(self, **kwargs):
        # Generate regular instructions with two-stage translation active
        for _ in range(100):
            self.genInstruction("ADDI##RISCV")
            self.genInstruction("LD##RISCV")
            self.genInstruction("SD##RISCV")
            self.genInstruction("ADD##RISCV")
            self.genInstruction("SUB##RISCV")


class MainSequence(MainTest):
    pass

# Points to the MainSequence defined in this file
MainSequenceClass = MainSequence
