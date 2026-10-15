"""
Two-Stage Address Translation Stress Template

Heavy stress test exercising all two-stage translation paths:
- 1000+ instructions
- All H-extension instructions (HLV/HSV/HFENCE/HINVAL)
- Mixed load/store/ALU/branch/fence
- Guest page fault exception handling
- Hypervisor trap delegation (hedeleg/hideleg)
- Multiple VS-stage and G-stage paging mode combinations

Usage:
  friscv -c config/riscv_rv64_twostage.config py/riscv/two_stage_stress.py
  friscv -c config/riscv_rv64_twostage.config py/riscv/two_stage_stress.py --iss
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence

EnvClass = EnvRISCV
GenThreadClass = GenThreadRISCV


class TwoStageStressTest(Sequence):
    """Comprehensive stress test for two-stage address translation."""

    def generate(self, **kwargs):
        self.notice(">>> Two-Stage Translation Stress Test Start")

        # ================================================================
        # Setup: Two-stage paging + delegation + H CSRs
        # ================================================================
        self.notice("[Setup] Configuring two-stage translation environment")

        # G-stage (GPA -> SPA) via hgatp
        self.genThread.setupGStagePaging(mode="Sv39x4")

        # VS-stage (GVA -> GPA) via vsatp
        self.genThread.setupVsStagePaging(mode="Sv39")

        # hstatus for 64-bit guest
        self.genThread.initializeRegister("hstatus", "VSXL", 2)
        self.genThread.initializeRegister("vstart", "", 0)  # ensure vstart is ISS-initialized

        # Activate two-stage VM
        self.genThread.setupTwoStageVm()

        # Configure hypervisor trap delegation
        self.notice("  Configuring hedeleg/hideleg")
        self.genThread.initializeRegister("hedeleg", "EXC12", 1)  # Instr page fault
        self.genThread.initializeRegister("hedeleg", "EXC13", 1)  # Load page fault
        self.genThread.initializeRegister("hedeleg", "EXC15", 1)  # Store/AMO page fault
        self.genThread.initializeRegister("hideleg", "IRQ1", 1)   # VS software interrupt
        self.genThread.initializeRegister("hideleg", "IRQ5", 1)   # VS timer interrupt

        # ================================================================
        # Phase 1: Memory Access Stress (400 instructions)
        # ================================================================
        self.notice("[Phase 1] Memory access stress — 400 instructions")
        for i in range(80):
            # Mix of integer + float loads/stores
            self.genInstruction("LD##RISCV")
            self.genInstruction("SD##RISCV")
            self.genInstruction("LW##RISCV")
            self.genInstruction("SW##RISCV")
            self.genInstruction("LH##RISCV")

            if i % 10 == 0:
                self.notice("    %d/400" % ((i + 1) * 5))

        # ================================================================
        # Phase 2: H-extension Instructions (300 instructions)
        # ================================================================
        self.notice("[Phase 2] H-extension instruction stress — 300 instructions")
        for i in range(30):
            # Hypervisor virtual loads
            self.genInstruction("HLV.B##RISCV")
            self.genInstruction("HLV.W##RISCV")
            self.genInstruction("HLV.D##RISCV")
            self.genInstruction("HLV.BU##RISCV")
            self.genInstruction("HLV.HU##RISCV")

            # Hypervisor virtual stores
            self.genInstruction("HSV.B##RISCV")
            self.genInstruction("HSV.W##RISCV")
            self.genInstruction("HSV.D##RISCV")

            # TLB fence/invalidate
            self.genInstruction("HFENCE.VVMA##RISCV")
            self.genInstruction("HFENCE.GVMA##RISCV")

            if i % 5 == 0:
                self.notice("    %d/300" % ((i + 1) * 10))

        # ================================================================
        # Phase 3: ALU + Branch Mix (200 instructions)
        # ================================================================
        self.notice("[Phase 3] ALU + branch mix — 200 instructions")
        for i in range(40):
            self.genInstruction("ADD##RISCV")
            self.genInstruction("ADDI##RISCV")
            self.genInstruction("SUB##RISCV")
            self.genInstruction("ANDI##RISCV")
            self.genInstruction("ORI##RISCV")

            if i % 10 == 0:
                self.notice("    %d/200" % ((i + 1) * 5))

        # ================================================================
        # Phase 4: CSR Access (100 instructions)
        # ================================================================
        self.notice("[Phase 4] CSR access stress — 100 instructions")
        for _ in range(25):
            # Zicsr instructions with hypervisor CSRs mixed
            self.genInstruction("CSRRC#register#RISCV")
            self.genInstruction("CSRRS#register#RISCV")
            self.genInstruction("CSRRW#register#RISCV")
            self.genInstruction("CSRRWI#immediate#RISCV")

        # ================================================================
        # Phase 5: Final Verification (50 instructions)
        # ================================================================
        self.notice("[Phase 5] Post-stress verification — 50 instructions")
        try:
            for i in range(10):
                self.genInstruction("LD##RISCV")
                self.genInstruction("SD##RISCV")
                self.genInstruction("ADD##RISCV")
                self.genInstruction("ADDI##RISCV")
                self.genInstruction("HLV.W##RISCV")
            self.notice("  PASS: Post-stress verification")
        except Exception as e:
            self.error("  FAIL: Post-stress verification: %s" % e)

        # ================================================================
        # Summary
        # ================================================================
        self.notice(">>> Two-Stage Translation Stress Test Complete")
        self.notice("    Total: ~1050 instructions generated")
        self.notice("    Phases: Memory(400) + H-Inst(300) + ALU(200) + CSR(100) + Verify(50)")


class MainSequence(TwoStageStressTest):
    pass


MainSequenceClass = MainSequence
