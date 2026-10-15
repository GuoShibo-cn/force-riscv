"""Debug test for setupPtgCSRs two-stage scenario."""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=== Test 2: Two-stage (vsatp + hgatp) ===")

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

        ptg.handle.add_mapping(ctx_id, "VS", 0x10000, 0x30000000, 4096, 0, 0b111)
        ptg.handle.add_mapping(ctx_id, "G", 0x30000000, 0x80000000, 4096, 0, 0b111)

        vsatp_before = ptg.handle.get_vsatp(ctx_id)
        hgatp_before = ptg.handle.get_hgatp(ctx_id)
        self.notice(f"PTG vsatp=0x{vsatp_before:016x} hgatp=0x{hgatp_before:016x}")

        self.genThread.setupPtgCSRs(
            ptg_handle=ptg.handle,
            ctx_id=ctx_id,
            vs_mode="Sv39",
            g_mode="Sv39x4",
        )

        try:
            vsatp_mode, _ = self.genThread.readRegister("vsatp", "MODE")
            vsatp_ppn, _ = self.genThread.readRegister("vsatp", "PPN")
            hgatp_mode, _ = self.genThread.readRegister("hgatp", "MODE")
            hgatp_vmid, _ = self.genThread.readRegister("hgatp", "VMID")
            hgatp_ppn, _ = self.genThread.readRegister("hgatp", "PPN")

            self.notice("After setup:")
            self.notice(f"  vsatp.MODE={vsatp_mode} PPN=0x{vsatp_ppn:X}")
            self.notice(f"  hgatp.MODE={hgatp_mode} VMID={hgatp_vmid} PPN=0x{hgatp_ppn:X}")
            self.notice("TEST 2 PASSED")

        except Exception as e:
            self.notice(f"ERROR: {e}")
            import traceback
            self.notice(f"Traceback: {traceback.format_exc()}")
            self.notice("TEST 2 FAILED")

        ptg.destroy()


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
