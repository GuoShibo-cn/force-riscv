# Phase 3 - 完整 Hypervisor 支持 · 实施方案

**日期**：2026-06-21  
**状态**：✅ 已完成 — 14/14 测试通过 Handcar ISS 验证 (2026-06-21)  
**依据**：Phase 1-2 完成两阶转译集成 + gap-analysis 识别的完整缺口  
**预计周期**：~30 个工作日（6 周，分 3 个迭代）

---

## 0. 上下文

### Phase 1-2 交付物（已完成）

| 阶段 | 交付物 |
|------|--------|
| Phase 1 | PTG 后端集成（678 行 ctypes 封装），两阶转译 basic path |
| Phase 2 | SvMode 8 模式扩展、18 个两阶 API、setupPtgCSRs、Guest Fault 10 场景、Handcar ISS 验证、性能基准 |

### Phase 3 目标

**让 FORCE-RISCV 支持**
**完整的 RISC-V Hypervisor Extension v1.0**：

- ✅ 两阶地址转译（Phase 1-2 已完成）
- ⏳ Hypervisor 指令（HFENCE/HLV/HSV/HINVAL）
- ⏳ Guest 异常系统（Guest Page Fault、虚拟化异常）
- ⏳ 虚拟化中断（VS-SWI/Timer/External）
- ⏳ HS/VS/VU 特权级切换
- ⏳ VMID 管理
- ⏳ 多 Hart 隔离
- ⏳ Stress 和嵌套异常测试

---

## 1. 工作量分解（按优先级）

| 优先级 | 子任务 | 预计工作量 | 依赖 |
|--------|--------|-----------|------|
| **P0** | 3.1 多 Hart 隔离（hgatp/vsatp） | 3-4 天 | Phase 2.2 setupPtgCSRs |
| **P1** | 3.2 嵌套异常链测试 | 4-5 天 | Phase 2.5 Guest Fault |
| **P2** | 3.3 Hypervisor 指令（HFENCE/HLV/HSV） | 5-6 天 | 1. 指令定义 XML 2. Handcar ISS |
| **P3** | 3.4 缺失 CSR 补齐 | 2-3 天 | 无 |
| **P4** | 3.5 虚拟化异常系统 | 3-4 天 | 1. 异常类型定义 2. GenExceptionAgent |
| **P5** | 3.6 虚拟化中断 | 3-4 天 | 1. hvip/hideleg 2. 中断分发逻辑 |
| **P6** | 3.7 HS/VS 特权切换 | 4-5 天 | 1. SwitchPrivilegeSolver 2. SRET 增强 |
| **P7** | 3.8 VMID 管理 | 2-3 天 | hgatp 定义已完成 |
| **P8** | 3.9 Stress 测试套件 | 3-4 天 | Phase 2.7 Perf |

**总计**：~30 天（含风险缓冲）

---

## 2. Phase 3.1 — 多 Hart 隔离（Per-Hart CSR）

### 2.1 目标

让每个 Hart 独立管理 `hgatp`/`vsatp`，支持多 VM 跨 Hart 迁移测试。

### 2.2 当前限制

当前 `setupPtgCSRs` 设置全局 CSR：

```python
# py/riscv/GenThreadRISCV.py:231
def setupPtgCSRs(self, vs_mode, g_mode, ...):
    self.setRegisterField("satp", "MODE", vs_mode_value, hart=0)
    self.setRegisterField("hgatp", "MODE", g_mode_value, hart=0)
```

仅设置 hart=0，其他 Hart 共享未初始化的 CSR 值。

### 2.3 改动清单

#### 改动 1：`GenThreadRISCV.setupPtgCSRs` 扩展支持所有 Hart

```python
# py/riscv/GenThreadRISCV.py
def setupPtgCSRs(self, vs_mode, g_mode, vs_root_gpa=None, g_root_spa=None):
    """配置两阶地址转译 CSR，支持多 Hart 隔离"""
    hart_count = self.getGlobalState("NumChips") * self.getGlobalState("NumCores") * self.getGlobalState("NumThreads")
    
    for hart_id in range(hart_count):
        # VS-stage (vsatp)
        self.setRegisterField("vsatp", "MODE", vs_mode_value, hart=hart_id)
        if vs_root_gpa is not None:
            self.setRegisterField("vsatp", "PPN", vs_root_gpa >> 12, hart=hart_id)
        
        # G-stage (hgatp)
        self.setRegisterField("hgatp", "MODE", g_mode_value, hart=hart_id)
        if g_root_spa is not None:
            self.setRegisterField("hgatp", "PPN", g_root_spa >> 12, hart=hart_id)
        
        # VMID (可选：每个 Hart 独立 VMID，或共享)
        vmid = self.random32(0, 0xFFFF)
        self.setRegisterField("hgatp", "VMID", vmid, hart=hart_id)
```

