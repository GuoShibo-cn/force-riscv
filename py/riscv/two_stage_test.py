"""
Two-Stage Address Translation Test

Tests the RISC-V H-extension two-stage address translation:
  GVA -> GPA (VS-stage, vsatp, Sv39) -> HPA (G-stage, hgatp, Sv39x4)
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence


class MainSequence(Sequence):
    """Main test sequence for two-stage address translation."""

    def generate(self, **kargs):
        print("\n" + "=" * 70)
        print("Two-Stage Address Translation Test")
        print("GVA -> GPA (VS-stage) -> HPA (G-stage)")
        print("=" * 70)

        # Step 1: Setup G-stage (GPA -> HPA)
        print("\n[1] Setting up G-stage paging (Sv39x4)...")
        self.genThread.setupGStagePaging(mode="Sv39x4")
        print("    hgatp.MODE = Sv39x4")

        # Step 2: Setup VS-stage (GVA -> GPA)
        print("\n[2] Setting up VS-stage paging (Sv39)...")
        self.genThread.setupVsStagePaging(mode="Sv39")
        print("    vsatp.MODE = Sv39")

        # Step 3: Configure hstatus for 64-bit guest
        print("\n[3] Configuring hstatus.VSXL = 2 (64-bit guest)...")
        try:
            self.genThread.initializeRegister("hstatus", "VSXL", 2)
            print("    hstatus.VSXL configured")
        except Exception as e:
            print("    hstatus.VSXL skipped:", e)

        # Step 4: Trigger VM update (activates two-stage translation chain
        #         on FORCE side when regime becomes VS/HS)
        print("\n[4] Triggering VM update for two-stage setup...")
        self.genThread.setupTwoStageVm()
        print("    VM update triggered")

        # Step 5: Generate memory access instructions
        print("\n[5] Generating memory access instructions...")
        for i in range(20):
            self.genInstruction("LD##RISCV")
            self.genInstruction("SD##RISCV")
            self.genInstruction("ADD##RISCV")
        print("    60 instructions generated")

        print("\n" + "=" * 70)
        print("Two-Stage Translation Test Complete")
        print("=" * 70 + "\n")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
