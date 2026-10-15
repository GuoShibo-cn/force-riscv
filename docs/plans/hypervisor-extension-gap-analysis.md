# RISC-V Hypervisor Extension 完整差距分析

## RISC-V H-Extension 规范核心内容 (v1.0)

### 1. 特权级扩展
- HS-mode (Hypervisor Supervisor) - 新的特权级
- VS-mode (Virtual Supervisor) - 虚拟化的 S-mode
- VU-mode (Virtual User) - 虚拟化的 U-mode

### 2. 两阶地址转译 (Two-Stage Translation)
- VS-stage: GVA → GPA (via vsatp, 使用 Sv39/Sv48/Sv39x4/Sv48x4)
- G-stage: GPA → SPA (via hgatp, 使用 Sv39x4/Sv48x4)
- 页表格式扩展 (R/W/X/U/G/D/A + RSW2 + N-bit)

### 3. Hypervisor CSR 寄存器 (~30个)

#### Hypervisor 控制寄存器 (HS-mode)
| 寄存器 | 地址 | 功能 | 项目现状 |
|--------|------|------|---------|
| hstatus | 0x600 | Hypervisor 状态 | ✅ 已定义，字段已按 Spike mask 补齐 |
| hedeleg | 0x602 | 异常委托到 VS | ✅ 已定义 |
| hideleg | 0x603 | 中断委托到 VS | ✅ 已定义 |
| hie | 0x604 | Hypervisor 中断使能 | ✅ 已定义（部分字段） |
| hip | 0x644 | Hypervisor 中断挂起 | ✅ 已定义（部分字段） |
| hvien | 0x608 | 虚拟中断使能 | ✅ 已定义 |
| hvictl | 0x609 | 虚拟中断控制 | ✅ 已定义，字段已按 Spike AIA mask 补齐 |
| hvip | 0x645 | Hypervisor VS 中断挂起 | ✅ 已定义 |
| hvipr1-12 | 0x660-66C | 虚拟中断优先级 | ❌ 缺失 |
| htimedelta | 0x605 | 时间增量 | ❌ 缺失 |
| hcounteren | 0x606 | 计数器使能 | ✅ 已定义 |
| hgeie | 0x607 | 外部中断使能 | ✅ 已定义 |
| hgeip | 0xE12 | 外部中断挂起 | ✅ 已定义 |
| htval | 0x643 | 陷阱值 | ✅ 已定义 |
| htinst | 0x64A | 陷阱指令 | ✅ 已定义 |
| hgatp | 0x680 | G-stage 地址转译 | ✅ 已定义，字段已按 RV64 hgatp layout 补齐 |
| henvcfg | 0x60A | 环境配置 | ✅ 已定义，字段已按 Spike HENVCFG mask 补齐 |
| henvcfgH | 0x61A | 环境配置 high | ❌ 缺失 |
| hstateen0-3 | 0x610-613 | 状态使能 | ❌ 缺失 |

#### VS-mode 寄存器 (虚拟化的 S-mode 寄存器)
| 寄存器 | 地址 | 功能 | 项目现状 |
|--------|------|------|---------|
| vsstatus | 0x200 | VS 状态 | ✅ 已定义 |
| vsie | 0x204 | VS 中断使能 | ✅ 已定义（空寄存器） |
| vsip | 0x244 | VS 中断挂起 | ✅ 已定义（空寄存器） |
| vstvec | 0x205 | VS 陷阱向量 | ✅ 已定义 |
| vscounteren | 0x206 | VS 计数器使能 | ❌ 缺失 |
| vsscratch | 0x240 | VS scratch | ✅ 已定义（部分） |
| vsepc | 0x241 | VS 异常 PC | ✅ 已定义 |
| vscause | 0x242 | VS 异常原因 | ✅ 已定义 |
| vstval | 0x243 | VS 陷阱值 | ✅ 已定义 |
| vsatp | 0x280 | VS 地址转译 | ✅ 已定义 |
| vsstateen0-3 | 0x210-213 | VS 状态使能 | ❌ 缺失 |

### 4. Hypervisor 指令