**注意**：VMID 可配置为全局共享（VM 迁移场景）或 per-hart（VM 隔离场景）

#### 改动 2：测试模板 `ptg_multi_hart_force.py`（新文件）

```python
# tests/riscv/ptg_multi_hart_force.py
class MainSequence(Sequence):
    def generate(self, **kargs):
        # 配置：4 Hart，每 Hart 独立 VS/G-stage
        hart_count = 4
        for hart_id in range(hart_count):
            # 每个 Hart 独立的 GVA 空间：[hart_id * 4GB, (hart_id+1) * 4GB)
            gva_base = hart_id * 0x1_0000_0000
            gva_size = 0x1_0000_0000
            
            self.genInstruction("ADD##RISCV", {
                "Addresses": {
                    "VsMode": {
                        "Base": gva_base,
                        "Size": gva_size,
                        "VsPagingMode": "Sv39",
                        "GPagingMode": "Sv39x4",
                    }
                }
            })
```

#### 改动 3：Handcar ISS 验证 per-hart CSR 隔离

修改 `ptg_iss_walk_force.py` 验证每个 Hart 的页表 walk：

```python
for hart_id in range(hart_count):
    # 切换到对应 Hart
    # 读取 hgatp/vsatp，验证 MODE/PPN/VMID
    # 执行两阶翻译，验证 SPA
```

### 2.4 验证步骤

1. 编译通过：`make -j`
2. 测试通过：`bin/friscv -t tests/riscv/ptg_multi_hart_force.py`
3. Handcar ISS：每个 Hart 的 CSR 值正确，翻译结果互不干扰
4. PTG dump_path：每个 Hart 的页表独立，无 GPA 重叠

### 2.5 验收标准

- [ ] `setupPtgCSRs` 支持 per-hart VMID 参数
- [ ] 测试模板验证 8 Hart（2 chip × 2 core × 2 thread）隔离
- [ ] Handcar ISS walk 验证每个 Hart 的 SPA 一致性
- [ ] VM 迁移场景：Hart 0 的 VMID=100，Hart 1 的 VMID=200，切换后翻译正确

---

## 3. Phase 3.2 — 嵌套异常链测试

### 3.1 目标

测试 guest fault → VS trap → M trap 的完整异常委托链，覆盖 `hedeleg`/`hideleg` 的嵌套语义。

### 3.2 当前限制

Phase 2.5 只测试单点注入：

```python
gen_thread.inject_implicit_guest_fault(gva, cause=1)  # fault_code=1 (InvalidPTE)
```

缺少嵌套场景：

- Guest fault 注入 VS trap → VS trap 再次注入 → M trap
- 同一 GVA 的 VS fault 和 G fault 同时发生
- `hedeleg` 委托失败（delegate bit 未设置）

### 3.3 改动清单

#### 改动 1：测试模板 `ptg_nested_exception_force.py`（新文件）

```python
# tests/riscv/ptg_nested_exception_force.py
class MainSequence(Sequence):
    def generate(self, **kargs):
        # 配置 VS-stage 页表：GVA 0x1000 → GPA 0x2000 → SPA 0x3000
        self.setupPtgCSRs(vs_mode="Sv39", g_mode="Sv39x4")
        
        # 场景 1: Guest fault → VS trap → M trap
        # 注入 implicit VS fault (cause=6, PermRWXViolation)
        gva = 0x1000
        self.inject_implicit_guest_fault(gva, cause=6)
        
        # 设置 VS trap handler (V-mode exception handler)
        self.setVsTrapHandler(...)
        
        # 在 VS trap handler 中再次注入 fault
        self.inject_implicit_guest_fault(0x2000, cause=1)
        
        # 设置 M trap handler (M-mode exception handler)
        self.setMTrapHandler(...)
        
        # 生成测试指令
        self.genInstruction("LW##RISCV", {
            "Addresses": {"Base": gva, "Size": 0x1000}
        })
```

#### 改动 2：VS trap handler 模板

