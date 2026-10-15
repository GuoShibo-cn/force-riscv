# RISC-V 两阶地址转译（Two-Stage Address Translation）开发计划

## 一、背景与目标

RISC-V Hypervisor 扩展（H-extension）引入两阶地址转译机制：
- **Stage-1 (VS-stage)**：Guest OS 的虚拟地址（GVA）→ 物理地址（GPA），由 `vsatp` 寄存器控制
- **Stage-2 (G-stage)**：Guest 物理地址（GPA）→ 宿主物理地址（HPA），由 `hgatp` 寄存器控制

最终效果：GVA → GPA → HPA

## 二、现状分析

### 2.1 已有基础设施（好消息）

项目已经为 H-extension 做了**大量预埋工作**：

| 组件 | 现状 | 说明 |
|------|------|------|
| `EVmRegimeType` 枚举 | ✅ 已有 `VS` 和 `HS` | `EnumsRISCV.h` 中已定义 M/S/HS/VS 四种 regime |
| CSR 寄存器 | ✅ hgatp/hstatus/vsatp 等已定义 | `system_registers_rv64.xml` 中有完整定义 |
| `VmFactoryRISCV` | ⚠️ 已有 VS/HS case 但未实现 | `VmRegimeInstance()` 中 VS/HS 已创建 `VmPagingRegime`，但 `GetRegisterContext()` 里只有 `break; //hgatp, hstatus` 注释占位符 |
| 特权级别 | ✅ 已有 `EPrivilegeLevelType::H` | `EnumsRISCV.h` 已定义 |
| H-extension 指令 | ⚠️ 部分存在 | `RV64H` 已在 `EInstructionExtensionType` 枚举中 |

### 2.2 关键缺失（需要开发的部分）

1. **`VmAddressSpaceRISCV` 不存在** —— 当前 `VmAddressSpace` 是通用基类，不支持两阶翻译链
2. **`VmGpaMapper` 不存在** —— 缺少 GPA→HPA 映射层
3. **`VmasControlBlockRISCV` 不区分 VS/HS** —— 所有 regime 共用同一实现，VS 应该用 `vsatp`，HS 应该用 `hgatp`
4. **约束系统不支持两阶** —— `EVmConstraintType` 缺少 guest-page-fault 相关类型
5. **`PagingMode` 枚举缺 Ssv39/Ssv48** —— G-stage 使用 Sv39x4/Sv48x4 格式

## 三、总体架构设计

```
┌──────────────────────────────────────────────────────────────┐
│                    VmManagerRISCV                            │
│  ┌──────────────────┐  ┌──────────────────┐                  │
│  │  VS-Regime       │  │  HS-Regime       │                  │
│  │  (Guest VMAS)    │  │  (Host VMAS)     │                  │
│  │                  │  │                  │                  │
│  │ VmasControlBlock │  │ VmasControlBlock │                  │
│  │   - vsatp        │  │   - hgatp        │                  │
│  │   - vs-mode      │  │   - h-status     │                  │
│  │                  │  │                  │                  │
│  │ VmAddressSpace   │  │ VmGpaAddressSpace│                  │
│  │  (S1 translation)│  │  (S2 translation)│                  │
│  │                  │  │                  │                  │
│  │ VmPaMapper       │──│ VmGpaMapper      │                  │
│  │  GVA→GPA         │  │  GPA→HPA         │                  │
│  │                  │  │                  │                  │
│  │ PageTable(Sv39)  │  │ PageTable(Sv39x4)│                  │
│  └──────────────────┘  └──────────────────┘                  │
│         │                       │                            │
│         └───────┬───────────────┘                            │
│                 ▼                                            │
│         TwoStageTranslationUnit                              │
│   (协调 S1 + S2, 生成完整 GVA→HPA 页表链)                    │
└──────────────────────────────────────────────────────────────┘
```

## 四、分阶段实施计划

---

### 阶段一：基础设施扩展（枚举、配置、约束）

**目标**: 为两阶地址转译扩展底层数据结构和枚举

#### 4.1 扩展枚举定义

