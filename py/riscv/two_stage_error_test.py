"""
Two-Stage Translation Error Handling Test

Tests error handling and recovery for two-stage address translation:
- Invalid register states
- Missing paging choices
- Recovery from errors
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence


class MainSequence(Sequence):
    """Error handling test sequence for two-stage address translation."""

    def generate(self, **kargs):
        print("\n" + "=" * 70)
        print("Two-Stage Translation Error Handling Test")
        print("=" * 70)

        # Test 1: Setup with minimal configuration
        print("\n[Test 1] Minimal two-stage setup...")
        try:
            # Only set G-stage, not VS-stage
            self.genThread.setupGStagePaging(mode="Sv39x4")
            self.genThread.setupTwoStageVm()
            print("  INFO: Setup with only G-stage (expected: may not establish chain)")
        except Exception as e:
            print(f"  INFO: Exception during minimal setup: {e}")

        # Test 2: Full setup after minimal attempt
        print("\n[Test 2] Full setup after minimal attempt...")
        try:
            self.genThread.setupGStagePaging(mode="Sv39x4")
            self.genThread.setupVsStagePaging(mode="Sv39")
            self.genThread.initializeRegister("hstatus", "VSXL", 2)
            self.genThread.setupTwoStageVm()
            print("  PASS: Full setup succeeded after minimal attempt")
        except Exception as e:
            print(f"  FAIL: Full setup failed: {e}")

        # Test 3: Generate instructions after recovery
        print("\n[Test 3] Generating instructions after recovery...")
        try:
            for i in range(5):
                self.genInstruction("LD##RISCV")
            print("  PASS: Generated 5 instructions after recovery")
        except Exception as e:
            print(f"  FAIL: Instruction generation failed: {e}")

        # Test 4: Different paging mode combinations
        print("\n[Test 4] Testing various paging mode combinations...")
        test_cases = [
            ("Sv39x4", "Sv39", "64-bit guest"),
            ("Sv48x4", "Sv48", "64-bit guest (Sv48)"),
        ]
        for gstage_mode, vsstage_mode, desc in test_cases:
            try:
                self.genThread.setupGStagePaging(mode=gstage_mode)
                self.genThread.setupVsStagePaging(mode=vsstage_mode)
                self.genThread.initializeRegister("hstatus", "VSXL", 2)
                self.genThread.setupTwoStageVm()
                print(f"  PASS: {desc}")
            except Exception as e:
                print(f"  FAIL: {desc}: {e}")

        print("\n" + "=" * 70)
        print("Error Handling Test Complete")
        print("=" * 70 + "\n")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