```python
def setVsTrapHandler(self):
    """配置 VS-mode 陷阱处理器"""
    # 设置 vstvec（VS trap handler 入口）
    vstvec_value = 0x8000_0000  # VS trap handler 地址
    self.setRegister("vstvec", vstvec_value)
    
    # 在 vstvec 处生成 handler 代码
    handler_code = [
        "CSRRS##RISCV",  # 读取 vscause
        "SRET##RISCV",   # 返回 VS
    ]
    self.genInstructions(handler_code, {
        "Addresses": {"Base": vstvec_value}
    })
```

#### 改动 3：`hedeleg`/`hideleg` 配置

```python
def setupDelegation(self):
    """配置异常/中断委托"""
    # hedeleg: 委托 exception to VS
    # 设置 delegation bit 13 (Guest Instruction Page Fault)
    hedeleg_value = (1 << 13) | (1 << 12)  # 委托 load/store fault
    self.setRegister("hedeleg", hedeleg_value)
    
    # hideleg: 委托 interrupt to VS
    hideleg_value = (1 << 10) | (1 << 12) | (1 << 14)  # 委托 VS SW/Timer/External
    self.setRegister("hideleg", hideleg_value)
```

### 3.4 验证步骤

1. 编译通过：`make -j`
2. 测试通过：`bin/friscv -t tests/riscv/ptg_nested_exception_force.py`
3. Handcar ISS 验证异常链：
   - 第一次 fault：触发 VS trap（vstval = GVA，vscause = 6）
   - 第二次 fault（嵌套）：VS trap 中再次注入，触发 M trap（mtval = GVA，mcause = 13）
4. 检查 `hedeleg`/`hideleg` 委托逻辑：
   - 当 delegation bit 设置：异常直接进 VS
   - 未设置：保留在 M 或 HS

### 3.5 验收标准

- [ ] 支持 3 层嵌套异常：Guest → VS → M
- [ ] 10 个嵌套场景全部 PASS（覆盖所有 cause 组合）
- [ ] `hedeleg`/`hideleg` 委托逻辑验证正确
- [ ] Handcar ISS 异常链追踪正确

---

## 4. Phase 3.3 — Hypervisor 指令（HFENCE/HLV/HSV）

### 4.1 目标

定义 H-extension 的全部 12 条指令，支持 HLV/HSV 生成和 HFENCE TLB flush。

### 4.2 指令清单

#### HFENCE/HINVAL（TLB Flush 指令）

| 指令 | 操作数 | 功能 |
|------|--------|------|
| HFENCE.VVMA | vsid, vaddr | VS-stage TLB flush |
| HFENCE.GVMA | vmid, gaddr | G-stage TLB flush |
| HINVAL.VVMA | vsid, vaddr | VS 无效化（Zihint） |
| HINVAL.GVMA | vmid, gaddr | G 无效化（Zihint） |

#### HLV（Hypervisor 虚拟读取）

| 指令 | 功能 | 操作数 |
|------|------|--------|
| HLV.B | 读虚拟 Byte（有符号） | rs1, rd |
| HLV.H | 读虚拟 Halfword（有符号） | rs1, rd |
| HLV.W | 读虚拟 Word（有符号） | rs1, rd |
| HLV.D | 读虚拟 Double（有符号） | rs1, rd |
| HLV.BU | 读虚拟 Byte（无符号） | rs1, rd |
| HLV.HU | 读虚拟 Half（无符号） | rs1, rd |
| HLV.WU | 读虚拟 Word（无符号） | rs1, rd |

#### HSV（Hypervisor 虚拟写入）

| 指令 | 功能 | 操作数 |
|------|------|--------|
| HSV.B | 写虚拟 Byte | rs1, rs2 |
| HSV.H | 写虚拟 Half | rs1, rs2 |
| HSV.W | 写虚拟 Word | rs1, rs2 |
| HSV.D | 写虚拟 Double | rs1, rs2 |

#### HLVX（执行权限读取）

| 指令 | 功能 |
|------|------|
| HLVX.HU | 执行权限读 Half（无符号） |
| HLVX.WU | 执行权限读 Word（无符号） |
| HLVX.D | 执行权限读 Double |

### 4.3 改动清单

#### 改动 1：`priv_instructions.xml` 扩展