| 文件 | 修改 | 说明 |
|------|------|------|
| `utils/enum_classes/riscv_enum_classes.py` | 添加 `Sv39x4`, `Sv48x4` 到 `EPagingMode` | G-stage 专用分页模式 |
| `utils/enum_classes/riscv_enum_classes.py` | 添加 `GuestPageFault` 等约束类型 | `EPagingExceptionType` |
| `utils/enum_classes/riscv_enum_classes.py` | 添加 `GStage`、`VSStage` 到 `ESystemOptionType` | 配置选项 |

#### 4.2 重新生成枚举头文件

```bash
cd /home/guoshibo/force-riscv/utils/enum_classes
python3 create_enum_files.py
```

#### 4.3 扩展 `EVmInfoBoolType`

在 `EnumsRISCV.h` 的 `EVmInfoBoolType` 中添加：
- `VGEIN` — Virtual Guest External Interrupt Number
- `GVA` — Guest Virtual Address flag

#### 4.4 Config 文件扩展

在 `config/riscv_rv64.config` 中添加两阶地址转译开关：

```json
{
  "HExtension": {
    "Enable": true,
    "TwoStageTranslation": true,
    "GStagePagingMode": "Sv39x4"
  }
}
```

**预估工作量**: 0.5 天

---

### 阶段二：VmasControlBlock 拆分（VS vs HS）

**目标**: 让 VS 和 HS regime 使用各自的控制块实现

#### 4.5 创建 `VmasControlBlockVS`

新文件: `riscv/inc/VmasControlBlockVS.h` + `riscv/src/VmasControlBlockVS.cc`

继承自 `VmasControlBlockRISCV`，覆盖以下方法：

```cpp
class VmasControlBlockVS : public VmasControlBlockRISCV {
public:
    VmasControlBlockVS();
    ~VmasControlBlockVS() override;

    const std::string AtpRegisterName() const override { return "vsatp"; }
    const std::string StatusRegisterName() const override { return "vsstatus"; }

    void Setup(Generator* pGen) override;
    void GetAddressErrorRanges(std::vector<TranslationRange>& rRanges) const override;
    bool InitializeRootPageTable(VmAddressSpace* pVmas, RootPageTable* pRootTable) override;

protected:
    void FillRegisterReload(RegisterReload* pRegContext) const override;
    uint64 GetMaxPhysicalAddress() const override;  // 对 VS 来说是 GPA 空间
};
```

**关键区别**:
- `AtpRegisterName()` 返回 `"vsatp"` 而非 `"satp"`
- `StatusRegisterName()` 返回 `"vsstatus"` 而非 `"sstatus"`
- 地址错误范围基于 Guest 虚拟地址空间
- PTE 属性需考虑 U 位在 VS 阶段的语义

#### 4.6 创建 `VmasControlBlockHS`

新文件: `riscv/inc/VmasControlBlockHS.h` + `riscv/src/VmasControlBlockHS.cc`

```cpp
class VmasControlBlockHS : public VmasControlBlockRISCV {
public:
    VmasControlBlockHS();
    ~VmasControlBlockHS() override;

    const std::string AtpRegisterName() const override { return "hgatp"; }
    const std::string StatusRegisterName() const override { return "hstatus"; }

    // G-stage 特有的地址错误范围 (基于 GPA 空间, canonical address 检查不同)
    void GetAddressErrorRanges(std::vector<TranslationRange>& rRanges) const override;

    // G-stage 页表使用 Sv39x4/Sv48x4 格式
    bool InitializeRootPageTable(VmAddressSpace* pVmas, RootPageTable* pRootTable) override;

    // G-stage 没有 U/X/W/R 位中的 U 位 — 所有页面对 HS 阶段都是 "supervisor" 级别
    ConstraintSet* InitialVirtualConstraint() const override;

protected:
    void FillRegisterReload(RegisterReload* pRegContext) const override;
};
```

**关键区别**:
- `AtpRegisterName()` 返回 `"hgatp"`
- G-stage PTE 没有 U 位 (bit 4)，所有翻译对 VS 阶段可见
- G-stage 支持更大的页面粒度（Sv39x4 的超级页）
- `hstatus.VSXL` 决定 guest 的 XLEN

