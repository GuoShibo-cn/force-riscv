"""Phase 2.4.1: Diagnose CSR overwrite timing and translation correctness."""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("Phase 2.4.1: CSR Overwrite Diagnosis")
        self.notice("=" * 60)

        ptg = PtgBackend()
        ctx_id = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Sv39x4",
            asid=0,
            vmid=1,
            pa_base=0x80000000,
            pa_limit=0x90000000,
            gpa_base=0x30000000,
            gpa_limit=0x40000000,
        )
        self.notice(f"Context ID: {ctx_id}")

        self.notice("\n[T1] Add mappings")
        ptg.handle.add_mapping(ctx_id, "VS", 0x10000, 0x30000000, 4096, 0, 0b111)
        ptg.handle.add_mapping(ctx_id, "G", 0x30000000, 0x80000000, 4096, 0, 0b111)

        self.notice("\n[T2] Generate page tables")
        ptg.generate_random(ctx_id, "VS", 0x10000, 0x20000, 0x30000000, 0x30100000,
                            "Sv39", 1, seed=100)
        ptg.generate_random(ctx_id, "G", 0x30000000, 0x30100000, 0x80000000, 0x80100000,
                            "Sv39x4", 1, seed=200, gs_inherit=1)

        self.notice("\n[T3] Load to FORCE memory")
        ptg.load_to_force(ctx_id, "VS", self.genThread)
        ptg.load_to_force(ctx_id, "G", self.genThread)

        self.notice("\n[T4] Read BEFORE setupPtgCSRs")
        try:
            vsatp_before_mode, _ = self.genThread.readRegister("vsatp", "MODE")
            vsatp_before_ppn, _ = self.genThread.readRegister("vsatp", "PPN")
            hgatp_before_mode, _ = self.genThread.readRegister("hgatp", "MODE")
            hgatp_before_vmid, _ = self.genThread.readRegister("hgatp", "VMID")
            hgatp_before_ppn, _ = self.genThread.readRegister("hgatp", "PPN")
        except Exception as e:
            vsatp_before_mode = vsatp_before_ppn = hgatp_before_mode = 0
            hgatp_before_vmid = hgatp_before_ppn = 0
            self.notice(f"  readRegister failed: {e}")

        self.notice(f"  BEFORE: vsatp.MODE={vsatp_before_mode} PPN=0x{vsatp_before_ppn:X}")
        self.notice(f"  BEFORE: hgatp.MODE={hgatp_before_mode} VMID={hgatp_before_vmid} PPN=0x{hgatp_before_ppn:X}")

        self.notice("\n[T5] Call setupPtgCSRs")
        self.genThread.setupPtgCSRs(ptg_handle=ptg.handle, ctx_id=ctx_id,
                                     vs_mode="Sv39", g_mode="Sv39x4")

        self.notice("\n[T6] Read AFTER setupPtgCSRs")
        try:
            vsatp_after_mode, _ = self.genThread.readRegister("vsatp", "MODE")
            vsatp_after_ppn, _ = self.genThread.readRegister("vsatp", "PPN")
            hgatp_after_mode, _ = self.genThread.readRegister("hgatp", "MODE")
            hgatp_after_vmid, _ = self.genThread.readRegister("hgatp", "VMID")
            hgatp_after_ppn, _ = self.genThread.readRegister("hgatp", "PPN")
        except Exception as e:
            vsatp_after_mode = vsatp_after_ppn = hgatp_after_mode = 0
            hgatp_after_vmid = hgatp_after_ppn = 0
            self.notice(f"  readRegister failed: {e}")

        self.notice(f"  AFTER: vsatp.MODE={vsatp_after_mode} PPN=0x{vsatp_after_ppn:X}")
        self.notice(f"  AFTER: hgatp.MODE={hgatp_after_mode} VMID={hgatp_after_vmid} PPN=0x{hgatp_after_ppn:X}")

        self.notice("\n[T7] Generate instructions (triggers ISS paging)")
        for _ in range(5):
            self.genInstruction("ADD##RISCV")

        self.notice("\n[T8] Read AFTER genInstruction")
        try:
            vsatp_final_mode, _ = self.genThread.readRegister("vsatp", "MODE")
            vsatp_final_ppn, _ = self.genThread.readRegister("vsatp", "PPN")
            hgatp_final_mode, _ = self.genThread.readRegister("hgatp", "MODE")
            hgatp_final_vmid, _ = self.genThread.readRegister("hgatp", "VMID")
            hgatp_final_ppn, _ = self.genThread.readRegister("hgatp", "PPN")
        except Exception as e:
            vsatp_final_mode = vsatp_final_ppn = hgatp_final_mode = 0
            hgatp_final_vmid = hgatp_final_ppn = 0
            self.notice(f"  readRegister failed: {e}")

        self.notice(f"  FINAL: vsatp.MODE={vsatp_final_mode} PPN=0x{vsatp_final_ppn:X}")
        self.notice(f"  FINAL: hgatp.MODE={hgatp_final_mode} VMID={hgatp_final_vmid} PPN=0x{hgatp_final_ppn:X}")

        self.notice("\n[T9] PTG translation test")
        for va in [0x10000, 0x30000000]:
            try:
                result = ptg.handle.translate_sequential(ctx_id, va, 0)
                self.notice(f"  translate(0x{va:X}): {result}")
            except Exception as e:
                self.notice(f"  translate(0x{va:X}): ERROR {e}")

        self.notice("\n" + "=" * 60)

        if vsatp_after_ppn == vsatp_final_ppn and vsatp_after_mode == vsatp_final_mode:
            self.notice("CONCLUSION: vsatp STABLE after genInstruction")
        else:
            self.notice("CONCLUSION: vsatp OVERWRITTEN by genInstruction")

        if hgatp_after_ppn == hgatp_final_ppn and hgatp_after_mode == hgatp_final_mode:
            self.notice("CONCLUSION: hgatp STABLE after genInstruction")
        else:
            self.notice("CONCLUSION: hgatp OVERWRITTEN by genInstruction")

        self.notice("=" * 60)

        ptg.destroy()


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