```xml
<!-- riscv/arch_data/instr/priv_instructions.xml -->
<!-- HFENCE.VVMA -->
<instruction mnemonic="HFENCE.VVMA" category="Hypervisor"
             encoding="0010001 rs2 rs1 000 00000 1110011"
             class="HVInstruction">
  <operand type="vsid" field="rs2" width="5"/>
  <operand type="vaddr" field="rs1" width="5"/>
  <description>Flush VS-stage TLB for (vsid, vaddr) mapping</description>
</instruction>

<!-- HFENCE.GVMA -->
<instruction mnemonic="HFENCE.GVMA" category="Hypervisor"
             encoding="0110001 rs2 rs1 000 00000 1110011"
             class="HVInstruction">
  <operand type="vmid" field="rs2" width="5"/>
  <operand type="gaddr" field="rs1" width="5"/>
  <description>Flush G-stage TLB for (vmid, gaddr) mapping</description>
</instruction>

<!-- HLV.B -->
<instruction mnemonic="HLV.B" category="Hypervisor"
             encoding="0110000 00000 rs1 100 rd 1110011"
             class="HVLoadInstruction">
  <operand type="rs1" width="5"/>
  <operand type="rd" width="5"/>
  <description>Hypervisor virtual load byte (signed)</description>
</instruction>

<!-- HLV.H, HLV.W, HLV.D, HLV.BU, HLV.HU, HLV.WU -->
<!-- HSV.B, HSV.H, HSV.W, HSV.D -->
<!-- ... 类似定义 ... -->
```

#### 改动 2：`instruction_tree.py` 添加指令定义

```python
# py/DV/riscv/trees/instruction_tree.py
hypervisor_instructions = [
    # HFENCE/HINVAL
    "HFENCE.VVMA##RISCV",
    "HFENCE.GVMA##RISCV",
    "HINVAL.VVMA##RISCV",
    "HINVAL.GVMA##RISCV",
    
    # HLV (Read)
    "HLV.B##RISCV",
    "HLV.H##RISCV",
    "HLV.W##RISCV",
    "HLV.D##RISCV",
    "HLV.BU##RISCV",
    "HLV.HU##RISCV",
    "HLV.WU##RISCV",
    
    # HSV (Write)
    "HSV.B##RISCV",
    "HSV.H##RISCV",
    "HSV.W##RISCV",
    "HSV.D##RISCV",
    
    # HLVX (Execute)
    "HLVX.HU##RISCV",
    "HLVX.WU##RISCV",
    "HLVX.D##RISCV",
]
```

#### 改动 3：Handcar ISS 支持

修改 Handcar 以支持 HLV/HSV 指令的语义：

```cpp
// riscv/src/GenExceptionAgentRISCV.cc
void HVLoadInstruction::execute(ExecutionContext* ctx) {
    // 1. 读取 rs1 (GVA)
    uint64_t gva = ctx->getRegister(rs1);
    
    // 2. VS-stage 翻译：GVA → GPA
    auto [gpa, fault_code, fault_level] = translateVsStage(gva, ctx->vsatp);
    
    // 3. G-stage 翻译：GPA → SPA
    auto [spa, g_fault_code, g_fault_level] = translateGStage(gpa, ctx->hgatp);
    
    // 4. 读取 SPA 内存
    uint64_t value = ctx->readMemory(spa, size);
    
    // 5. 写入 rd
    ctx->setRegister(rd, signExtend(value));
}
```

#### 改动 4：测试模板 `ptg_hlv_force.py`（新文件）

```python
# tests/riscv/ptg_hlv_force.py
class MainSequence(Sequence):
    def generate(self, **kargs):
        # 配置 VS/G-stage 页表
        self.setupPtgCSRs(vs_mode="Sv39", g_mode="Sv39x4")
        
        # 在 GVA 0x1000 处生成数据
        gva = 0x1000
        self.genVM(0x1000, 0x2000, 0x3000)
        
        # 生成 HLV.W 指令
        self.genInstruction("HLV.W##RISCV", {
            "Addresses": {"Base": gva, "Size": 0x1000}
        })
        
        # 生成 HSV.W 写入
        self.genInstruction("HSV.W##RISCV", {
            "Addresses": {"Base": gva, "Size": 0x1000}
        })
```

### 4.4 验证步骤

1. 编译通过：`make -j && make enums`
2. 指令生成：生成 HLV/HSV 指令并验证编码正确
3. Handcar ISS 执行 HLV/HSV 验证翻译语义
4. HFENCE 验证 TLB flush 后重新翻译
5. 测试覆盖：所有 12 条指令 × 2-3 个场景

### 4.5 验收标准

- [ ] 12 条 H-extension 指令全部定义
- [ ] Handcar ISS 正确执行 HLV/HSV 语义
- [ ] HFENCE.VVMA/GVMA TLB flush 验证正确
- [ ] 测试模板覆盖所有 12 条指令

---

## 5. Phase 3.4 — 缺失 CSR 补齐

### 5.1 目标

补齐 `hvipr1-12`、`htimedelta`、`henvcfgH`、`hstateen0-3`、`vscounteren`、`vsstateen0-3` 等缺失 CSR。