#### 4.7 修改 `VmFactoryRISCV`

修改 `VmFactoryRISCV.cc` 中的 `VmRegimeInstance()`:

```cpp
case EVmRegimeType::VS:
    return new VmPagingRegime(this, mVmRegimeType, EPrivilegeLevelType::S, EMemBankType::Default);
case EVmRegimeType::HS:
    return new VmPagingRegime(this, mVmRegimeType, EPrivilegeLevelType::H, EMemBankType::Default);
```

修改 `GetRegisterContext()` 填充 VS/HS 的寄存器列表：

```cpp
case EVmRegimeType::HS:
    rRegNames.push_back("hstatus");
    if (pagingEnabled) rRegNames.push_back("hgatp");
    rRegNames.push_back("hideleg");
    rRegNames.push_back("hedeleg");
    break;
case EVmRegimeType::VS:
    rRegNames.push_back("vsstatus");
    if (pagingEnabled) rRegNames.push_back("vsatp");
    rRegNames.push_back("vstvec");
    break;
```

**预估工作量**: 2 天

---

### 阶段三：两阶地址空间（VmAddressSpaceRISCV）

**目标**: 创建支持两阶翻译的地址空间类

#### 4.8 创建 `VmAddressSpaceRISCV`

新文件: `riscv/inc/VmAddressSpaceRISCV.h` + `riscv/src/VmAddressSpaceRISCV.cc`

继承自 `VmAddressSpace`，增加两阶翻译能力：

```cpp
class VmAddressSpaceRISCV : public VmAddressSpace {
public:
    VmAddressSpaceRISCV(const VmFactory* pFactory, VmasControlBlock* pVmasCtlrBlock);
    ~VmAddressSpaceRISCV() override;

    // 两阶翻译核心接口
    void SetGpaAddressSpace(VmAddressSpaceRISCV* pGpaAs);   // VS 设置指向 HS
    void SetGvaTranslationEnabled(bool enabled);

    // 覆盖翻译方法，实现 GVA→GPA→HPA 链式翻译
    ETranslationResultType TranslateVaToPa(uint64 VA, uint64& PA, uint32& bank) const override;
    ETranslationResultType TranslatePaToVa(uint64 PA, EMemBankType bank, uint64& VA) const override;

    // GVA→HPA 完整翻译（两阶）
    ETranslationResultType TranslateGvaToHpa(uint64 GVA, uint64& HPA, uint32& bank) const;

    // 页表操作
    void SetupTwoStagePageTables(uint64 GVA, uint64 size, bool isInstr,
                                  GenPageRequest* pPageReq);

protected:
    VmAddressSpaceRISCV* mpGpaAddressSpace;  // 指向 G-stage 地址空间（仅 VS 使用）
    bool mTwoStageEnabled;
};
```

#### 4.9 创建 `VmGpaAddressSpace`

新文件: `riscv/inc/VmGpaAddressSpace.h` + `riscv/src/VmGpaAddressSpace.cc`

专门用于 G-stage 翻译的地址空间：

```cpp
class VmGpaAddressSpace : public VmAddressSpaceRISCV {
public:
    VmGpaAddressSpace(const VmFactory* pFactory, VmasControlBlock* pVmasCtlrBlock);
    ~VmGpaAddressSpace() override;

    // G-stage 使用 GPA 作为"虚拟地址"，HPA 作为"物理地址"
    ETranslationResultType TranslateVaToPa(uint64 GPA, uint64& HPA, uint32& bank) const override;

    // G-stage 页表使用不同的 PTE 格式
    void InitializeGStagePageTables();

    // G-stage 没有 instruction/data 区分
    const ConstraintSet* VirtualUsableConstraintSet(bool isInstr) const override;

protected:
    void SetupGStageConstraints();
};
```

#### 4.10 创建 `TwoStageTranslationUnit`

新文件: `riscv/inc/TwoStageTranslationUnit.h` + `riscv/src/TwoStageTranslationUnit.cc`

协调两阶翻译的核心类：

