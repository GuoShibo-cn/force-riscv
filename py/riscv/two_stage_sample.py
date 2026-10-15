"""
Two-Stage Address Translation Sample Template

Demonstrates RISC-V H-extension two-stage address translation:
  Stage 1 (VS-stage): GVA -> GPA  via vsatp (Sv39)
  Stage 2 (G-stage):  GPA -> SPA  via hgatp (Sv39x4)

Usage:
  # No ISS (generate only):
  friscv -c config/riscv_rv64_twostage.config py/riscv/two_stage_sample.py

  # With ISS (cosim verification):
  friscv -c config/riscv_rv64_twostage.config py/riscv/two_stage_sample.py --iss

Expected output: generated assembly with two-stage page tables,
hypervisor instructions (HLV/HSV/HFENCE), and memory access patterns
that exercise both VS-stage and G-stage translation.
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence

EnvClass = EnvRISCV
GenThreadClass = GenThreadRISCV


class TwoStageTranslationSample(Sequence):
    """Complete two-stage translation walkthrough."""

    def generate(self, **kwargs):
        # ================================================================
        # Phase 1: Two-Stage Paging Setup
        # ================================================================
        self.notice(">>> Phase 1: Two-Stage Paging Setup")

        # 1a. Configure G-stage (GPA -> SPA) via hgatp
        self.notice("  [1a] Configuring G-stage paging: hgatp.MODE = Sv39x4")
        self.genThread.setupGStagePaging(mode="Sv39x4")

        # 1b. Configure VS-stage (GVA -> GPA) via vsatp
        self.notice("  [1b] Configuring VS-stage paging: vsatp.MODE = Sv39")
        self.genThread.setupVsStagePaging(mode="Sv39")

        # 1c. Set hstatus.VSXL to 2 (64-bit guest XLEN)
        self.notice("  [1c] Configuring hstatus.VSXL = 2")
        self.genThread.initializeRegister("hstatus", "VSXL", 2)

        # 1d. Trigger VM update to activate two-stage translation chain
        self.notice("  [1d] Activating two-stage VM chain")
        self.genThread.setupTwoStageVm()

        # ================================================================
        # Phase 2: Basic Memory Access (goes through both stages)
        # ================================================================
        self.notice(">>> Phase 2: Basic Memory Access through two-stage translation")

        for _ in range(20):
            self.genInstruction("LD##RISCV")
            self.genInstruction("SD##RISCV")
            self.genInstruction("ADD##RISCV")

        # ================================================================
        # Phase 3: Hypervisor Instructions (HLV/HSV/HFENCE)
        # ================================================================
        self.notice(">>> Phase 3: Hypervisor Instructions")

        # Hypervisor virtual loads (hlv.b/w/d)
        self.notice("  [3a] Hypervisor Virtual Loads")
        for _ in range(5):
            self.genInstruction("HLV.B##RISCV")
            self.genInstruction("HLV.W##RISCV")
            self.genInstruction("HLV.D##RISCV")

        # Hypervisor virtual stores (hsv.b/w/d)
        self.notice("  [3b] Hypervisor Virtual Stores")
        for _ in range(5):
            self.genInstruction("HSV.B##RISCV")
            self.genInstruction("HSV.W##RISCV")
            self.genInstruction("HSV.D##RISCV")

        # TLB fence instructions
        self.notice("  [3c] Hypervisor TLB Fences")
        for _ in range(3):
            self.genInstruction("HFENCE.VVMA##RISCV")
            self.genInstruction("HFENCE.GVMA##RISCV")

        # ================================================================
        # Phase 4: Hypervisor Trap Delegation
        # ================================================================
        self.notice(">>> Phase 4: Hypervisor Trap Delegation")

        # Delegate page faults to VS-mode via hedeleg
        self.notice("  Configuring hedeleg for page fault delegation")
        self.genThread.initializeRegister("hedeleg", "EXC12", 1)   # Instruction page fault
        self.genThread.initializeRegister("hedeleg", "EXC13", 1)   # Load page fault
        self.genThread.initializeRegister("hedeleg", "EXC15", 1)   # Store/AMO page fault

        # Generate instructions under delegation
        self.notice("  Generating instructions under hedeleg delegation")
        for _ in range(15):
            self.genInstruction("LD##RISCV")
            self.genInstruction("SD##RISCV")

        # ================================================================
        # Phase 5: Final Verification
        # ================================================================
        self.notice(">>> Phase 5: Final Verification")

        for _ in range(10):
            self.genInstruction("ADD##RISCV")
            self.genInstruction("ADDI##RISCV")

        self.notice(">>> Two-Stage Translation Sample Complete")


class MainSequence(TwoStageTranslationSample):
    pass


MainSequenceClass = MainSequence