### 5.2 CSR 清单

#### 虚拟中断优先级寄存器

| 寄存器 | 地址 | 功能 |
|--------|------|------|
| hvipr1 | 0x660 | 虚拟中断优先级 1 |
| hvipr2 | 0x661 | 虚拟中断优先级 2 |
| ... | 0x662-0x66C | hvipr3-12 |

#### Hypervisor 时间虚拟化

| 寄存器 | 地址 | 功能 |
|--------|------|------|
| htimedelta | 0x605 | VS-time 增量（相对于 HS-time） |

#### 环境配置

| 寄存器 | 地址 | 功能 |
|--------|------|------|
| henvcfgH | 0x61A | henvcfg 的高 32 位（RV32 兼容） |

#### 状态使能

| 寄存器 | 地址 | 功能 |
|--------|------|------|
| hstateen0 | 0x610 | 状态使能 0 |
| hstateen1 | 0x611 | 状态使能 1 |
| hstateen2 | 0x612 | 状态使能 2 |
| hstateen3 | 0x613 | 状态使能 3 |
| vsstateen0 | 0x210 | VS 状态使能 0 |
| vsstateen1 | 0x211 | VS 状态使能 1 |
| vsstateen2 | 0x212 | VS 状态使能 2 |
| vsstateen3 | 0x213 | VS 状态使能 3 |

#### VS 计数器使能

| 寄存器 | 地址 | 功能 |
|--------|------|------|
| vscounteren | 0x206 | VS-mode 计数器使能 |

### 5.3 改动清单

#### 改动 1：`system_registers_rv64.xml` 添加 CSR

```xml
<!-- riscv/arch_data/reg/system_registers_rv64.xml -->

<!-- hvipr1-12 (虚拟中断优先级寄存器) -->
<register name="hvipr1" index="0x660" class="HVRegister">
  <field name="ID" bits="10-0" class="ValueField"/>
  <field name="Priority" bits="63-11" class="PriorityField"/>
  <description>Virtual interrupt priority 1</description>
</register>

<register name="hvipr2" index="0x661" class="HVRegister">
  <!-- 类似定义，hvipr3-12 省略 -->
</register>

<!-- htimedelta (时间增量化) -->
<register name="htimedelta" index="0x605">
  <field name="Value" bits="63-0" class="ValueField"/>
  <description>Delta applied to VS-mode time CSR</description>
</register>

<!-- henvcfgH (环境配置高位，RV32 兼容) -->
<register name="henvcfgH" index="0x61A">
  <field name="STCE" bits="63" class="STCEField"/>
  <field name="PBMTE" bits="62" class="PBMTEField"/>
  <!-- 高位字段 -->
</register>

<!-- hstateen0-3 (状态使能寄存器) -->
<register name="hstateen0" index="0x610">
  <field name="SE0" bits="0" class="ValueField"/>
  <field name="ENVCFG" bits="31" class="ValueField"/>
  <!-- 更多字段 -->
</register>

<!-- vscounteren (VS 计数器使能) -->
<register name="vscounteren" index="0x206">
  <field name="TM" bits="1" class="ValueField"/>  <!-- Machine timer 使能 -->
  <field name="CY" bits="0" class="ValueField"/>  <!-- Cycle counter 使能 -->
  <field name="IR" bits="2" class="ValueField"/>  <!-- Instret counter 使能 -->
  <!-- HPM 计数器 3-31 使能 (bits 3-31) -->
</register>

<!-- vsstateen0-3 (VS 状态使能，类似 hstateen) -->
<register name="vsstateen0" index="0x210">
  <!-- 字段类似 hstateen0 -->
</register>
```

#### 改动 2：重新生成枚举

```bash
cd /home/guoshibo/force-riscv && make enums
```

#### 改动 3：测试模板 `ptg_missing_csrs_force.py`（新文件）

```python
# tests/riscv/ptg_missing_csrs_force.py
class MainSequence(Sequence):
    def generate(self, **kargs):
        # 读取所有 CSR
        csrs = ["hvipr1", "htimedelta", "henvcfgH", "hstateen0", "vscounteren", "vsstateen0"]
        for csr in csrs:
            self.genInstruction("CSRRS##RISCV", {
                "csr": csr,
                "Value": 0,
            })
```

### 5.4 验证步骤

1. 枚举生成：`make enums`
2. 编译通过：`make -j`
3. Handcar ISS 验证所有缺失 CSR 可读写
4. 测试覆盖：10+ 个缺失 CSR

