"""Minimal ISS debug test - vstart FIRST"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence

EnvClass = EnvRISCV
GenThreadClass = GenThreadRISCV

class MainSequence(Sequence):
    def generate(self, **kwargs):
        print("[DEBUG] about to writeRegister vstart")
        try:
            self.writeRegister("vstart", 0)
            print("[DEBUG] writeRegister vstart OK")
        except Exception as e:
            print(f"[DEBUG] writeRegister vstart failed: {e}")
        print("[DEBUG] about to setupGStagePaging")
        self.genThread.setupGStagePaging(mode="Sv39x4")
        self.genThread.setupVsStagePaging(mode="Sv39")
        self.genThread.initializeRegister("hstatus", "VSXL", 2)
        self.genThread.setupTwoStageVm()
        print("[DEBUG] setup done, generating HLV.B")
        self.genInstruction("HLV.B##RISCV")
        print("[DEBUG] HLV.B OK")

MainSequenceClass = MainSequence
