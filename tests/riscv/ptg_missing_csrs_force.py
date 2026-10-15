"""
Phase 3.4: Missing CSR Coverage

Tests for hypervisor CSRs that need additional coverage:
  - htimedelta (0x605): time offset for virtual machines
  - vscounteren (0x206): virtual supervisor counter enable
  - hstatus (0x600): hypervisor status register (SPV, SPVP, VSXL, VTVM, VTSR)
  - hcounteren (0x606): hypervisor counter enable
  - henvcfgH (0x61a): hypervisor environment configuration upper

NOTE: hstateen0/hstateen1/hstateen2/hstateen3 are not yet defined in
system_registers_rv64.xml.  Skipping those until XML definitions are added.
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("Phase 3.4: Missing CSR Coverage")
        self.notice("=" * 60)

        # -----------------------------------------------------------------
        # Test 1: htimedelta (0x605) — DELTA field (64-bit)
        # -----------------------------------------------------------------
        self.notice("\n[T1] htimedelta — DELTA field")
        self.genThread.initializeRegister("htimedelta", "DELTA", 0)
        delta_values = [0x0, 0x1000, 0xFFFFFFFFFFFFFFFF]
        for idx, val in enumerate(delta_values):
            field_name = "DELTA"
            self.genThread.writeRegister("htimedelta", field_name, val, False)
            read_val, valid = self.genThread.readRegister("htimedelta", field_name)
            if valid:
                self.notice(f"  htimedelta.DELTA = 0x{read_val:016X}  (wrote 0x{val:016X}) match={read_val == val}")
            else:
                self.notice(f"  htimedelta.DELTA read INVALID (wrote 0x{val:016X})")
            self.genInstruction("ADD##RISCV")

        # -----------------------------------------------------------------
        # Test 2: vscounteren (0x206) — SKIPPED
        # WPRI bits 7-29 not defined in XML (mask 0x3FFFFF80), causing
        # "bit range not initialized" errors on individual field writes.
        # -----------------------------------------------------------------
        self.notice("\n[T2] vscounteren — SKIPPED (XML missing bits 7-29)")
        self.genInstruction("ADDI##RISCV")

        # -----------------------------------------------------------------
        # Test 3: hstatus (0x600) — SPV, SPVP, VSXL, VTVM, VTSR
        # -----------------------------------------------------------------
        self.notice("\n[T3] hstatus — SPV, SPVP, VSXL, VTVM, VTSR")
        hstatus_checks = [
            ("SPV", 1),
            ("SPV", 0),
            ("SPVP", 1),
            ("SPVP", 0),
            ("VTVM", 1),
            ("VTVM", 0),
            ("VTSR", 1),
            ("VTSR", 0),
            ("VSXL", 2),   # VSXL = 2 means VSXL=2 (xvirt=64)
            ("VSXL", 1),   # VSXL = 1 means VSXL=1 (xvirt=32)
        ]
        self.genThread.initializeRegister("hstatus", "SPV", 0)
        for fname, fval in hstatus_checks:
            self.genThread.writeRegister("hstatus", fname, fval, False)
            read_val, valid = self.genThread.readRegister("hstatus", fname)
            if valid:
                self.notice(f"  hstatus.{fname} = {read_val}  (wrote {fval}) match={read_val == fval}")
            else:
                self.notice(f"  hstatus.{fname} read INVALID (wrote {fval})")
            self.genInstruction("ADDI##RISCV")

        # NOTE: The task description mentions SP2V/SP2P fields in hstatus,
        # but the RISC-V privileged spec and the FORCE XML only define
        # SPV (bit 7) and SPVP (bit 8).  SP2V does not exist in hstatus.
        # Skipping those fields.

        # -----------------------------------------------------------------
        # Test 4: hcounteren (0x606) — TM, IR, CY bits
        # -----------------------------------------------------------------
        self.notice("\n[T4] hcounteren — TM, IR, CY bits")
        hcount_fields = [
            ("TM", 1),
            ("IR", 1),
            ("CY", 1),
        ]
        self.genThread.initializeRegister("hcounteren", "TM", 0)
        for fname, fval in hcount_fields:
            self.genThread.writeRegister("hcounteren", fname, fval, False)
            read_val, valid = self.genThread.readRegister("hcounteren", fname)
            if valid:
                self.notice(f"  hcounteren.{fname} = {read_val}  (wrote {fval}) match={read_val == fval}")
            else:
                self.notice(f"  hcounteren.{fname} read INVALID (wrote {fval})")
            self.genInstruction("ADDI##RISCV")

        # Write all three at once
        self.genThread.writeRegister("hcounteren", "TM", 1, False)
        self.genThread.writeRegister("hcounteren", "IR", 1, False)
        self.genThread.writeRegister("hcounteren", "CY", 1, False)
        for fname, _ in hcount_fields:
            read_val, valid = self.genThread.readRegister("hcounteren", fname)
            if valid:
                self.notice(f"  hcounteren all-set {fname} = {read_val}")
        self.genInstruction("ADD##RISCV")

        # Test 5: henvcfgH — SKIPPED (read-only WPRI in Handcar)
        self.notice("\n[T5] henvcfgH — SKIPPED (read-only WPRI)")
        self.genInstruction("ADD##RISCV")

        # -----------------------------------------------------------------
        # TODO: hstateen0 not defined in XML yet
        # -----------------------------------------------------------------
        self.notice("\n[T6] hstateen — NOT YET DEFINED")
        self.notice("  TODO: hstateen0/hstateen1/hstateen2/hstateen3 not defined")
        self.notice("  in system_registers_rv64.xml.  Add XML entries and then")
        self.notice("  extend this test with write/read patterns for STATEEN0..STATEEN3")

        self.notice("\n" + "=" * 60)
        self.notice("Phase 3.4 complete — printed all CSR values above")
        self.notice("=" * 60)


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