### 5.5 验收标准

- [ ] 10+ 个缺失 CSR 全部定义
- [ ] XML 字段定义完整
- [ ] Handcar ISS 支持 CSR 读写

---

## 6. Phase 3.5 — 虚拟化异常系统

### 6.1 目标

实现 Guest Page Fault 异常注入、虚拟化异常（VirtualInstruction）和 Guest 指令 page fault。

### 6.2 异常类型

| Code | 名称 | 触发条件 |
|------|------|---------|
| 20 | VirtualInstruction | 在 VS-mode 执行 HS-mode 指令 |
| 22 | GuestInstructionPageFault | VS-stage 翻译失败（指令读取） |
| 23 | GuestLoadPageFault | G-stage 翻译失败（Load） |
| 24 | GuestStorePageFault | G-stage 翻译失败（Store） |

### 6.3 改动清单

#### 改动 1：`ExceptionClass.py` 添加异常类型

```python
# py/riscv/exception_handlers/ExceptionClass.py

class VirtualInstruction(Exception):
    """虚拟化指令异常 (code=20)"""
    code = 20

class GuestInstructionPageFault(Exception):
    """VS-stage 指令读取 page fault (code=22)"""
    code = 22

class GuestLoadPageFault(Exception):
    """G-stage load page fault (code=23)"""
    code = 23

class GuestStorePageFault(Exception):
    """G-stage store page fault (code=24)"""
    code = 24
```

#### 改动 2：`GenExceptionAgentRISCV.cc` 处理新异常

```cpp
// riscv/src/GenExceptionAgentRISCV.cc
if (exception_code == 20) {  // VirtualInstruction
    // HS 模式执行了 VS-mode 指令
    ctx->setRegister("mtval", ctx->pc);
    ctx->enterMModeTrap();
}

if (exception_code == 22) {  // GuestInstructionPageFault
    // VS-stage 翻译失败（指令 fetch）
    ctx->setRegister("tval", fault_level);
    ctx->setRegister("tinst", faultingInstr);
    ctx->enterVsModeTrap();
}

// ... GuestLoadPageFault(23), GuestStorePageFault(24) 类似
```

#### 改动 3：测试模板 `ptg_guest_fault_complete_force.py`（新文件）

```python
# tests/riscv/ptg_guest_fault_complete_force.py
class MainSequence(Sequence):
    def generate(self, **kargs):
        # 场景 1: GuestLoadPageFault (code=23)
        self.inject_implicit_guest_fault(gva=0x1000, cause=23)
        
        # 场景 2: GuestStorePageFault (code=24)
        self.inject_implicit_guest_fault(gva=0x2000, cause=24)
        
        # 场景 3: GuestInstructionPageFault (code=22)
        # 在 VS-stage 设置无效页表项，指令 fetch 失败
        self.setupPtgCSRs(vs_mode="Sv39", g_mode="Sv39x4")
        self.invalidateVsPte(gva=0x3000)
```

### 6.4 验证步骤

1. 异常类型定义完整
2. 编译通过：`make -j`
3. 测试模板覆盖全部 8 个异常类型
4. Handcar ISS 异常追踪正确

### 6.5 验收标准

- [ ] 8 个 guest 异常类型全部支持
- [ ] 异常触发和委托逻辑正确（hedeleg 生效）
- [ ] 10+ 个异常场景测试覆盖

---

## 7. Phase 3.6 — 虚拟化中断

### 7.1 目标

实现虚拟化 supervisor 中断（VS-SWI/Timer/External），支持 `hvip`/`hideleg` 中断委托。

### 7.2 中断类型

| Interrupt | 名称 | 触发机制 |
|-----------|------|----------|
| 10 | VS Supervisor Software Interrupt | hvip 寄存器写入 |
| 12 | VS Supervisor Timer Interrupt | htimedelta + stimecmp |
| 14 | VS Supervisor External Interrupt | 外部事件映射 |

### 7.3 改动清单

#### 改动 1：`GenExceptionAgentRISCV.cc` 处理 VS 中断

```cpp
// riscv/src/GenExceptionAgentRISCV.cc
bool shouldDelegateToVs(uint32_t interrupt_id) {
    // hideleg bit 对应此中断是否委托到 VS
    uint64_t hideleg = ctx->getRegister("hideleg");
    return (hideleg >> interrupt_id) & 0x1;
}

if (interrupt_id == 10 || interrupt_id == 12 || interrupt_id == 14) {
    if (shouldDelegateToVs(interrupt_id)) {
        ctx->enterVsModeTrap();
    } else {
        ctx->enterHsModeTrap();
    }
}
```

