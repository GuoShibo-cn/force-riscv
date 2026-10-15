from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend
from riscv.Utils import LoadGPR64
import struct

class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("PTG G-stage U-bit bug verification")
        self.notice("=" * 60)

        # 创建 PTG 上下文
        ptg = PtgBackend()
        ctx = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Sv39x4",
            asid=1,
            vmid=1,
            gpa_base=0x90000000,
            gpa_limit=0xA0000000,
            pa_base=0xA0000000,
            pa_limit=0xB0000000,
        )

        # 添加一个映射，明确设置 G-stage 权限位包含 U=1
        gva = 0x80000000
        gpa = 0x90000000
        spa = 0xA0000000
        
        # VS-stage: V=1, R=1, W=1, A=1, D=1
        vs_perms = 0x1F
        
        # G-stage: V=1, R=1, W=1, U=1, A=1, D=1, X=1
        g_perms = 0x7F
        
        self.notice(f"Adding mapping:")
        self.notice(f"  GVA: 0x{gva:08X} -> GPA: 0x{gpa:08X} -> SPA: 0x{spa:08X}")
        self.notice(f"  VS perms: 0x{vs_perms:02X} (V=1, R=1, W=1, A=1, D=1)")
        self.notice(f"  G perms: 0x{g_perms:02X} (V=1, R=1, W=1, U=1, A=1, D=1, X=1)")
        
        ptg.handle.add_mapping(ctx, "VS", gva, gpa, 0x200000, 0, vs_perms)
        ptg.handle.add_mapping(ctx, "G", gpa, spa, 0x200000, 0, g_perms)

        # 生成页表
        self.notice("Generating page tables...")
        ptg.generate_random(ctx, "VS",
            va_start=0x80000000, va_end=0x90000000,
            pa_start=0x90000000, pa_end=0xA0000000,
            sv_mode="Sv39", count=1, seed=42,
        )
        
        ptg.generate_random(ctx, "G",
            va_start=0x90000000, va_end=0xA0000000,
            pa_start=0xA0000000, pa_end=0xB0000000,
            sv_mode="Sv39x4", count=1, seed=42,
            gs_inherit=1,
        )

        # 加载到 FORCE
        ptg.load_to_force(ctx, "VS", self.genThread)
        ptg.load_to_force(ctx, "G", self.genThread)

        # 设置 CSRs
        vsatp_val = ptg.handle.get_vsatp(ctx)
        hgatp_val = ptg.handle.get_hgatp(ctx)
        
        self.notice(f"Setting CSRs:")
        self.notice(f"  vsatp: 0x{vsatp_val:016X}")
        self.notice(f"  hgatp: 0x{hgatp_val:016X}")

        self.genThread.initializeRegister("x6", "", vsatp_val)
        self.genThread.initializeRegister("x7", "", hgatp_val)
        self.genThread.initializeRegister("x8", "", 0x80)

        self.genInstruction("CSRRW#register#RISCV", {"rd": 0, "rs1": 6, "csr": 0x280, "NoRestriction": 1})
        self.genInstruction("CSRRW#register#RISCV", {"rd": 0, "rs1": 7, "csr": 0x680, "NoRestriction": 1})
        self.genInstruction("CSRRW#register#RISCV", {"rd": 0, "rs1": 8, "csr": 0x600, "NoRestriction": 1})

        # 测试 HLV.D
        self.notice(f"Testing HLV.D with GVA: 0x{gva:08X}")
        self.genThread.initializeRegister("x1", "", gva)
        self.genInstruction("HLV.D##RISCV", {"rs1": 1, "NoRestriction": 1})

        self.notice("Done")
        ptg.destroy()


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
