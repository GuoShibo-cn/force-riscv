from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend
from riscv.Utils import LoadGPR64
import random


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("PTG Two-Stage Translation Stress Test")
        self.notice("=" * 60)

        # 随机种子（可从命令行参数获取）
        seed = random.randint(0, 0xFFFFFFFF)
        random.seed(seed)
        self.notice(f"Random seed: 0x{seed:08X}")

        # 随机化配置（减少映射数量避免 timeout）
        num_mappings = random.randint(3, 8)
        use_superpages = random.choice([True, False])
        page_sizes = [0x1000]  # 4KB
        if use_superpages:
            page_sizes.extend([0x200000])  # 2MB only (1GB 太慢)

        # 地址空间配置
        gva_base = 0x80000000
        gpa_base = 0x80000000
        spa_base = 0x90000000

        self.notice(f"Configuration:")
        self.notice(f"  Mappings: {num_mappings}")
        self.notice(f"  Page sizes: {[f'0x{ps:X}' for ps in page_sizes]}")
        self.notice(f"  GVA base: 0x{gva_base:08X}")
        self.notice(f"  GPA base: 0x{gpa_base:08X}")
        self.notice(f"  SPA base: 0x{spa_base:08X}")

        # 创建 PTG 上下文
        ptg = PtgBackend()
        ctx = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Sv39x4",
            asid=random.randint(1, 100),
            vmid=random.randint(1, 50),
            gpa_base=gpa_base,
            gpa_limit=gpa_base + 0x10000000,  # 256MB
            pa_base=spa_base,
            pa_limit=spa_base + 0x10000000,
        )

        # 生成随机映射（避免地址冲突）
        mappings = []
        used_offsets = set()

        for i in range(num_mappings):
            # VS-stage 权限位（U 位随机）
            vs_perms = 0x01  # V=1
            if random.random() > 0.3:
                vs_perms |= 0x02  # R=1
            if random.random() > 0.3:
                vs_perms |= 0x04  # W=1
            if random.random() > 0.5:
                vs_perms |= 0x08  # X=1
            if random.random() > 0.5:
                vs_perms |= 0x10  # U=1 (随机)
            vs_perms |= 0x20  # A=1
            vs_perms |= 0x40  # D=1
            
            # G-stage 权限位（U 位必须为 1）
            g_perms = vs_perms | 0x10  # 强制 U=1

            # 随机页大小
            page_size = random.choice(page_sizes)

            # 随机地址（页对齐，避免冲突）
            while True:
                offset = random.randint(0, 0x0F000000) & ~(page_size - 1)
                if offset not in used_offsets:
                    used_offsets.add(offset)
                    break

            gva = gva_base + offset
            gpa = gpa_base + offset
            spa = spa_base + offset

            mappings.append({
                'gva': gva,
                'gpa': gpa,
                'spa': spa,
                'size': page_size,
                'vs_perms': vs_perms,
                'g_perms': g_perms,
            })

            self.notice(f"  Mapping {i+1}: GVA 0x{gva:08X} -> GPA 0x{gpa:08X} -> SPA 0x{spa:08X} "
                       f"(size=0x{page_size:X}, vs_perms=0x{vs_perms:02X}, g_perms=0x{g_perms:02X})")

        # 添加映射（先 VS 后 G，触发自动 G-stage 映射创建）
        for m in mappings:
            ptg.handle.add_mapping(ctx, "VS", m['gva'], m['gpa'], m['size'], 0, m['vs_perms'])
            ptg.handle.add_mapping(ctx, "G", m['gpa'], m['spa'], m['size'], 0, m['g_perms'])

        # 加载到 FORCE
        ptg.load_to_force(ctx, "VS", self.genThread)
        ptg.load_to_force(ctx, "G", self.genThread)

        # 设置 CSRs
        vsatp_val = ptg.handle.get_vsatp(ctx)
        hgatp_val = ptg.handle.get_hgatp(ctx)

        self.notice(f"CSRs: vsatp=0x{vsatp_val:016X}, hgatp=0x{hgatp_val:016X}")

        # Set vsatp, hgatp, hstatus via LUI+CSRRW (initializeRegister is async)
        # vsatp: split into upper and lower parts
        vsatp_upper = (vsatp_val >> 32) & 0xFFFFFFFF
        vsatp_lower = vsatp_val & 0xFFFFFFFF
        self.genInstruction("LUI##RISCV", {"rd": 6, "simm20": vsatp_upper >> 12, "NoRestriction": 1})
        self.genInstruction("ADDI##RISCV", {"rd": 6, "rs1": 6, "simm12": vsatp_upper & 0xFFF, "NoRestriction": 1})
        self.genInstruction("SLLI#RV64I#RISCV", {"rd": 6, "rs1": 6, "shamt": 32, "NoRestriction": 1})
        self.genInstruction("LUI##RISCV", {"rd": 7, "simm20": vsatp_lower >> 12, "NoRestriction": 1})
        self.genInstruction("ADDI##RISCV", {"rd": 7, "rs1": 7, "simm12": vsatp_lower & 0xFFF, "NoRestriction": 1})
        self.genInstruction("OR##RISCV", {"rd": 6, "rs1": 6, "rs2": 7, "NoRestriction": 1})
        self.genInstruction("CSRRW#register#RISCV", {"rd": 0, "rs1": 6, "csr": 0x280, "NoRestriction": 1})

        # hgatp: split into upper and lower parts
        hgatp_upper = (hgatp_val >> 32) & 0xFFFFFFFF
        hgatp_lower = hgatp_val & 0xFFFFFFFF
        self.genInstruction("LUI##RISCV", {"rd": 7, "simm20": hgatp_upper >> 12, "NoRestriction": 1})
        self.genInstruction("ADDI##RISCV", {"rd": 7, "rs1": 7, "simm12": hgatp_upper & 0xFFF, "NoRestriction": 1})
        self.genInstruction("SLLI#RV64I#RISCV", {"rd": 7, "rs1": 7, "shamt": 32, "NoRestriction": 1})
        self.genInstruction("LUI##RISCV", {"rd": 8, "simm20": hgatp_lower >> 12, "NoRestriction": 1})
        self.genInstruction("ADDI##RISCV", {"rd": 8, "rs1": 8, "simm12": hgatp_lower & 0xFFF, "NoRestriction": 1})
        self.genInstruction("OR##RISCV", {"rd": 7, "rs1": 7, "rs2": 8, "NoRestriction": 1})
        self.genInstruction("CSRRW#register#RISCV", {"rd": 0, "rs1": 7, "csr": 0x680, "NoRestriction": 1})

        # hstatus: SPVP=1 (bit 8)
        self.genInstruction("LUI##RISCV", {"rd": 8, "simm20": 0, "NoRestriction": 1})
        self.genInstruction("ADDI##RISCV", {"rd": 8, "rs1": 8, "simm12": 0x100, "NoRestriction": 1})
        self.genInstruction("CSRRW#register#RISCV", {"rd": 0, "rs1": 8, "csr": 0x600, "NoRestriction": 1})

        # Set mstatus.SUM and vsstatus.SUM via CSRRW right before HLV.D
        # Use LUI to set x11/x12 before CSRRW (initializeRegister is async)
        self.genInstruction("LUI##RISCV", {"rd": 11, "simm20": 0x40, "NoRestriction": 1})  # x11 = 0x40000
        self.genInstruction("CSRRW#register#RISCV", {"rd": 0, "rs1": 11, "csr": 0x300, "NoRestriction": 1})  # mstatus
        self.genInstruction("LUI##RISCV", {"rd": 12, "simm20": 0x40, "NoRestriction": 1})  # x12 = 0x40000
        self.genInstruction("CSRRW#register#RISCV", {"rd": 0, "rs1": 12, "csr": 0x200, "NoRestriction": 1})  # vsstatus
        # 随机选择多个 GVA 进行 HLV.D 测试
        num_tests = min(5, len(mappings))
        test_indices = random.sample(range(len(mappings)), num_tests)

        for idx in test_indices:
            test_gva = mappings[idx]['gva']
            self.notice(f"Testing HLV.D with GVA: 0x{test_gva:08X}")

            self.genThread.initializeRegister("x1", "", test_gva)
            self.genInstruction("HLV.D##RISCV", {"rs1": 1, "rd": 2, "NoRestriction": 1})

        self.notice("Stress test completed")
        ptg.destroy()


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