#### 改动 2：测试模板 `ptg_vs_interrupts_force.py`（新文件）

```python
# tests/riscv/ptg_vs_interrupts_force.py
class MainSequence(Sequence):
    def generate(self, **kargs):
        # 配置 hideleg 委托 VS SWI
        hideleg_value = 1 << 10  # 委托 VS SWI
        self.setRegister("hideleg", hideleg_value)
        
        # 配置 hvip 触发 VS SWI
        hvip_value = 1 << 10  # 触发 VS SWI pending
        self.setRegister("hvip", hvip_value)
        
        # 设置 VS trap handler
        self.setVsTrapHandler(...)
        
        # 生成等待中断的指令
        self.genInstruction("WFI##RISCV")
```

### 7.4 验证步骤

1. 编译通过：`make -j`
2. 测试覆盖：3 种 VS 中断类型
3. Handcar ISS 中断追踪正确

### 7.5 验收标准

- [ ] VS-SWI/Timer/External 中断支持
- [ ] `hideleg` 委托逻辑正确
- [ ] `hvip` 中断触发逻辑正确
- [ ] 测试覆盖 3 种中断类型

---

## 8. Phase 3.7 — HS/VS 特权切换

### 8.1 目标

扩展 `SwitchPrivilegeSolverRISCV` 支持 M ↔ HS ↔ VS ↔ VU 的完整特权链。

### 8.2 当前限制

当前 `SwitchPrivilegeSolverRISCV` 仅支持 M↔S↔U 切换，HS 和 VS 作为 S-mode 的子类型，而非独立特权级。

### 8.3 改动清单

#### 改动 1：`SwitchPrivilegeSolverRISCV.cc` 添加 HS/VS 切换

```cpp
// riscv/src/SwitchPrivilegeSolverRISCV.cc
SwitchDecision decideVsToHs(ExecutionContext* ctx) {
    // VS-mode → HS-mode 切换
    uint64_t vscause = ctx->getRegister("vscause");
    uint64_t mstatus = ctx->getRegister("mstatus");
    
    // 检查 hstatus.SPV
    if (hstatus & HSTATUS_SPV) {
        // SRET from VS → HS
        return SWITCH_SRET;
    }
    
    return NO_SWITCH;
}

SwitchDecision decideHsToVs(ExecutionContext* ctx) {
    // HS-mode → VS-mode 切换
    uint64_t hstatus = ctx->getRegister("hstatus");
    uint64_t mstatus = ctx->getRegister("mstatus");
    
    // 检查 hstatus.SPVP, hstatus.SPV
    if (hstatus & HSTATUS_SPV) {
        // SRET from HS → VS
        return SWITCH_SRET;
    }
    
    return NO_SWITCH;
}
```

#### 改动 2：测试模板 `ptg_hs_vs_switch_force.py`（新文件）

```python
# tests/riscv/ptg_hs_vs_switch_force.py
class MainSequence(Sequence):
    def generate(self, **kargs):
        # 配置 M → HS → VS 切换链
        self.setupPrivilegeSwitch([M, HS, VS])
        
        # 在 M 模式下执行指令
        self.genInstruction("ADD##RISCV", {"PrivilegeLevel": "M"})
        
        # 切换到 HS
        self.genInstruction("MRET##RISCV", {"TargetMode": "HS"})
        
        # 在 HS 模式执行
        self.genInstruction("ADD##RISCV", {"PrivilegeLevel": "HS"})
        
        # 切换到 VS
        self.genInstruction("SRET##RISCV", {"TargetMode": "VS"})
        
        # 在 VS 模式执行
        self.genInstruction("ADD##RISCV", {"PrivilegeLevel": "VS"})
```

### 8.4 验收标准

- [ ] M ↔ HS ↔ VS ↔ VU 全链路切换
- [ ] SRET/MRET 目标模式正确
- [ ] 特权链测试覆盖完整

---

## 9. Phase 3.8 — VMID 管理

### 9.1 目标

实现 VMID 分配、回收和多 VM 隔离策略。

### 9.2 改动清单

#### 改动 1：`GenThreadRISCV.py` 添加 VMID 分配器

```python
class VMIDAllocator:
    def __init__(self):
        self.allocated_vmids = set()
        self.max_vmid = 0xFFFF  # 16-bit VMID space
    
    def allocate(self):
        """分配 VMID"""
        vmid = random.randint(1, self.max_vmid)
        while vmid in self.allocated_vmids:
            vmid = random.randint(1, self.max_vmid)
        self.allocated_vmids.add(vmid)
        return vmid
    
    def release(self, vmid):
        """释放 VMID"""
        self.allocated_vmids.discard(vmid)
```

