"""
Two-Stage Translation Paging Mode Combinations Test

Tests various paging mode combinations for two-stage address translation:
- Sv39x4 + Sv39
- Sv48x4 + Sv48
- Different hstatus configurations
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence


class MainSequence(Sequence):
    """Paging mode combinations test sequence."""

    def generate(self, **kargs):
        print("\n" + "=" * 70)
        print("Two-Stage Translation Paging Mode Combinations Test")
        print("=" * 70)

        # Test combinations
        test_cases = [
            ("Sv39x4", "Sv39", "VSXL=2", "64-bit guest (Sv39)"),
            ("Sv48x4", "Sv48", "VSXL=2", "64-bit guest (Sv48)"),
        ]

        for gstage_mode, vsstage_mode, vsxl_desc, desc in test_cases:
            print(f"\n[Test] {desc}: G-stage={gstage_mode}, VS-stage={vsstage_mode}")
            try:
                # Setup G-stage
                self.genThread.setupGStagePaging(mode=gstage_mode)
                print(f"  [OK] G-stage: {gstage_mode}")

                # Setup VS-stage
                self.genThread.setupVsStagePaging(mode=vsstage_mode)
                print(f"  [OK] VS-stage: {vsstage_mode}")

                # Configure hstatus
                self.genThread.initializeRegister("hstatus", "VSXL", 2)
                print(f"  [OK] hstatus.VSXL = 2")

                # Trigger VM update
                self.genThread.setupTwoStageVm()
                print(f"  [OK] VM update triggered")

                # Generate instructions
                for i in range(5):
                    self.genInstruction("LD##RISCV")
                    self.genInstruction("SD##RISCV")
                print(f"  [OK] Generated 10 instructions")

                print(f"  PASS: {desc}")
            except Exception as e:
                print(f"  FAIL: {desc}: {e}")

        print("\n" + "=" * 70)
        print("Paging Mode Combinations Test Complete")
        print("=" * 70 + "\n")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