| 指令 | 功能 | 项目现状 |
|------|------|---------|
| HFENCE.VVMA | VS-stage TLB flush | ❌ 缺失 |
| HFENCE.GVMA | G-stage TLB flush | ❌ 缺失 |
| HINVAL.VVMA | VS-stage 无效化 (Zihint) | ❌ 缺失 |
| HINVAL.GVMA | G-stage 无效化 (Zihint) | ❌ 缺失 |
| HLV.B/H/W/D | Hypervisor 虚拟读 | ❌ 缺失 |
| HLV.BU/HU/WU | Hypervisor 虚拟读 (无符号) | ❌ 缺失 |
| HSV.B/H/W/D | Hypervisor 虚拟写 | ❌ 缺失 |
| HLVX.HU/W/UQ | Hypervisor 执行权限读 | ❌ 缺失 |

### 5. 虚拟化异常类型

| Exception Code | 描述 | 项目现状 |
|---------------|------|---------|
| 20 | 虚拟化指令异常 | ❌ 缺失 |
| 22 | Guest 页表异常 (load) | ❌ 缺失 |
| 23 | Guest 页表异常 (instr) | ❌ 缺失 |
| 24 | Guest 页表异常 (store) | ❌ 缺失 |

### 6. 虚拟化中断

| 中断号 | 描述 | 项目现状 |
|--------|------|---------|
| 10 | 虚拟化 supervisor 软件中断 | ❌ 缺失 |
| 12 | 虚拟化 supervisor 定时器中断 | ❌ 缺失 |
| 14 | 虚拟化 supervisor 外部中断 | ❌ 缺失 |

---

## 项目现状总结

### ✅ 已有的基础 (约 40% 完成度)

1. **枚举系统**：
   - `EVmRegimeType::HS` 和 `EVmRegimeType::VS` 已存在
   - `EPrivilegeLevelType::H` 已存在
   - 但缺少 VS-mode 和 VU-mode 的独立枚举

2. **寄存器定义**：
   - 大部分 HS-mode 和 VS-mode 寄存器已在 XML 中声明
   - `hstatus` 的主要字段已定义 (SPV, SP2V, SP2P, VSXL, VTVM, VTSR, etc.)
   - `hgatp` 寄存器已定义
   - `vsatp` 寄存器已定义
   - 但很多寄存器只有声明，没有字段细节（vsie/vsip 是空的）

3. **指令定义**：
   - MRET/SRET 已定义
   - **H-extension 专用指令完全缺失**

4. **异常处理**：
   - 基本的 M-mode 和 S-mode 异常已实现
   - 代码中有注释 "Hypervisor exceptions not supported" (GenExceptionAgentRISCV.cc:421)
   - Guest Page Fault 异常类型完全缺失

5. **特权切换**：
   - `SwitchPrivilegeSolverRISCV` 支持 M↔S↔U 切换
   - 通过 ECALL 机制实现
   - **不支持 M→HS→VS 的 hypervisor 切换链**

6. **虚拟内存**：
   - 单阶转译 (Sv32/Sv39/Sv48) 完整实现
   - PTE 有 stage 字段但未使用
   - 无 Sv39x4/Sv48x4 支持
   - 无 G-stage 页表定义

### ❌ 完全缺失的部分 (约 60%)

| 模块 | 缺失程度 | 工作量估计 |
|------|---------|-----------|
| Hypervisor 指令定义 | 100% | 高 (需要定义 12+ 条新指令) |
| Guest Page Fault 异常 | 100% | 中 |
| 虚拟化中断支持 | 100% | 高 |
| 两阶地址转译核心 | 100% | 高 |
| 缺失的 CSR 寄存器字段 | ~60% | 中 |
| HS/VS-mode 特权切换 | 100% | 高 |
| VMID 管理 | 100% | 中 |
| TLB flush (HFENCE) 语义 | 100% | 中 |
| hedeleg/hideleg 委托逻辑 | ~70% | 中 |

---

## 扩展到完整 H-Extension 的额外修改范围

### 新增模块（相对两阶转译计划）

#### A. Hypervisor 指令集 (4-5 天)
- `priv_instructions.xml` 添加 12+ 条 H-extension 指令
- HLV/HSV 需要新的操作数类型（虚拟化 Load/Store Operand）
- HFENCE/HINVAL 需要新的 Fence Operand 类型
- 指令编码需要遵循 H-extension spec

#### B. 虚拟化异常系统 (3-4 天)
- 新增 ExceptionCode: GuestInstrPageFault(22), GuestLoadPageFault(23), GuestStorePageFault(24)
- 新增 ExceptionCode: VirtualInstruction(20)
- 修改 GenExceptionAgentRISCV 处理这些新异常
- 异常委托逻辑 (hedeleg) 集成
- Guest Page Fault 的 htval/htinst 填充