#### 改动 2：测试模板 `ptg_vmid_isolation_force.py`（新文件）

```python
# tests/riscv/ptg_vmid_isolation_force.py
class MainSequence(Sequence):
    def generate(self, **kargs):
        # 分配 4 个 VM
        allocator = VMIDAllocator()
        vmids = [allocator.allocate() for _ in range(4)]
        
        for vm_id in range(len(vmids)):
            vmid = vmids[vm_id]
            # 每个 VM 独立的 G-stage
            self.setRegisterField("hgatp", "VMID", vmid)
            # 测试 VM 隔离
```

### 9.3 验收标准

- [ ] VMID 分配/回收逻辑正确
- [ ] 多 VM 隔离测试通过
- [ ] VM 切换场景（VMID 回收复用）测试覆盖

---

## 10. Phase 3.9 — Stress 测试套件

### 10.1 目标

验证 Hypervisor 扩展在极端场景下的稳健性。

### 10.2 测试场景

#### Stress 1: 10K+ Mappings 两阶翻译

```python
# tests/riscv/ptg_stress_large_force.py
class MainSequence(Sequence):
    def generate(self, **kargs):
        # 配置 10K mappings 的两阶页表
        for i in range(10000):
            gva = 0x1_0000_0000 + i * 0x1000
            gpa = 0x2_0000_0000 + i * 0x1000
            spa = 0x3_0000_0000 + i * 0x1000
            self.genVM(gva, gpa, spa, page_size="4K")
```

#### Stress 2: ASID Wrap

```python
# tests/riscv/ptg_stress_asid_force.py
class MainSequence(Sequence):
    def generate(self, **kargs):
        # 生成 65536+ ASID，触发 wrap-around
        for asid in range(65536):
            self.setRegisterField("satp", "ASID", asid)
            # 测试 TLB 刷新
```

#### Stress 3: VM Context Switch

```python
# tests/riscv/ptg_stress_vm_switch_force.py
class MainSequence(Sequence):
    def generate(self, **kargs):
        # 配置 4 个 VM，连续切换 1000 次
        for _ in range(1000):
            vm_id = random.randint(0, 3)
            self.switchVM(vm_id)
```

### 10.3 验收标准

- [ ] 10K mappings 翻译正确性验证
- [ ] ASID wrap 后 TLB 正确刷新
- [ ] VM context switch 性能测试（<100ms/switch）
- [ ] 连续 1000 次 VM 切换无错误

---

## 11. 时间规划

### Iteration 1（Week 1-2）：核心基础设施

| Task | 工作量 |
|------|--------|
| 3.1 多 Hart 隔离 | 3-4 天 |
| 3.2 嵌套异常链测试 | 4-5 天 |
| 3.3 Hypervisor 指令 | 5-6 天 |

### Iteration 2（Week 3-4）：完整性支持

| Task | 工作量 |
|------|--------|
| 3.4 缺失 CSR 补齐 | 2-3 天 |
| 3.5 虚拟化异常系统 | 3-4 天 |
| 3.6 虚拟化中断 | 3-4 天 |

### Iteration 3（Week 5-6）：高级功能

| Task | 工作量 |
|------|--------|
| 3.7 HS/VS 特权切换 | 4-5 天 |
| 3.8 VMID 管理 | 2-3 天 |
| 3.9 Stress 测试套件 | 3-4 天 |

---

## 12. 风险与缓解

### Risk 1: Handcar ISS Hypervisor 支持不完整

**风险**：Handcar (Spike fork) 可能未完全支持 H-extension 的所有指令和异常。

**缓解**：
- 先验证 Spike 参考实现的 Hypervisor 支持
- Handcar 不支持的指令暂时跳过（记录在测试模板中）

### Risk 2: Guest Fault 注入的边界条件

**风险**：Phase 2.5 的 guest fault 可能未覆盖所有边界条件（如同时 VS/G fault）。

**缓解**：
- 在 3.2 嵌套异常测试中增加边界场景
- 与 PTG 团队保持沟通，确认边界条件

### Risk 3: VMID 管理复杂度

**风险**：VMID 回收策略可能引入难以调试的 bug。

**缓解**：
- VMID 分配器独立模块，可单独测试
- 在测试模板中验证 VMID 隔离性

---

## 13. 修订日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-06-21 | 初始版本 |