```cpp
class TwoStageTranslationUnit {
public:
    TwoStageTranslationUnit(VmAddressSpaceRISCV* pVsAs, VmGpaAddressSpace* pHsAs);

    // 设置完整的两阶页表链：GVA→GPA→HPA
    void SetupFullTranslation(uint64 GVA, uint64 GPA, uint64 HPA,
                               uint64 size, bool isInstr);

    // 生成 G-stage 异常场景（guest page fault）
    void SetupGuestPageFaultScenario(uint64 GVA, uint64 GPA);

    // 验证两阶翻译一致性
    bool ValidateTranslationChain(uint64 GVA, uint64& HPA) const;

    // 生成两阶翻译相关的 CSR 配置序列
    void GenerateSetupInstructions(Generator* pGen);

private:
    VmAddressSpaceRISCV* mpVsAddressSpace;  // Stage-1
    VmGpaAddressSpace*    mpHsAddressSpace;  // Stage-2
};
```

**预估工作量**: 3-4 天

---

### 阶段四：页表系统扩展

**目标**: 支持 G-stage 特有的页表格式（Sv39x4/Sv48x4）

#### 4.11 扩展 `RootPageTable` 支持 G-stage

修改 `riscv/src/RootPageTableRISCV.cc`（或创建新的 `GStageRootPageTable`）：

G-stage PTE 格式差异：
- **Sv39x4**: 与 Sv39 相同的层级结构，但 PTE 中没有 U 位
- **Sv48x4**: 与 Sv48 相同的层级结构，但 PTE 中没有 U 位
- `hgatp.MODE` 值不同：Sv39x4=8, Sv48x4=9

```cpp
class GStageRootPageTable : public RootPageTable {
public:
    GStageRootPageTable(EPagingMode mode, uint32 tableSize, uint32 pteSize);

    // G-stage 使用不同的 MODE 编码
    uint64 EncodeModeRegisterValue(uint64 ppn) const override;

    // G-stage 没有 U 位
    uint64 EncodePteAddress(uint64 pa) const override;

    // G-stage 的 PTE 属性检查不同
    bool IsPteValid(uint64 pteValue) const override;
};
```

#### 4.12 创建 `GStagePteAttribute`

新文件: `riscv/inc/GStagePteAttribute.h` + `riscv/src/GStagePteAttribute.cc`

```cpp
class GStagePteAttribute : public PteAttribute {
public:
    // G-stage PTE 没有 U (User) 位
    // RWX 位语义相同
    // D (Dirty) 和 A (Accessed) 位由软件管理
    // 新增：Rsw 字段在 G-stage 中的使用

    uint64 EncodeValue(EPteAttributeType attrType, uint64 attrValue) const override;
    uint64 DecodeValue(uint64 pteValue, EPteAttributeType attrType) const override;
};
```

#### 4.13 扩展 `SetupRootPageTableRISCV`

添加 G-stage 的根页表设置逻辑：

```cpp
uint64 SetupGStageRootPageTable(uint32 tableSize, MemoryManager* pMemMgr,
                                 EMemBankType bankType,
                                 const RegisterFile* pRegFile,
                                 const std::string& regName,  // "hgatp"
                                 const ConstraintSet* usable,
                                 EPagingMode gStageMode);     // Sv39x4/Sv48x4
```

**预估工作量**: 2-3 天

---

### 阶段五：约束和异常处理

**目标**: 添加两阶翻译相关的约束类型和异常场景

#### 4.14 扩展约束类型

修改 `utils/enum_classes/riscv_enum_classes.py`，在 `EVmConstraintType` 中添加：

```python
('GuestPageFault', ...),      # Guest Page Fault 约束
('GStageAccessFault', ...),   # G-stage Access Fault
('GStagePageFault', ...),     # G-stage Page Fault
('NestedPageFault', ...),     # 嵌套页异常（两阶都 fault）
```

#### 4.15 扩展异常类

在 `EPagingExceptionType` 中添加：

```python
('GuestInstructionPageFault', ...),  # 12 (与 S-stage 共享编码)
('GuestLoadPageFault', ...),         # 13
('GuestStoreAmoPageFault', ...),     # 15
```

