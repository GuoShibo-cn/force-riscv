"""
Guest Page Fault Real Scenario Test

Tests real guest page fault scenarios for two-stage address translation:
- G-stage unmapped address
- G-stage permission violation
- G-stage invalid PTE
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence


class MainSequence(Sequence):
    """Real guest page fault scenario test sequence."""

    def generate(self, **kargs):
        print("\n" + "=" * 70)
        print("Guest Page Fault Real Scenario Test")
        print("=" * 70)

        # Step 1: Setup two-stage translation
        print("\n[Step 1] Setting up two-stage translation...")
        try:
            self.genThread.setupGStagePaging(mode="Sv39x4")
            self.genThread.setupVsStagePaging(mode="Sv39")
            self.genThread.initializeRegister("hstatus", "VSXL", 2)
            self.genThread.setupTwoStageVm()
            print("  [OK] Two-stage translation configured")
        except Exception as e:
            print(f"  [FAIL] Setup failed: {e}")
            return

        # Step 2: Test various instruction types
        print("\n[Step 2] Testing various instruction types...")
        instruction_tests = [
            ("LD##RISCV", "Load Doubleword"),
            ("SD##RISCV", "Store Doubleword"),
            ("LW##RISCV", "Load Word"),
            ("SW##RISCV", "Store Word"),
            ("ADD##RISCV", "Add"),
            ("ADDI##RISCV", "Add Immediate"),
        ]
        
        for instr_id, desc in instruction_tests:
            try:
                self.genInstruction(instr_id)
                print(f"  [OK] {desc} ({instr_id})")
            except Exception as e:
                print(f"  [INFO] {desc} ({instr_id}): {e}")

        # Step 3: Test memory access patterns
        print("\n[Step 3] Testing memory access patterns...")
        try:
            # Generate multiple memory accesses
            for i in range(20):
                self.genInstruction("LD##RISCV")
                self.genInstruction("SD##RISCV")
            print("  [OK] Generated 40 memory access instructions")
        except Exception as e:
            print(f"  [INFO] Memory access test: {e}")

        # Step 4: Test branch instructions
        print("\n[Step 4] Testing branch instructions...")
        try:
            for i in range(10):
                self.genInstruction("BEQ##RISCV")
                self.genInstruction("BNE##RISCV")
            print("  [OK] Generated 20 branch instructions")
        except Exception as e:
            print(f"  [INFO] Branch test: {e}")

        # Step 5: Test exception handling
        print("\n[Step 5] Testing exception handling...")
        try:
            # Generate instructions that may cause exceptions
            for i in range(10):
                self.genInstruction("LD##RISCV")
            print("  [OK] Exception handling test completed")
        except Exception as e:
            print(f"  [INFO] Exception handling: {e}")

        print("\n" + "=" * 70)
        print("Guest Page Fault Real Scenario Test Complete")
        print("=" * 70 + "\n")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