#### C. 虚拟化中断系统 (3-4 天)
- 新增虚拟中断类型：VS-SWI(10), VS-Timer(12), VS-External(14)
- hvip 寄存器写入控制 VS 中断挂起
- hideleg 中断委托逻辑
- 虚拟中断与物理中断的映射关系

#### D. 特权级切换扩展 (3-4 天)
- SwitchPrivilegeSolverRISCV 扩展支持 HS 和 VS
- M→HS 切换 (通过 MRET with appropriate mstatus.MPP)
- HS→VS 切换 (通过 SRET with hstatus.SPV)
- VS→HS 切换 (通过 SRET)
- ECALL 的虚拟化语义 (U→VS, VS→HS, HS→M)

#### E. 缺失 CSR 完善 (2-3 天)
- hvien, hvictl, hvip, hvipr1-12 寄存器定义
- henvcfg, hstateen 寄存器定义
- vsie/vsip 的字段填充（映射到 hip/hvip）
- vsstateen 寄存器定义
- hgeip 寄存器定义

#### F. VMID 管理 (2-3 天)
- VMID 分配器（类似 ASID 管理）
- hgatp.VMID 字段生成
- VMID 回收策略
- VMID 与 address space 的关联

#### G. 其他 (1-2 天)
- htimedelta 虚拟化
- hcounteren 计数器虚拟化
- VU-mode 支持

---

## 工作量估算

| Phase | 内容 | 原始计划 | 扩展到 H-Ext | 增量 |
|-------|------|---------|-------------|------|
| 枚举/配置 | 枚举和 XML 扩展 | 1天 | 2天 | +1天 |
| PTE/XML | 页表定义 | 1天 | 1.5天 | +0.5天 |
| VmControlBlock | stage 感知 | 0.5天 | 0.5天 | 0 |
| TwoStageVmMapper | 核心组合器 | 2天 | 2天 | 0 |
| VmManager | 两阶管理 | 1天 | 1天 | 0 |
| VmFactory/Regime | 工厂扩展 | 0.5天 | 0.5天 | 0 |
| 配置文件 | 配置集成 | 0.5天 | 0.5天 | 0 |
| Python API | 用户接口 | 1天 | 1.5天 | +0.5天 |
| PTE 属性类 | 属性实现 | 0.5天 | 0.5天 | 0 |
| 编译/测试 | 验证 | 2天 | 3天 | +1天 |
| **A. HV 指令** | **H-extension 指令** | **0** | **4天** | **+4天** |
| **B. HV 异常** | **Guest Page Fault** | **0** | **3.5天** | **+3.5天** |
| **C. HV 中断** | **虚拟化中断** | **0** | **3.5天** | **+3.5天** |
| **D. 特权切换** | **HS/VS 模式切换** | **0** | **3.5天** | **+3.5天** |
| **E. CSR 完善** | **缺失寄存器** | **0** | **2.5天** | **+2.5天** |
| **F. VMID** | **VMID 管理** | **0** | **2.5天** | **+2.5天** |
| **G. 其他** | **htimedelta 等** | **0** | **1.5天** | **+1.5天** |
| | **总计** | **~10天** | **~30天** | **+20天** |

---

## 推荐实施策略

### 方案 A：渐进式（推荐）
```
第一阶段：两阶地址转译 (~10天)
  → 先实现核心的 VA→PA 两阶转译
  → 可以独立测试，不需要完整的 H-extension

第二阶段：基础 Hypervisor 支持 (~10天)
  → H-extension 指令 (HFENCE, HLV/HSV)
  → Guest Page Fault 异常
  → 缺失 CSR 完善

第三阶段：完整 Hypervisor (~10天)
  → 虚拟化中断
  → HS/VS 特权切换
  → VMID 管理
  → htimedelta 等高级功能
```

### 方案 B：一次性完整实现 (~30天)
- 所有模块并行开发
- 需要更多协调和集成测试
- 风险更高，但一次性到位

### 方案 C：最小可行集 (~5天)
- 仅两阶转译 + 基本 HS/VS 模式识别
- 指令和异常暂不实现
- 适用于验证 H-extension 设计，不生成实际可运行的 hypervisor 测试
