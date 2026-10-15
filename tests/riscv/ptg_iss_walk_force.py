from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("Phase 2.6: Handcar ISS Walks PTG Two-Stage Page Tables")

        self.notice("Step 1: Creating PTG two-stage context")
        ptg = PtgBackend()
        ctx = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Sv39x4",
            asid=1,
            vmid=1,
            gpa_base=0x90000000,
            gpa_limit=0x90200000,
            pa_base=0x200000000,
            pa_limit=0x220000000,
        )

        self.notice("Step 2: Configuring G-stage mappings")
        ptg.handle.add_mapping(ctx, "G", 0x90000000, 0x200000000, 0x200000, 0, 7)
        ptg.handle.add_mapping(ctx, "G", 0x90200000, 0x200200000, 0x200000, 0, 7)

        self.notice("Step 3: Configuring VS-stage mappings")
        ptg.handle.add_mapping(ctx, "VS", 0x90000000, 0x90000000, 0x200000, 0, 7)
        ptg.handle.add_mapping(ctx, "VS", 0x90200000, 0x90200000, 0x200000, 0, 7)

        self.notice("Step 4: Generating PTG page tables with gs_inherit=1")
        g_count, _ = ptg.generate_random(
            ctx, "G",
            va_start=0x90000000, va_end=0x90400000,
            pa_start=0x200000000, pa_end=0x200400000,
            sv_mode="Sv39x4", count=4, seed=12345, gs_inherit=1,
        )
        self.notice(f"  G-stage: {g_count} mappings generated")
        vs_count, _ = ptg.generate_random(
            ctx, "VS",
            va_start=0x90000000, va_end=0x90400000,
            pa_start=0x90000000, pa_end=0x90400000,
            sv_mode="Sv39", count=4, seed=54321,
        )
        self.notice(f"  VS-stage: {vs_count} mappings generated")

        self.notice("Step 5: Loading page tables to simulator memory")
        ptg.load_to_force(ctx, "VS", self.genThread)
        ptg.load_to_force(ctx, "G", self.genThread)

        self.notice("Step 6: Configuring CSRs for PTG page tables")
        self.genThread.setupPtgCSRs(
            ptg_handle=ptg.handle,
            ctx_id=ctx,
            vs_mode="Sv39",
            g_mode="Sv39x4",
        )
        self.genThread.initializeRegister("hstatus", "VSXL", 2)
        self.genThread.setupTwoStageVm()

        self.notice("Step 7: Overriding satp to PTG VS-stage root for ISS walk")
        vsatp_val = ptg.handle.get_vsatp(ctx)
        vs_ppn = vsatp_val & 0xFFFFFFFFFFF
        self.genThread.initializeRegister("satp", "PPN", vs_ppn)
        self.genThread.writeRegister("satp", "MODE", 8, False)
        self.genThread.updateVm({})

        self.notice("Step 8: Initializing test data at SPA")
        data = bytes(range(256)) * 32
        self.genThread.writePhysicalMemory(0x200000000, data, 0)

        self.notice("Step 9: Generating ADD instructions")
        for _ in range(20):
            self.genInstruction("ADD##RISCV")
            self.genInstruction("ADDI##RISCV")
            self.genInstruction("ADD##RISCV")

        self.notice("Step 10: Generating LD/SD instructions")
        ldst_targets = [0x90000000, 0x90000008, 0x90000100]
        for target in ldst_targets:
            self.genInstruction("LD##RISCV", {"LSTarget": target})
            self.genInstruction("SD##RISCV", {"LSTarget": target})
            self.genInstruction("ADD##RISCV")

        self.notice("Step 11: Generating random LD/SD for broader coverage")
        for _ in range(5):
            rand_va = self.genVA(Size=48, Align=8, Type="D", Bank="Default")
            self.genInstruction("LD##RISCV", {"LSTarget": rand_va})
            self.genInstruction("SD##RISCV", {"LSTarget": rand_va})

        self.notice("Step 12: Verifying PTG address translations")
        for gva in [0x90000000, 0x90200000]:
            translate = ptg.handle.translate_sequential(ctx, gva, 0)
            spa, vs_code, g_code = translate
            self.notice(f"  GVA 0x{gva:X} -> SPA 0x{spa:X} (vs_fault={vs_code}, g_fault={g_code})")

        ptg.destroy()
        self.notice("Phase 2.6 complete: ISS walked PTG two-stage page tables")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