在 `EExceptionClassType` 中添加对应的 guest 异常。

#### 4.16 修改 `GenExceptionAgentRISCV`

扩展异常生成器以支持：
- Guest Page Fault 的陷阱处理
- `htval`/`htinst` 寄存器值的生成
- Two-stage fault 的优先级处理（S1 fault 优先于 S2 fault）

**预估工作量**: 2 天

---

### 阶段六：Python 测试模板

**目标**: 提供 Python 层的两阶地址转译测试支持

#### 4.17 扩展 `GenThread.py`

添加两阶翻译设置方法：

```python
class GenThreadRISCV(GenThread):
    def setup_two_stage_translation(self, vs_paging_mode="Sv39",
                                     hs_paging_mode="Sv39x4"):
        """设置两阶地址转译环境"""
        pass

    def generate_gva_to_hpa_mapping(self, gva, gpa, hpa, size=0x1000):
        """生成完整的 GVA→GPA→HPA 映射"""
        pass

    def trigger_guest_page_fault(self, gva, fault_type="load"):
        """触发 Guest Page Fault 场景"""
        pass
```

#### 4.18 创建测试模板示例

新文件: `py/riscv/two_stage_test.py`

```python
# 两阶地址转译测试模板
class TwoStageTranslationTest(GenThreadRISCV):
    def generate(self):
        # 1. 设置 HS 阶段（hgatp，GPA→HPA）
        self.setup_h_stage(paging_mode="Sv39x4")

        # 2. 设置 VS 阶段（vsatp，GVA→GPA）
        self.setup_vs_stage(paging_mode="Sv39")

        # 3. 配置 hstatus
        self.configure_hstatus(vsxl=2)  # 64-bit guest

        # 4. 生成两阶页表
        self.setup_two_stage_page_tables(
            gva_base=0x80000000,
            gpa_base=0x80000000,
            hpa_base=0x80200000,
            size=0x100000
        )

        # 5. 生成测试指令序列
        self.generate_guest_instructions()
```

**预估工作量**: 1.5 天

---

### 阶段七：集成、测试与验证

**目标**: 集成所有组件，端到端验证

#### 4.19 修改 `VmManagerRISCV`

更新 `VmManagerRISCV::SetupVm()` 以支持两阶模式：

```cpp
void VmManagerRISCV::SetupVm() {
    // 创建 HS 地址空间（G-stage）
    VmFactoryRISCV hsFactory(EVmRegimeType::HS);
    VmasControlBlock* hsCBlock = hsFactory.CreateVmasControlBlock(EMemBankType::Default);
    VmGpaAddressSpace* hsAs = new VmGpaAddressSpace(&hsFactory, hsCBlock);

    // 创建 VS 地址空间（S1-stage）
    VmFactoryRISCV vsFactory(EVmRegimeType::VS);
    VmasControlBlock* vsCBlock = vsFactory.CreateVmasControlBlock(EMemBankType::Default);
    VmAddressSpaceRISCV* vsAs = new VmAddressSpaceRISCV(&vsFactory, vsCBlock);

    // 连接两阶翻译链
    vsAs->SetGpaAddressSpace(hsAs);

    // 注册到 manager
    AddAddressSpace(EVmRegimeType::VS, vsAs);
    AddAddressSpace(EVmRegimeType::HS, hsAs);
}
```

#### 4.20 集成测试场景

| 测试场景 | 说明 |
|----------|------|
| 基本两阶翻译 | GVA→GPA→HPA 链式翻译正确性 |
| G-stage 仅启用 | vsatp=Bare, hgatp=Sv39x4 |
| S1+G-stage 混合 | 两阶页表同时启用 |
| Guest Page Fault | 模拟 GPA 无映射导致的 fault |
| 嵌套 Page Fault | S1 和 S2 同时 fault 的优先级 |
| ASID/VMID 隔离 | 多 Guest 场景下的地址空间隔离 |
| 权限转换 | VS→HS→M 模式的特权级转换 |

**预估工作量**: 2-3 天

---

## 五、文件变更清单

### 新建文件（约 12 个）

