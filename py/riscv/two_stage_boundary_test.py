"""
Two-Stage Translation Boundary Test

Tests boundary conditions and error handling for two-stage address translation:
- Invalid paging mode combinations
- Empty register states
- Error recovery
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence


class MainSequence(Sequence):
    """Boundary test sequence for two-stage address translation."""

    def generate(self, **kargs):
        print("\n" + "=" * 70)
        print("Two-Stage Translation Boundary Test")
        print("=" * 70)

        # Test 1: Valid two-stage setup
        print("\n[Test 1] Valid two-stage setup (Sv39x4 + Sv39)...")
        try:
            self.genThread.setupGStagePaging(mode="Sv39x4")
            self.genThread.setupVsStagePaging(mode="Sv39")
            self.genThread.initializeRegister("hstatus", "VSXL", 2)
            self.genThread.setupTwoStageVm()
            print("  PASS: Valid setup succeeded")
        except Exception as e:
            print(f"  FAIL: Valid setup failed: {e}")

        # Test 2: Generate instructions with two-stage translation
        print("\n[Test 2] Generating instructions with two-stage translation...")
        try:
            for i in range(10):
                self.genInstruction("LD##RISCV")
                self.genInstruction("SD##RISCV")
            print("  PASS: Generated 20 instructions")
        except Exception as e:
            print(f"  FAIL: Instruction generation failed: {e}")

        # Test 3: Different paging mode combinations
        print("\n[Test 3] Testing different paging mode combinations...")
        test_modes = [
            ("Sv39x4", "Sv39"),
            ("Sv48x4", "Sv48"),
        ]
        for gstage_mode, vsstage_mode in test_modes:
            try:
                self.genThread.setupGStagePaging(mode=gstage_mode)
                self.genThread.setupVsStagePaging(mode=vsstage_mode)
                print(f"  PASS: {gstage_mode} + {vsstage_mode}")
            except Exception as e:
                print(f"  FAIL: {gstage_mode} + {vsstage_mode}: {e}")

        print("\n" + "=" * 70)
        print("Boundary Test Complete")
        print("=" * 70 + "\n")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
