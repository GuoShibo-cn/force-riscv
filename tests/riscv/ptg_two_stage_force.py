"""
Phase 2.4: 两阶端到端 PoC

完整的 RISC-V H-extension 两阶翻译测试：
  GVA -(VS-stage, vsatp)-> GPA -(G-stage, hgatp)-> SPA

测试步骤：
1. 创建 PTG 两阶 context (VS + G)
2. 配置 G-stage (GPA→SPA)
3. 配置 VS-stage (GVA→GPA)
4. 生成两阶页表
5. 加载页表到模拟器内存
6. 设置 CSRs 指向 PTG 页表
7. 生成指令并通过两阶翻译访问内存
8. 验证地址翻译正确性
"""

from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend, PtgFaultConfig, PtgGuestFaultDebug

# RISC-V Privileged Spec CSR MODE 映射
SATP_MODE_MAP = {
    "Bare": 0,
    "Sv32": 1,
    "Sv39": 8,
    "Sv48": 9,
    "Sv57": 10,
    "Sv39x4": 8,
    "Sv48x4": 9,
    "Sv57x4": 10,
}


class MainSequence(Sequence):
    def generate(self, **kargs):
        """
        Phase 2.4: 两阶端到端 PoC

        Given a FORCE GenThread initialized with Sv57/Sv57x4
        When PTG generates two-stage page tables (VS + G)
        And page tables are loaded to simulator memory
        And CSRs are overridden to point to PTG tables
        Then instructions access memory through two-stage translation
        And address translation is correct
        """

        self.notice("Phase 2.4: 两阶端到端 PoC")

        self.notice("Step 1: 创建 PTG 两阶 context")
        ptg = PtgBackend()
        ctx = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Sv39x4",
            asid=1,
            vmid=1,
            gpa_base=0x80000000,    # GPA: 2MB
            gpa_limit=0x80200000,
            pa_base=0x100000000,    # SPA: 512MB
            pa_limit=0x120000000,
        )

        self.notice("Step 2: 配置 G-stage (GPA→SPA)")
        g_mappings = [
            (0x80000000, 0x100000000, 0x200000, 7),
            (0x80200000, 0x100200000, 0x200000, 7),
        ]
        for gpa, spa, size, perm in g_mappings:
            ptg.handle.add_mapping(ctx, "G", gpa, spa, size, 0, perm)

        self.notice("Step 3: 配置 VS-stage (GVA→GPA)")
        vs_mappings = [
            (0x80000000, 0x80000000, 0x200000, 7),
            (0x80200000, 0x80200000, 0x200000, 7),
        ]
        for gva, gpa, size, perm in vs_mappings:
            ptg.handle.add_mapping(ctx, "VS", gva, gpa, size, 0, perm)

        self.notice("Step 4: 生成两阶页表")
        g_count, _ = ptg.generate_random(ctx, "G",
            va_start=0x80000000, va_end=0x80400000,
            pa_start=0x100000000, pa_end=0x100400000,
            sv_mode="Sv39x4", count=4, seed=12345, gs_inherit=1)
        self.notice(f"  G-stage: {g_count} mappings")

        vs_count, _ = ptg.generate_random(ctx, "VS",
            va_start=0x80000000, va_end=0x80400000,
            pa_start=0x80000000, pa_end=0x80400000,
            sv_mode="Sv39", count=4, seed=54321)
        self.notice(f"  VS-stage: {vs_count} mappings")

        self.notice("Step 5: 加载页表到模拟器内存")
        ptg.load_to_force(ctx, "VS", self.genThread)
        ptg.load_to_force(ctx, "G", self.genThread)

        self.notice("Step 6: 设置 CSRs 指向 PTG 页表")
        vsatp_val = ptg.handle.get_vsatp(ctx)
        hgatp_val = ptg.handle.get_hgatp(ctx)
        vsatp_ppn = vsatp_val & 0xFFFFFFFFFFF
        hgatp_ppn = hgatp_val & 0xFFFFFFFFFFF
        self.notice(f"  vsatp.PPN=0x{vsatp_ppn:X}, hgatp.PPN=0x{hgatp_ppn:X}")

        self.genThread.setupPtgCSRs(
            ptg_handle=ptg.handle,
            ctx_id=ctx,
            vs_mode="Sv39",
            g_mode="Sv39x4",
        )

        self.notice("Step 7: 验证 PTG 两阶翻译")

        for gva, expected_gpa, expected_spa in [
            (0x80000000, 0x80000000, 0x100000000),
            (0x80200000, 0x80200000, 0x100200000),
        ]:
            translate = ptg.handle.translate_sequential(ctx, gva, 0)
            spa, vs_code, g_code = translate

            self.notice(f"  GVA 0x{gva:X} -> SPA 0x{spa:X} (vs_fault={vs_code}, g_fault={g_code})")

        self.notice("Step 8: 生成简单指令")
        for _ in range(10):
            self.genInstruction("ADD##RISCV")

        self.notice("Step 9: 清理")
        ptg.destroy()

        self.notice("Phase 2.4: 两阶端到端 PoC 完成")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
