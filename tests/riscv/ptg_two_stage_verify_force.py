from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.Utils import LoadGPR64
import struct

SENTINEL = 0xDEADBEEFCAFE1234
GVA_TARGET = 0x90000000
GPA_TARGET = 0x90000000
SPA_TARGET = 0x90000000

VS_ROOT_PA = 0x90600000
G_ROOT_PA = 0x90800000
G_MID_PA = 0x90801000


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("Minimal two-stage translation test")
        self.notice("=" * 60)

        # 1. 构建 VS-stage 页表（Sv39，1GB superpage）
        pte_vs_valid = 0x5F  # D=1, A=1, U=1, X=1, W=1, R=1, V=1 (user page for VS-stage)
        pte_g_valid = 0x5F   # D=1, A=1, U=1, X=1, W=1, R=1, V=1 (U=1 required for G-stage HLV access)
        pte_table = 0x01

        vs_root = bytearray(4096)
        
        # Map data region: GVA 0x90000000 -> GPA 0x90000000
        gva_idx2 = (GVA_TARGET >> 30) & 0x1FF
        vs_ppn2 = (GPA_TARGET >> 30) & 0x3FFFFFF
        vs_pte = (vs_ppn2 << 28) | pte_vs_valid
        struct.pack_into("<Q", vs_root, gva_idx2 * 8, vs_pte)
        
        # Map instruction region: GVA 0x80000000 -> GPA 0x80000000
        instr_gva = 0x80000000
        instr_idx2 = (instr_gva >> 30) & 0x1FF
        instr_ppn2 = (instr_gva >> 30) & 0x3FFFFFF
        instr_pte = (instr_ppn2 << 28) | pte_vs_valid
        struct.pack_into("<Q", vs_root, instr_idx2 * 8, instr_pte)

        # 2. 构建 G-stage 页表（Sv39x4，2MB page）
        g_root = bytearray(4096)
        g_mid = bytearray(4096)

        # G-stage root -> mid (for data region 0x90000000)
        g_root_idx2 = (GPA_TARGET >> 30) & 0x1FF
        g_mid_ppn = G_MID_PA >> 12
        g_root_pte = (g_mid_ppn << 10) | pte_table
        struct.pack_into("<Q", g_root, g_root_idx2 * 8, g_root_pte)

        # G-stage root -> VS root mapping (for VS page tables at 0x90600000)
        g_vs_root_idx2 = (VS_ROOT_PA >> 30) & 0x1FF
        if g_vs_root_idx2 != g_root_idx2:
            g_vs_mid_ppn = G_MID_PA >> 12
            g_vs_root_pte = (g_vs_mid_ppn << 10) | pte_table
            struct.pack_into("<Q", g_root, g_vs_root_idx2 * 8, g_vs_root_pte)

        # G-stage mid -> data page (0x90000000 -> 0x90000000)
        g_data_idx1 = (GPA_TARGET >> 21) & 0x1FF
        g_data_ppn1 = (SPA_TARGET >> 21) & 0x1FF
        g_data_ppn2 = (SPA_TARGET >> 30) & 0x3FFFFFF
        g_data_pte = (g_data_ppn2 << 28) | (g_data_ppn1 << 19) | pte_g_valid
        struct.pack_into("<Q", g_mid, g_data_idx1 * 8, g_data_pte)

        # G-stage mid -> VS root page (0x90600000 -> 0x90600000)
        g_vs_idx1 = (VS_ROOT_PA >> 21) & 0x1FF
        g_vs_ppn1 = (VS_ROOT_PA >> 21) & 0x1FF
        g_vs_ppn2 = (VS_ROOT_PA >> 30) & 0x3FFFFFF
        g_vs_pte = (g_vs_ppn2 << 28) | (g_vs_ppn1 << 19) | pte_g_valid
        struct.pack_into("<Q", g_mid, g_vs_idx1 * 8, g_vs_pte)
        
        # G-stage: Map instruction region (0x80000000 -> 0x80000000)
        instr_gpa = 0x80000000
        instr_g_root_idx2 = (instr_gpa >> 30) & 0x1FF
        instr_g_mid_ppn = G_MID_PA >> 12
        instr_g_root_pte = (instr_g_mid_ppn << 10) | pte_table
        struct.pack_into("<Q", g_root, instr_g_root_idx2 * 8, instr_g_root_pte)
        
        instr_g_mid_idx1 = (instr_gpa >> 21) & 0x1FF
        instr_g_ppn1 = (instr_gpa >> 21) & 0x1FF
        instr_g_ppn2 = (instr_gpa >> 30) & 0x3FFFFFF
        instr_g_pte = (instr_g_ppn2 << 28) | (instr_g_ppn1 << 19) | pte_g_valid
        struct.pack_into("<Q", g_mid, instr_g_mid_idx1 * 8, instr_g_pte)

        # 3. 写入页表到物理内存
        self.notice(f"  VS root PTE at index {gva_idx2}: 0x{vs_pte:016X}")
        self.notice(f"  G root PTE at index {g_root_idx2}: 0x{g_root_pte:016X}")
        self.notice(f"  VS root bytes at idx {gva_idx2}: {vs_root[gva_idx2*8:gva_idx2*8+8].hex()}")
        self.notice(f"  G root bytes at idx {g_root_idx2}: {g_root[g_root_idx2*8:g_root_idx2*8+8].hex()}")
        
        # 先写入 PTE（8 字节），而不是整个页表（4096 字节）
        vs_pte_bytes = vs_root[gva_idx2*8:gva_idx2*8+8]
        g_root_pte_bytes = g_root[g_root_idx2*8:g_root_idx2*8+8]
        g_mid_pte_bytes = g_mid[g_data_idx1*8:g_data_idx1*8+8]
        g_vs_pte_bytes = g_mid[g_vs_idx1*8:g_vs_idx1*8+8]
        
        self.notice(f"  Writing VS PTE: {vs_pte_bytes.hex()}")
        self.notice(f"  Writing G root PTE: {g_root_pte_bytes.hex()}")
        self.notice(f"  Writing G mid PTE: {g_mid_pte_bytes.hex()}")
        self.notice(f"  Writing G VS PTE: {g_vs_pte_bytes.hex()}")
        
        self.genThread.writePhysicalMemory(VS_ROOT_PA + gva_idx2*8, bytes(vs_pte_bytes), 0)
        self.genThread.writePhysicalMemory(G_ROOT_PA + g_root_idx2*8, bytes(g_root_pte_bytes), 0)
        self.genThread.writePhysicalMemory(G_MID_PA + g_data_idx1*8, bytes(g_mid_pte_bytes), 0)
        self.genThread.writePhysicalMemory(G_MID_PA + g_vs_idx1*8, bytes(g_vs_pte_bytes), 0)

        # 4. 写入哨兵值
        sentinel_bytes = struct.pack("<Q", SENTINEL)
        self.genThread.writePhysicalMemory(SPA_TARGET, sentinel_bytes, 0)

        self.notice(f"  VS root PA=0x{VS_ROOT_PA:X}")
        self.notice(f"  G root PA=0x{G_ROOT_PA:X}, mid PA=0x{G_MID_PA:X}")
        self.notice(f"  sentinel PA=0x{SPA_TARGET:X}=0x{SENTINEL:016X}")
        self.notice(f"  GVA 0x{GVA_TARGET:X} -> GPA 0x{GPA_TARGET:X} -> SPA 0x{SPA_TARGET:X}")

        # 5. 设置 vsatp 和 hgatp
        vsatp_val = (8 << 60) | (VS_ROOT_PA >> 12)
        hgatp_val = (8 << 60) | (G_ROOT_PA >> 12)
        self.notice(f"  vsatp=0x{vsatp_val:016X} hgatp=0x{hgatp_val:016X}")

        # 使用 initializeRegister 而不是 LoadGPR64
        self.genThread.initializeRegister("x6", "", vsatp_val)
        self.genInstruction("CSRRW#register#RISCV", {
            "rd": 0, "rs1": 6, "csr": 0x280, "NoRestriction": 1,
        })

        self.genThread.initializeRegister("x7", "", hgatp_val)
        self.genInstruction("CSRRW#register#RISCV", {
            "rd": 0, "rs1": 7, "csr": 0x680, "NoRestriction": 1,
        })

        # Flush TLB after changing vsatp/hgatp
        self.genInstruction("SFENCE.VMA##RISCV", {"rs1": 0, "rs2": 0, "NoRestriction": 1})

        # 6. 设置 hstatus.HU=1（允许 U-mode 执行 HLV）
        self.genThread.initializeRegister("x8", "", 0x200)  # HU is bit 9
        self.genInstruction("CSRRW#register#RISCV", {
            "rd": 0, "rs1": 8, "csr": 0x600, "NoRestriction": 1,
        })

        # 7. 加载 GVA 到 x1
        self.genThread.initializeRegister("x1", "", GVA_TARGET)

        # 8. 执行 HLV.D（在 M-mode，但 hstatus.SPVP=1 允许执行）
        self.notice("  Executing HLV.D in M-mode with SPVP=1")
        self.genInstruction("HLV.D##RISCV", {"rs1": 1, "rd": 2, "NoRestriction": 1})

        # 9. 验证结果
        x2_val, valid = self.readRegister("x2")
        if valid and x2_val == SENTINEL:
            self.notice(f"  SUCCESS: x2 = 0x{x2_val:016X} (sentinel)")
        else:
            self.error(f"  FAIL: x2 = 0x{x2_val:016X}, expected 0x{SENTINEL:016X}")

        self.notice("Done")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
