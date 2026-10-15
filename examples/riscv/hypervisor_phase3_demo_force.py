"""
H-Extension Phase 3 Demo Test

Demonstrates all Phase 3 infrastructure features in a single test:
- VMID allocation via allocateVMID()
- Per-Hart CSR override via setupPtgCSRsForHart()
- HLVX instruction (execute-permission load)
- hvip CSR manipulation

Prerequisites: build FORCE with Python 3.12
    FORCE_PYTHON_INC=/usr/include/python3.12 FORCE_PYTHON_VER=3.12 make -j

Run:
    bin/friscv -t examples/riscv/hypervisor_phase3_demo_force.py \
              --cfg config/riscv_rv64_twostage.config
    tail sim.log
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend


class HypervisorPhase3Demo(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("Phase 3 Hypervisor Demo")
        self.notice("=" * 60)

        # ------------------------------------------------------------------
        # Feature 1: VMID Allocation
        # ------------------------------------------------------------------
        self.notice("\n[1] VMID Allocation")
        vmids = [self.genThread.allocateVMID() for _ in range(3)]
        self.notice(f"    Allocated: {vmids}")
        self.notice(f"    Unique: {len(set(vmids)) == 3}")

        # ------------------------------------------------------------------
        # Feature 2: Two-stage PTG + VMID assignment
        # ------------------------------------------------------------------
        self.notice("\n[2] Two-stage PTG context with VMID")
        ptg = PtgBackend()
        ctx = ptg.create_two_stage_context(
            vs_mode="Sv39", gs_mode="Sv39x4",
            asid=1, vmid=vmids[0],
            gpa_base=0x80000000, gpa_limit=0x80200000,
            pa_base=0x100000000, pa_limit=0x100200000,
        )
        ptg.handle.add_mapping(ctx, "G", 0x80000000, 0x100000000, 0x200000, 0, 7)
        ptg.handle.add_mapping(ctx, "VS", 0x80000000, 0x80000000, 0x200000, 0, 7)
        g_cnt, _ = ptg.generate_random(ctx, "G",
            va_start=0x80000000, va_end=0x80200000,
            pa_start=0x100000000, pa_end=0x100200000,
            sv_mode="Sv39x4", count=2, seed=1, gs_inherit=1)
        vs_cnt, _ = ptg.generate_random(ctx, "VS",
            va_start=0x80000000, va_end=0x80200000,
            pa_start=0x80000000, pa_end=0x80200000,
            sv_mode="Sv39", count=2, seed=2)
        self.notice(f"    G-stage: {g_cnt}, VS-stage: {vs_cnt}")
        ptg.load_to_force(ctx, "VS", self.genThread)
        ptg.load_to_force(ctx, "G", self.genThread)

        # ------------------------------------------------------------------
        # Feature 3: setupPtgCSRsForHart (Hart 0)
        # ------------------------------------------------------------------
        self.notice("\n[3] setupPtgCSRsForHart (hart_id=0)")
        self.genThread.setupPtgCSRsForHart(
            ptg_handle=ptg.handle,
            ctx_id=ctx,
            hart_id=0,
            vs_mode="Sv39",
            g_mode="Sv39x4",
            vmid=vmids[0],
        )
        self.genThread.setupTwoStageVm()

        # ------------------------------------------------------------------
        # Feature 4: Generate instructions using new H-extension features
        # ------------------------------------------------------------------
        self.notice("\n[4] HLVX + HLV/HSV instruction generation")
        gva_test = 0x80001000
        self.genInstruction("HLVX.HU##RISCV", {"LSTarget": gva_test, "NoPreamble": 1})
        self.genInstruction("HLVX.WU##RISCV", {"LSTarget": gva_test, "NoPreamble": 1})

        # ------------------------------------------------------------------
        # Feature 5: hvip CSR initialization and manipulation
        # ------------------------------------------------------------------
        self.notice("\n[5] hvip CSR manipulation")
        self.initializeRegister("hvip", 0)
        self.genThread.writeRegister("hvip", "VSSIP", 1, False)
        self.genThread.writeRegister("hvip", "VTIP", 0, False)
        hvip_val, _ = self.genThread.readRegister("hvip", "")
        self.notice(f"    hvip = 0x{hvip_val:X}")

        # ------------------------------------------------------------------
        # Feature 6: Cleanup
        # ------------------------------------------------------------------
        for vmid in vmids:
            self.genThread.releaseVMID(vmid)
        self.notice(f"    Released all {len(vmids)} VMIDs")
        ptg.destroy()

        self.notice("\n" + "=" * 60)
        self.notice("Phase 3 demo complete")
        self.notice("=" * 60)


MainSequenceClass = HypervisorPhase3Demo
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