| 文件 | 说明 |
|------|------|
| `riscv/inc/VmasControlBlockVS.h` | VS 阶段控制块头文件 |
| `riscv/src/VmasControlBlockVS.cc` | VS 阶段控制块实现 |
| `riscv/inc/VmasControlBlockHS.h` | HS 阶段控制块头文件 |
| `riscv/src/VmasControlBlockHS.cc` | HS 阶段控制块实现 |
| `riscv/inc/VmAddressSpaceRISCV.h` | RISC-V 地址空间头文件 |
| `riscv/src/VmAddressSpaceRISCV.cc` | RISC-V 地址空间实现 |
| `riscv/inc/VmGpaAddressSpace.h` | G-stage 地址空间头文件 |
| `riscv/src/VmGpaAddressSpace.cc` | G-stage 地址空间实现 |
| `riscv/inc/TwoStageTranslationUnit.h` | 两阶翻译协调单元头文件 |
| `riscv/src/TwoStageTranslationUnit.cc` | 两阶翻译协调单元实现 |
| `riscv/inc/GStagePteAttribute.h` | G-stage PTE 属性头文件 |
| `riscv/src/GStagePteAttribute.cc` | G-stage PTE 属性实现 |
| `py/riscv/two_stage_test.py` | 两阶翻译测试模板 |

### 修改文件（约 10 个）

| 文件 | 修改内容 |
|------|----------|
| `utils/enum_classes/riscv_enum_classes.py` | 添加 Sv39x4/Sv48x4 等枚举值 |
| `riscv/inc/EnumsRISCV.h` | 自动生成（通过脚本） |
| `riscv/src/VmFactoryRISCV.cc` | 填充 VS/HS 的完整实现 |
| `riscv/src/VmManagerRISCV.cc` | 添加两阶模式支持 |
| `riscv/src/VmasControlBlockRISCV.cc` | 添加虚拟化相关辅助方法 |
| `riscv/inc/SetupRootPageTableRISCV.h` | 添加 G-stage 根页表设置 |
| `riscv/src/SetupRootPageTableRISCV.cc` | 实现 G-stage 根页表设置 |
| `riscv/src/GenExceptionAgentRISCV.cc` | 添加 guest 异常类型 |
| `py/base/GenThread.py` | 添加两阶翻译 Python API |
| `config/riscv_rv64.config` | 添加 H-extension 配置项 |

## 六、总体时间估算

| 阶段 | 预估时间 | 复杂度 |
|------|----------|--------|
| 一：基础设施扩展 | 0.5 天 | 低 |
| 二：VmasControlBlock 拆分 | 2 天 | 中 |
| 三：两阶地址空间 | 3-4 天 | 高 |
| 四：页表系统扩展 | 2-3 天 | 高 |
| 五：约束和异常处理 | 2 天 | 中 |
| 六：Python 测试模板 | 1.5 天 | 中 |
| 七：集成与验证 | 2-3 天 | 高 |
| **总计** | **13-16 天** | |

## 七、风险与注意事项

1. **RISC-V H-extension 规范版本**：需要确认目标支持的 spec 版本（1.0 ratified），不同版本的 hgatp 格式可能不同
2. **与现有单阶翻译的兼容性**：需要确保不启用 H-extension 时行为完全不变
3. **页表约束交叉影响**：S1 和 S2 的 PTE 约束可能交叉影响，需要仔细处理
4. **Handcar 仿真器支持**：需要确认 Spike/handcar 是否已支持 H-extension 的两阶翻译仿真
5. **测试覆盖率**：两阶翻译的异常场景组合较多（S1 fault/S2 fault/both fault），需要系统化测试

## 八、建议的优先级顺序

1. **Phase 1 + Phase 2 先行** — 先把枚举和控制块的基础搭好，这是所有后续工作的基础
2. **Phase 3 核心** — `VmAddressSpaceRISCV` 和 `TwoStageTranslationUnit` 是核心
3. **Phase 4 页表** — 页表是翻译功能的关键
4. **Phase 5+6 约束和测试** — 保证功能正确性
5. **Phase 7 集成** — 端到端验证
