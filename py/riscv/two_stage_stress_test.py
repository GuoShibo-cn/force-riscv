"""
Two-Stage Translation Stress Test

Tests system stability with large instruction counts:
- 1000+ instructions
- Multiple instruction types
- Long-running generation
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence


class MainSequence(Sequence):
    """Stress test sequence for two-stage address translation."""

    def generate(self, **kargs):
        print("\n" + "=" * 70)
        print("Two-Stage Translation Stress Test")
        print("=" * 70)

        # Setup two-stage translation
        print("\n[Setup] Configuring two-stage translation...")
        self.genThread.setupGStagePaging(mode="Sv39x4")
        self.genThread.setupVsStagePaging(mode="Sv39")
        self.genThread.initializeRegister("hstatus", "VSXL", 2)
        self.genThread.setupTwoStageVm()
        print("  [OK] Two-stage translation configured")

        # Stress test: Generate large number of instructions
        print("\n[Stress] Generating 1000 instructions...")
        instruction_count = 0
        try:
            for i in range(200):
                # Mix of different instruction types
                self.genInstruction("LD##RISCV")
                self.genInstruction("SD##RISCV")
                self.genInstruction("ADD##RISCV")
                self.genInstruction("ADDI##RISCV")
                self.genInstruction("LW##RISCV")
                instruction_count += 5

                # Progress indicator every 100 instructions
                if instruction_count % 100 == 0:
                    print(f"  [Progress] {instruction_count} instructions generated")

            print(f"  [OK] Generated {instruction_count} instructions")
            print("  PASS: Stress test completed successfully")
        except Exception as e:
            print(f"  FAIL: Stress test failed at instruction {instruction_count}: {e}")

        # Verify system is still stable after stress test
        print("\n[Verification] Post-stress verification...")
        try:
            for i in range(10):
                self.genInstruction("LD##RISCV")
            print("  [OK] Post-stress verification passed")
            print("  PASS: System stable after stress test")
        except Exception as e:
            print(f"  FAIL: Post-stress verification failed: {e}")

        print("\n" + "=" * 70)
        print("Stress Test Complete")
        print("=" * 70 + "\n")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
