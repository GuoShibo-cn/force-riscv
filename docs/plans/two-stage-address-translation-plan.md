# RISC-V 两阶地址转译 (Two-Stage Address Translation) 实现计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 在 FORCE-RISCV 项目中实现 RISC-V Hypervisor Extension 的两阶地址转译功能，支持 VS-stage (satp/vsatp) + G-stage (hgatp) 的级联地址转换。

**Architecture:** 基于现有单阶转译架构扩展：(1) 在 VmControlBlock 中增加 stage 字段管理；(2) 新增 TwoStageVmMapper 组合器串联 VS-stage 和 G-stage 的 VmMapper；(3) 扩展 PTE 定义支持 stage 2 的 G-stage PTE 格式；(4) 新增 Sv48x4/Sv39x4 等 hypervisor paging mode；(5) 扩展 VmInfoRISCV 识别两阶转译状态。

**Tech Stack:** C++17, Python 3, pybind11, RISC-V Hypervisor Extension Spec v1.0

**背景分析:**
- 项目已有 `EVmRegimeType::HS` 和 `EVmRegimeType::VS` 枚举，但未实现两阶转译逻辑
- 现有的 `VmMapper` 是单阶设计（VA → PA），需要扩展为两阶（GVA → GPA → SPA）
- PTE XML 定义中已有 `stage="1"` 属性，说明框架预留了 stage 概念
- `VmControlBlock` 已有 `mStage` 字段但始终为 0（单阶）
- `hgatp` 寄存器已在 system_registers_rv64.xml 中定义

---

## Phase 1: 枚举和配置扩展

### Task 1: 扩展 PagingMode 枚举，添加 Hypervisor 模式

**Objective:** 在 enum_classes 中添加 Sv39x4 和 Sv48x4 等两阶 paging mode

**Files:**
- Modify: `utils/enum_classes/riscv_enum_classes.py` — 找到 "PagingMode" 条目

**Step 1: 修改 PagingMode 枚举定义**

打开 `utils/enum_classes/riscv_enum_classes.py`，找到第 81-91 行的 PagingMode 定义，将：
```python
    [
        "PagingMode",
        "unsigned char",
        "Paging mode",
        [
            ("Bare", 0),
            ("Sv32", 1),
            ("Sv39", 2),
            ("Sv48", 3),
        ],
    ],
```
修改为：
```python
    [
        "PagingMode",
        "unsigned char",
        "Paging mode",
        [
            ("Bare", 0),
            ("Sv32", 1),
            ("Sv39", 2),
            ("Sv48", 3),
            ("Sv39x4", 4),
            ("Sv48x4", 5),
        ],
    ],
```

**Step 2: 重新生成枚举头文件**

```bash
cd /home/guoshibo/force-riscv && make enums
```

**Step 3: 验证生成的头文件**

```bash
grep -A 10 "enum class EPagingMode" riscv/inc/EnumsRISCV.h
```
预期输出应包含 Sv39x4 和 Sv48x4。

**Step 4: Commit**

```bash
git add utils/enum_classes/riscv_enum_classes.py riscv/inc/EnumsRISCV.h base/inc/Enums.h
git commit -m "feat: add Sv39x4/Sv48x4 paging modes for two-stage translation"
```

---

### Task 2: 扩展 EVmContextParamType，添加 Hypervisor 相关参数

**Objective:** 添加 hstatus.VGEIN、hgatp.VMID 等两阶转译所需的上下文参数类型

**Files:**
- Modify: `utils/enum_classes/riscv_enum_classes.py` — 找到 "VmContextParamType" 条目

**Step 1: 修改 VmContextParamType 枚举**

找到第 31-46 行的 VmContextParamType 定义，扩展为：
```python
    [
        "VmContextParamType",
        "unsigned char",
        "Virtual memory request types",
        [
            ("MODE", 0),
            ("MPRV", 1),
            ("MPP", 2),
            ("SPP", 3),
            ("MXR", 4),
            ("SUM", 5),
            ("MBE", 6),
            ("SBE", 7),
            ("UBE", 8),
            ("TVM", 9),
            ("VGEIN", 10),
            ("VMID", 11),
            ("GVA", 12),
        ],
    ],
```

**Step 2: 重新生成枚举**

```bash
cd /home/guoshibo/force-riscv && make enums
```

**Step 3: Commit**

```bash
git add utils/enum_classes/riscv_enum_classes.py riscv/inc/EnumsRISCV.h base/inc/Enums.h
git commit -m "feat: add VGEIN/VMID/GVA context params for hypervisor extension"
```

---

### Task 3: 扩展 EPteAttributeType，添加 stage 2 特有属性

**Objective:** 添加 RSW2 (stage 2 RSW) 等 stage 2 PTE 特有属性

**Files:**
- Modify: `utils/enum_classes/riscv_enum_classes.py` — 找到 "PteAttributeType" 条目

**Step 1: 修改 PteAttributeType 枚举**

将现有的 PteAttributeType 扩展：
```python
    [
        "PteAttributeType",
        "unsigned char",
        "Page table entry attribute types",
        [
            ("Address", 0),
            ("IGNORED", 1),
            ("RES0", 2),
            ("SystemPage", 3),
            ("RSW", 4),
            ("DA", 5),
            ("G", 6),
            ("U", 7),
            ("X", 8),
            ("WR", 9),
            ("V", 10),
            ("RSW2", 11),
            ("N", 12),
        ],
    ],
```

**Step 2: 重新生成枚举**

```bash
cd /home/guoshibo/force-riscv && make enums
```

**Step 3: Commit**

```bash
git add utils/enum_classes/riscv_enum_classes.py riscv/inc/EnumsRISCV.h base/inc/Enums.h
git commit -m "feat: add RSW2/N PTE attributes for stage 2 translation"
```

---

## Phase 2: PTE XML 定义扩展

### Task 4: 创建 stage 2 PTE XML 定义文件

**Objective:** 创建 G-stage 的 PTE 定义文件，支持 Sv39x4 和 Sv48x4 模式

**Files:**
- Create: `riscv/arch_data/paging/page_tables_sv48x4_gstage.xml`
- Create: `riscv/arch_data/paging/page_tables_sv39x4_gstage.xml`

**Step 1: 创建 page_tables_sv48x4_gstage.xml**

根据 RISC-V Hypervisor Spec，stage 2 PTE 的格式与 stage 1 类似，但：
- G-bit 含义不同（stage 2 中 G=1 表示全局映射，不受 VMID 限制）
- 增加 RSW2 字段
- 地址字段的 PPN 指向的是 Guest Physical Address → Stage Physical Address

```xml
<?xml version="1.0" encoding="utf-8"?>
<page_tables>
  <paging_mode name="Sv48x4"/>

  <!-- Stage 2 Table PTE (non-leaf) -->
  <pte type="4K" category="Table" granule="4K" stage="2" class="TablePte">
    <pte_attribute type="RES0" bits="63-54" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="Address" bits="53-10" class="AddressPteAttributeRISCV"/>
    <pte_attribute type="RSW2" bits="9-8" class="RandomPteAttribute"/>
    <pte_attribute type="DA" bits="7-6" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="G" bits="5" class="GPteAttributeRISCV"/>
    <pte_attribute type="U" bits="4" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="X" bits="3" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="WR" bits="2-1" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="V" bits="0" class="VPteAttributeRISCV"/>
  </pte>

  <!-- Stage 2 Leaf PTE - 4K page -->
  <pte type="4K" category="Page" granule="4K" level="0" stage="2">
    <pte_attribute type="RES0" bits="63-54" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="Address" bits="53-10" class="AddressPteAttributeRISCV"/>
    <pte_attribute type="RSW2" bits="9-8" class="RandomPteAttribute"/>
    <pte_attribute type="DA" bits="7-6" class="DAPteAttributeRISCV"/>
    <pte_attribute type="G" bits="5" class="GPteAttributeRISCV"/>
    <pte_attribute type="U" bits="4" class="UPteAttributeRISCV"/>
    <pte_attribute type="X" bits="3" class="XPteAttributeRISCV"/>
    <pte_attribute type="WR" bits="2-1" class="WRPteAttributeRISCV"/>
    <pte_attribute type="V" bits="0" value="1" class="VPteAttributeRISCV"/>
  </pte>

  <!-- Stage 2 Leaf PTE - 2M superpage -->
  <pte type="2M" category="Page" granule="4K" level="1" stage="2">
    <pte_attribute type="RES0" bits="63-54" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="Address" bits="53-10" class="AddressPteAttributeRISCV"/>
    <pte_attribute type="RSW2" bits="9-8" class="RandomPteAttribute"/>
    <pte_attribute type="DA" bits="7-6" class="DAPteAttributeRISCV"/>
    <pte_attribute type="G" bits="5" class="GPteAttributeRISCV"/>
    <pte_attribute type="U" bits="4" class="UPteAttributeRISCV"/>
    <pte_attribute type="X" bits="3" class="XPteAttributeRISCV"/>
    <pte_attribute type="WR" bits="2-1" class="WRPteAttributeRISCV"/>
    <pte_attribute type="V" bits="0" value="1" class="VPteAttributeRISCV"/>
  </pte>

  <!-- Stage 2 Leaf PTE - 1G superpage -->
  <pte type="1G" category="Page" granule="4K" level="2" stage="2">
    <pte_attribute type="RES0" bits="63-54" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="Address" bits="53-10" class="AddressPteAttributeRISCV"/>
    <pte_attribute type="RSW2" bits="9-8" class="RandomPteAttribute"/>
    <pte_attribute type="DA" bits="7-6" class="DAPteAttributeRISCV"/>
    <pte_attribute type="G" bits="5" class="GPteAttributeRISCV"/>
    <pte_attribute type="U" bits="4" class="UPteAttributeRISCV"/>
    <pte_attribute type="X" bits="3" class="XPteAttributeRISCV"/>
    <pte_attribute type="WR" bits="2-1" class="WRPteAttributeRISCV"/>
    <pte_attribute type="V" bits="0" value="1" class="VPteAttributeRISCV"/>
  </pte>

  <!-- Stage 2 Leaf PTE - 512G superpage -->
  <pte type="512G" category="Page" granule="4K" level="3" stage="2">
    <pte_attribute type="RES0" bits="63-54" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="Address" bits="53-10" class="AddressPteAttributeRISCV"/>
    <pte_attribute type="RSW2" bits="9-8" class="RandomPteAttribute"/>
    <pte_attribute type="DA" bits="7-6" class="DAPteAttributeRISCV"/>
    <pte_attribute type="G" bits="5" class="GPteAttributeRISCV"/>
    <pte_attribute type="U" bits="4" class="UPteAttributeRISCV"/>
    <pte_attribute type="X" bits="3" class="XPteAttributeRISCV"/>
    <pte_attribute type="WR" bits="2-1" class="WRPteAttributeRISCV"/>
    <pte_attribute type="V" bits="0" value="1" class="VPteAttributeRISCV"/>
  </pte>
</page_tables>
```

**Step 2: 创建 Sv39x4 版本（类似，但只有 3 级页表）**

```xml
<?xml version="1.0" encoding="utf-8"?>
<page_tables>
  <paging_mode name="Sv39x4"/>

  <!-- Stage 2 Table PTE (non-leaf) -->
  <pte type="4K" category="Table" granule="4K" stage="2" class="TablePte">
    <pte_attribute type="RES0" bits="63-54" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="Address" bits="53-10" class="AddressPteAttributeRISCV"/>
    <pte_attribute type="RSW2" bits="9-8" class="RandomPteAttribute"/>
    <pte_attribute type="DA" bits="7-6" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="G" bits="5" class="GPteAttributeRISCV"/>
    <pte_attribute type="U" bits="4" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="X" bits="3" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="WR" bits="2-1" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="V" bits="0" class="VPteAttributeRISCV"/>
  </pte>

  <!-- 4K Page - level 0 -->
  <pte type="4K" category="Page" granule="4K" level="0" stage="2">
    <pte_attribute type="RES0" bits="63-54" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="Address" bits="53-10" class="AddressPteAttributeRISCV"/>
    <pte_attribute type="RSW2" bits="9-8" class="RandomPteAttribute"/>
    <pte_attribute type="DA" bits="7-6" class="DAPteAttributeRISCV"/>
    <pte_attribute type="G" bits="5" class="GPteAttributeRISCV"/>
    <pte_attribute type="U" bits="4" class="UPteAttributeRISCV"/>
    <pte_attribute type="X" bits="3" class="XPteAttributeRISCV"/>
    <pte_attribute type="WR" bits="2-1" class="WRPteAttributeRISCV"/>
    <pte_attribute type="V" bits="0" value="1" class="VPteAttributeRISCV"/>
  </pte>

  <!-- 2M Page - level 1 -->
  <pte type="2M" category="Page" granule="4K" level="1" stage="2">
    <pte_attribute type="RES0" bits="63-54" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="Address" bits="53-10" class="AddressPteAttributeRISCV"/>
    <pte_attribute type="RSW2" bits="9-8" class="RandomPteAttribute"/>
    <pte_attribute type="DA" bits="7-6" class="DAPteAttributeRISCV"/>
    <pte_attribute type="G" bits="5" class="GPteAttributeRISCV"/>
    <pte_attribute type="U" bits="4" class="UPteAttributeRISCV"/>
    <pte_attribute type="X" bits="3" class="XPteAttributeRISCV"/>
    <pte_attribute type="WR" bits="2-1" class="WRPteAttributeRISCV"/>
    <pte_attribute type="V" bits="0" value="1" class="VPteAttributeRISCV"/>
  </pte>

  <!-- 1G Page - level 2 -->
  <pte type="1G" category="Page" granule="4K" level="2" stage="2">
    <pte_attribute type="RES0" bits="63-54" value="0" class="ValuePteAttribute"/>
    <pte_attribute type="Address" bits="53-10" class="AddressPteAttributeRISCV"/>
    <pte_attribute type="RSW2" bits="9-8" class="RandomPteAttribute"/>
    <pte_attribute type="DA" bits="7-6" class="DAPteAttributeRISCV"/>
    <pte_attribute type="G" bits="5" class="GPteAttributeRISCV"/>
    <pte_attribute type="U" bits="4" class="UPteAttributeRISCV"/>
    <pte_attribute type="X" bits="3" class="XPteAttributeRISCV"/>
    <pte_attribute type="WR" bits="2-1" class="WRPteAttributeRISCV"/>
    <pte_attribute type="V" bits="0" value="1" class="VPteAttributeRISCV"/>
  </pte>
</page_tables>
```

**Step 3: Commit**

```bash
git add riscv/arch_data/paging/page_tables_sv48x4_gstage.xml riscv/arch_data/paging/page_tables_sv39x4_gstage.xml
git commit -m "feat: add stage 2 PTE definitions for Sv48x4/Sv39x4 hypervisor modes"
```

---

### Task 5: 创建 stage 2 paging choices 文件

**Objective:** 为 stage 2 的页表选择创建独立的权重配置

**Files:**
- Create: `riscv/arch_data/paging/paging_choices_sv48x4_gstage.xml`

**Step 1: 创建 choices 文件**

```xml
<?xml version="1.0" encoding="utf-8"?>
<choices_file>
  <!-- Stage 2 Page Size Choices -->
  <choices name="Page size#4K granule#HS#stage 2" type="Paging">
    <choice description="4K page size" name="4K" value="0x0" weight="97"/>
    <choice description="2M page size" name="2M" value="0x1" weight="2"/>
    <choice description="1G page size" name="1G" value="0x2" weight="1"/>
    <choice description="512G page size" name="512G" value="0x3" weight="0"/>
  </choices>

  <!-- Stage 2 PTE Attributes -->
  <choices name="G-bit#HS#stage 2" type="Paging">
    <choice description="G=0 (VMID-restricted)" name="NoGlobal" value="0x0" weight="80"/>
    <choice description="G=1 (global)" name="Global" value="0x1" weight="20"/>
  </choices>

  <choices name="DA#HS#stage 2" type="Paging">
    <choice description="A=0,D=0" name="NotAccessedNotDirty" value="0x0" weight="10"/>
    <choice description="A=1,D=0" name="AccessedNotDirty" value="0x1" weight="40"/>
    <choice description="A=1,D=1" name="AccessedDirty" value="0x3" weight="50"/>
  </choices>
</choices_file>
```

**Step 2: Commit**

```bash
git add riscv/arch_data/paging/paging_choices_sv48x4_gstage.xml
git commit -m "feat: add stage 2 paging choices for hypervisor extension"
```

---

## Phase 3: VmControlBlock 扩展 — stage 感知

### Task 6: 扩展 VmControlBlock 支持 stage 字段

**Objective:** 让 VmControlBlock 能够标识自己是 stage 1 还是 stage 2

**Files:**
- Modify: `base/inc/VmControlBlock.h` — 添加 Stage() 访问器（已有 mStage 但需确保正确设置）
- Modify: `base/src/VmControlBlock.cc` — 构造函数增加 stage 参数

**Step 1: 查看现有实现**

```bash
grep -n "mStage\|Stage()" base/inc/VmControlBlock.h base/src/VmControlBlock.cc
```

现有代码已有 `uint32 Stage() const { return mStage; }`，但 mStage 初始化可能为 0。

**Step 2: 修改 VmControlBlock 构造函数**

在 `base/inc/VmControlBlock.h` 中，修改构造函数签名：
```cpp
// 原来:
VmControlBlock(EPrivilegeLevelType privType, EMemBankType memType);

// 修改为:
VmControlBlock(EPrivilegeLevelType privType, EMemBankType memType, uint32 stage = 1);
```

在 `base/src/VmControlBlock.cc` 中，修改构造函数初始化列表：
```cpp
// 原来:
VmControlBlock::VmControlBlock(EPrivilegeLevelType privType, EMemBankType memType)
  : VmContext(), mPrivilegeLevel(privType), mDefaultMemoryBank(memType),
    mBigEndian(false), mStage(0), mMaxPhysicalAddress(0), mVmContextParameters()

// 修改为:
VmControlBlock::VmControlBlock(EPrivilegeLevelType privType, EMemBankType memType, uint32 stage)
  : VmContext(), mPrivilegeLevel(privType), mDefaultMemoryBank(memType),
    mBigEndian(false), mStage(stage), mMaxPhysicalAddress(0), mVmContextParameters()
```

**Step 3: 同步修改派生类**

需要同步修改：
- `base/inc/VmDirectMapControlBlock.h` — 构造函数增加 stage 参数
- `base/src/VmDirectMapControlBlock.cc` — 传递 stage 到基类
- `riscv/inc/VmDirectMapControlBlockRISCV.h` — 构造函数增加 stage 参数
- `riscv/src/VmDirectMapControlBlockRISCV.cc` — 传递 stage 到基类

**Step 4: Commit**

```bash
git add base/inc/VmControlBlock.h base/src/VmControlBlock.cc base/inc/VmDirectMapControlBlock.h base/src/VmDirectMapControlBlock.cc riscv/inc/VmDirectMapControlBlockRISCV.h riscv/src/VmDirectMapControlBlockRISCV.cc
git commit -m "refactor: add stage parameter to VmControlBlock constructor hierarchy"
```

---

## Phase 4: 核心 — TwoStageVmMapper 组合器

### Task 7: 创建 TwoStageVmMapper 类（核心组件）

**Objective:** 创建组合 VmMapper，串联 VS-stage (GVA→GPA) 和 G-stage (GPA→SPA) 的两阶转译

**Files:**
- Create: `base/inc/TwoStageVmMapper.h`
- Create: `base/src/TwoStageVmMapper.cc`

**Step 1: 创建头文件 `base/inc/TwoStageVmMapper.h`**

```cpp
#ifndef Force_TwoStageVmMapper_H
#define Force_TwoStageVmMapper_H

#include "VmMapper.h"
#include "VmAddressSpace.h"
#include ARCH_ENUM_HEADER

namespace Force {

  class Generator;
  class ConstraintSet;
  class GenPageRequest;
  class Page;
  class TranslationRange;
  class PageInformation;
  class VmInfo;
  class AddressTagging;
  class PhysicalRegion;

  /*!\
    \class TwoStageVmMapper
    \brief Composes VS-stage and G-stage VmMappers for two-stage address translation.
    
    Two-stage translation: GVA --[VS-stage]--> GPA --[G-stage]--> SPA
    
    This mapper does NOT own the stage mappers; they are managed by VmManager.
  */
  class TwoStageVmMapper : public VmMapper {
  public:
    TwoStageVmMapper(VmMapper* pVsStageMapper, VmMapper* pGStageMapper);
    ~TwoStageVmMapper() override = default;

    ASSIGNMENT_OPERATOR_ABSENT(TwoStageVmMapper);
    COPY_CONSTRUCTOR_ABSENT(TwoStageVmMapper);

    void Setup(Generator* gen) override;
    void Activate() override;
    void Initialize() override;
    void Deactivate() override;

    // VmMapper interface implementations — delegate to appropriate stage mapper
    void AddPhysicalRegion(PhysicalRegion* pRegion, bool map) override;
    void Update() override;
    const ConstraintSet* VirtualUsableConstraintSet(bool isInstr) const override;
    ConstraintSet* VirtualUsableConstraintSetClone(bool isInstr) override;
    const ConstraintSet* VirtualSharedConstraintSet() const override;
    void ApplyVirtualUsableConstraint(EMemDataType memDataType, EMemAccessType memAccessType,
                                       const AddressReuseMode& rAddrReuseMode,
                                       ConstraintSet* constrSet) const override;

    // Address translation
    bool TranslateGvaToGpa(uint64 gva, uint64& rGpa, bool isInstr, const GenPageRequest* pPageReq) const;
    bool TranslateGpaToSpa(uint64 gpa, uint64& rSpa, bool isInstr, const GenPageRequest* pPageReq) const;
    bool TranslateGvaToSpa(uint64 gva, uint64& rSpa, bool isInstr, const GenPageRequest* pPageReq) const;

    // Page request interfaces — VS-stage handles GVA requests
    GenPageRequest* GenPageRequestInstance(bool isInstr = true, EMemAccessType memAccessType = EMemAccessType::Unknown) const override;
    GenPageRequest* GenPageRequestRegulated(bool isInstr = true, EMemAccessType memAccessType = EMemAccessType::Unknown, bool noFault = false) const override;
    bool VerifyVirtualAddress(uint64 va, uint64 size, bool isInstr, const GenPageRequest* pPageReq) const override;
    bool VerifyStreamingVa(uint64 va, uint64 size, bool isInstr) const override;

    // Accessors
    VmMapper* VsStageMapper() const { return mpVsStageMapper; }
    VmMapper* GStageMapper() const { return mpGStageMapper; }
    const AddressTagging* GetAddressTagging() const override;

    // VmPaMapper access — G-stage maps GPA to SPA
    VmPaMapper* VmPaMapperInstance() const override;

  private:
    VmMapper* mpVsStageMapper;  // VS-stage: GVA -> GPA (uses vsatp)
    VmMapper* mpGStageMapper;   // G-stage:  GPA -> SPA (uses hgatp)
    mutable VmPaMapper* mpGStagePaMapper; // For GPA->SPA mapping
  };

}

#endif
```

**Step 2: 创建实现文件 `base/src/TwoStageVmMapper.cc`**

核心逻辑：
```cpp
#include "TwoStageVmMapper.h"

#include "AddressTagging.h"
#include "Constraint.h"
#include "GenRequest.h"
#include "Generator.h"
#include "Log.h"
#include "VmPaMapper.h"

using namespace std;

namespace Force {

  TwoStageVmMapper::TwoStageVmMapper(VmMapper* pVsStageMapper, VmMapper* pGStageMapper)
    : VmMapper(nullptr), mpVsStageMapper(pVsStageMapper), mpGStageMapper(pGStageMapper), mpGStagePaMapper(nullptr)
  {
  }

  void TwoStageVmMapper::Setup(Generator* gen)
  {
    VmMapper::Setup(gen);
    mpVsStageMapper->Setup(gen);
    mpGStageMapper->Setup(gen);
  }

  void TwoStageVmMapper::Activate()
  {
    mpVsStageMapper->Activate();
    mpGStageMapper->Activate();
    VmMapper::Activate();
  }

  void TwoStageVmMapper::Initialize()
  {
    mpVsStageMapper->Initialize();
    mpGStageMapper->Initialize();
    VmMapper::Initialize();
  }

  void TwoStageVmMapper::Deactivate()
  {
    mpVsStageMapper->Deactivate();
    mpGStageMapper->Deactivate();
    VmMapper::Deactivate();
  }

  // 地址转译：GVA -> GPA (通过 VS-stage mapper)
  bool TwoStageVmMapper::TranslateGvaToGpa(uint64 gva, uint64& rGpa, bool isInstr, const GenPageRequest* pPageReq) const
  {
    // VS-stage mapper 内部维护 GVA->GPA 的页表映射
    // 查找对应的 Page 对象，获取其 GPA
    auto va_mapper = dynamic_cast<VmAddressSpace*>(mpVsStageMapper);
    if (va_mapper == nullptr) {
      LOG(fail) << "{TwoStageVmMapper::TranslateGvaToGpa} VS-stage mapper is not VmAddressSpace" << endl;
      return false;
    }

    // 通过查找 GVA 所在的 Page 来获取 GPA
    // 这需要调用 VmAddressSpace 的页面查找逻辑
    // 简化实现：遍历已映射的页面，找到包含 gva 的那个
    return va_mapper->LookupVirtualAddress(gva, rGpa, isInstr);
  }

  // 地址转译：GPA -> SPA (通过 G-stage mapper)
  bool TwoStageVmMapper::TranslateGpaToSpa(uint64 gpa, uint64& rSpa, bool isInstr, const GenPageRequest* pPageReq) const
  {
    auto gpa_mapper = dynamic_cast<VmAddressSpace*>(mpGStageMapper);
    if (gpa_mapper == nullptr) {
      LOG(fail) << "{TwoStageVmMapper::TranslateGpaToSpa} G-stage mapper is not VmAddressSpace" << endl;
      return false;
    }

    // 将 GPA 当作"虚拟地址"输入 G-stage mapper，得到 SPA
    return gpa_mapper->LookupVirtualAddress(gpa, rSpa, isInstr);
  }

  // 完整的两阶转译：GVA -> GPA -> SPA
  bool TwoStageVmMapper::TranslateGvaToSpa(uint64 gva, uint64& rSpa, bool isInstr, const GenPageRequest* pPageReq) const
  {
    uint64 gpa = 0;
    if (!TranslateGvaToGpa(gva, gpa, isInstr, pPageReq)) {
      return false;  // VS-stage 页表未映射此 GVA
    }

    if (!TranslateGpaToSpa(gpa, rSpa, isInstr, pPageReq)) {
      return false;  // G-stage 页表未映射此 GPA
    }

    return true;
  }

  // 虚拟地址可用性约束 — 使用 VS-stage 的约束（GVA 空间）
  const ConstraintSet* TwoStageVmMapper::VirtualUsableConstraintSet(bool isInstr) const
  {
    return mpVsStageMapper->VirtualUsableConstraintSet(isInstr);
  }

  // GenPageRequest — 委托给 VS-stage
  GenPageRequest* TwoStageVmMapper::GenPageRequestInstance(bool isInstr, EMemAccessType memAccessType) const
  {
    return mpVsStageMapper->GenPageRequestInstance(isInstr, memAccessType);
  }

  // VmPaMapper — 用于创建新的 GPA->SPA 映射
  VmPaMapper* TwoStageVmMapper::VmPaMapperInstance() const
  {
    if (mpGStagePaMapper == nullptr) {
      mpGStagePaMapper = mpGStageMapper->VmPaMapperInstance();
    }
    return mpGStagePaMapper;
  }

}
```

**Step 3: 需要在 VmAddressSpace 中添加 LookupVirtualAddress 方法**

在 `base/inc/VmAddressSpace.h` 中添加：
```cpp
//!< Look up the physical address for a given virtual address
virtual bool LookupVirtualAddress(uint64 va, uint64& rPa, bool isInstr) const;
```

**Step 4: Commit**

```bash
git add base/inc/TwoStageVmMapper.h base/src/TwoStageVmMapper.cc
git commit -m "feat: add TwoStageVmMapper for GVA->GPA->SPA two-stage translation"
```

---

## Phase 5: VmManager 扩展 — 管理两阶转译

### Task 8: 扩展 VmManager 支持 TwoStageVmMapper 组合

**Objective:** 让 VmManager 能够识别两阶转译模式，并组合 VS-stage 和 G-stage 的 VmMapper

**Files:**
- Modify: `base/inc/VmManager.h` — 添加两阶转译相关方法
- Modify: `base/src/VmManager.cc` — 实现两阶组合逻辑

**Step 1: 修改 VmManager.h**

在 VmManager 类中添加：
```cpp
// Two-stage translation support
bool IsTwoStageEnabled() const;
TwoStageVmMapper* GetTwoStageMapper() const;
void SetupTwoStageTranslation();
```

添加成员变量：
```cpp
TwoStageVmMapper* mpTwoStageMapper;  // Owned by VmManager
```

**Step 2: 修改 VmManager.cc**

```cpp
bool VmManager::IsTwoStageEnabled() const
{
  // 两阶转译启用条件：同时存在 HS 和 VS regime 的 active mapper
  auto hs_regime = mVmRegimes.at(EVmRegimeTypeBaseType(EVmRegimeType::HS));
  auto vs_regime = mVmRegimes.at(EVmRegimeTypeBaseType(EVmRegimeType::VS));
  return (hs_regime != nullptr && vs_regime != nullptr &&
          hs_regime->IsActive() && vs_regime->IsActive());
}

void VmManager::SetupTwoStageTranslation()
{
  if (!IsTwoStageEnabled()) {
    return;
  }

  auto vs_mapper = GetVmMapper(EVmRegimeType::VS);
  auto hs_mapper = GetVmMapper(EVmRegimeType::HS);

  if (vs_mapper && hs_mapper) {
    mpTwoStageMapper = new TwoStageVmMapper(vs_mapper, hs_mapper);
    mpTwoStageMapper->Setup(mpGenerator);
    mpTwoStageMapper->Activate();
  }
}
```

**Step 3: Commit**

```bash
git add base/inc/VmManager.h base/src/VmManager.cc
git commit -m "feat: add two-stage translation setup to VmManager"
```

---

### Task 9: 修改 VmInfoRISCV 识别两阶转译状态

**Objective:** 让 VmInfoRISCV 能够正确识别当前是否处于两阶转译模式

**Files:**
- Modify: `riscv/inc/VmInfoRISCV.h` — 添加两阶相关方法
- Modify: `riscv/src/VmInfoRISCV.cc` — 实现 hgatp/vsatp 状态读取

**Step 1: 修改 VmInfoRISCV.h**

添加：
```cpp
bool IsTwoStageTranslation() const;
EPagingMode GStagePagingMode() const;
uint64 HgatpValue() const;
```

添加成员变量：
```cpp
EPagingMode mGStageMode;
uint64 mHgatpValue;
uint64 mVsatpValue;
```

**Step 2: 修改 VmInfoRISCV.cc**

在 `GetCurrentStates` 方法中添加对 hgatp 和 vsatp 的读取：

```cpp
void VmInfoRISCV::GetCurrentStates(const Generator& rGen)
{
  // 原有的 satp 读取...
  auto reg_file = rGen.GetRegisterFile();
  auto satp_reg = reg_file->RegisterLookup("satp");
  GetRegisterFieldState(satp_reg, EVmInfoBoolType::MODE);

  // 新增：读取 vsatp 和 hgatp
  auto vsatp_reg = reg_file->RegisterLookup("vsatp");
  if (vsatp_reg != nullptr) {
    GetRegisterFieldState(vsatp_reg, EVmInfoBoolType::MODE);
    mVsatpValue = vsatp_reg->CurrentValue();
  }

  auto hgatp_reg = reg_file->RegisterLookup("hgatp");
  if (hgatp_reg != nullptr) {
    mHgatpValue = hgatp_reg->CurrentValue();
    // 从 hgatp.MODE 解析 G-stage paging mode
    // hgatp[63:60] = MODE: 8=Sv39x4, 9=Sv48x4, 0=Bare
    uint64 mode_field = (mHgatpValue >> 60) & 0xF;
    switch (mode_field) {
      case 0: mGStageMode = EPagingMode::Bare; break;
      case 8: mGStageMode = EPagingMode::Sv39x4; break;
      case 9: mGStageMode = EPagingMode::Sv48x4; break;
      default: mGStageMode = EPagingMode::Bare; break;
    }
  }

  mPrivilegeLevelType = rGen.PrivilegeLevel();
}

bool VmInfoRISCV::IsTwoStageTranslation() const
{
  return (mGStageMode != EPagingMode::Bare) && (mHgatpValue != 0);
}
```

**Step 3: Commit**

```bash
git add riscv/inc/VmInfoRISCV.h riscv/src/VmInfoRISCV.cc
git commit -m "feat: add two-stage translation detection to VmInfoRISCV"
```

---

## Phase 6: VmFactory 和 VmRegime 扩展

### Task 10: 扩展 VmFactoryRISCV 支持 stage 2 对象创建

**Objective:** 让 VmFactoryRISCV 能够创建 stage 2 的 VmDirectMapControlBlock 和 VmasControlBlock

**Files:**
- Modify: `riscv/src/VmFactoryRISCV.cc` — 增加 stage 参数传递

**Step 1: 修改 VmFactoryRISCV 的创建方法**

在 `VmFactoryRISCV` 中添加 stage 感知：

```cpp
VmDirectMapControlBlock* VmFactoryRISCV::CreateVmDirectMapControlBlock(const EMemBankType memBankType) const
{
  uint32 stage = (mVmRegimeType == EVmRegimeType::HS) ? 2 : 1;

  switch (mVmRegimeType)
  {
    case EVmRegimeType::M:
      return new VmDirectMapControlBlockRISCV(EPrivilegeLevelType::M, memBankType, stage);
    case EVmRegimeType::S:
    case EVmRegimeType::HS:
      return new VmDirectMapControlBlockRISCV(EPrivilegeLevelType::S, memBankType, stage);
    case EVmRegimeType::VS:
      return new VmDirectMapControlBlockRISCV(EPrivilegeLevelType::S, memBankType, stage);
    default:
      LOG(fail) << "{VmFactoryRISCV::CreateVmDirectMapControlBlock} Unsupported EVmRegimeType" << endl;
      FAIL("invalid_regime_type_vm_dmcb");
  }
  return nullptr;
}
```

**Step 2: Commit**

```bash
git add riscv/src/VmFactoryRISCV.cc
git commit -m "feat: pass stage parameter in VmFactoryRISCV object creation"
```

---

## Phase 7: 配置文件集成

### Task 11: 创建支持两阶转译的配置文件

**Objective:** 创建一个新的配置文件，同时加载 stage 1 和 stage 2 的 paging 定义

**Files:**
- Create: `config/riscv_rv64_twostage.config`

**Step 1: 基于 riscv_rv64_sv39.config 创建**

```bash
cp config/riscv_rv64_sv39.config config/riscv_rv64_twostage.config
```

**Step 2: 修改配置文件，添加 stage 2 paging files**

```xml
<!-- 在 <paging_files> 部分添加 -->
<paging_files>
  <!-- Stage 1: VS-stage (Sv39) -->
  <paging_file file="riscv/arch_data/paging/page_tables_sv39.xml"/>
  <!-- Stage 2: G-stage (Sv39x4) -->
  <paging_file file="riscv/arch_data/paging/page_tables_sv39x4_gstage.xml"/>
</paging_files>

<!-- 在 <choices_files> 部分添加 -->
<choices_files>
  ...
  <choices_file file="riscv/arch_data/paging/paging_choices_sv39.xml"/>
  <choices_file file="riscv/arch_data/paging/paging_choices_sv39x4_gstage.xml"/>
</choices_files>
```

**Step 3: Commit**

```bash
git add config/riscv_rv64_twostage.config
git commit -m "feat: add two-stage translation config file"
```

---

## Phase 8: Python 层扩展

### Task 12: 扩展 GenThreadRISCV 支持两阶转译 API

**Objective:** 在 Python 层添加设置两阶转译的 API

**Files:**
- Modify: `py/riscv/GenThreadRISCV.py`
- Create: `py/riscv/TwoStageSetup.py`

**Step 1: 在 GenThreadRISCV 中添加两阶转译设置方法**

```python
class GenThreadSetupSeqRISCV(GenThreadSetupSequence):
    # ... 现有代码 ...

    def setupTwoStageTranslation(self):
        """Setup two-stage address translation (VS-stage + G-stage)"""
        # 配置 VS-stage (vsatp)
        self.virtualMemoryRequest(
            "PhysicalRegion",
            {
                "RegionType": "VsStageRegion",
                "Size": 0x10000000,  # 256MB for VS-stage
                "Type": "IO",
                "Bank": 0,
            },
        )

        # 配置 G-stage (hgatp)
        self.virtualMemoryRequest(
            "PhysicalRegion",
            {
                "RegionType": "GStageRegion",
                "Size": 0x10000000,  # 256MB for G-stage
                "Type": "IO",
                "Bank": 0,
            },
        )

        # 设置 hgatp 寄存器启用两阶转译
        self.genThread.setHypervisorRegisters(
            hgatp_mode="Sv39x4",
            vmid=0,
        )
```

**Step 2: Commit**

```bash
git add py/riscv/GenThreadRISCV.py
git commit -m "feat: add two-stage translation setup API to GenThreadRISCV"
```

---

## Phase 9: PTE 属性类扩展

### Task 13: 创建 stage 2 特定的 PTE 属性类

**Objective:** 创建 RSW2 等 stage 2 特有 PTE 属性的处理类

**Files:**
- Create: `riscv/inc/PteAttributeRISCV.h` — 添加 RSW2PteAttributeRISCV 类
- Create: `riscv/src/PteAttributeRISCV.cc` — 实现

**Step 1: 在 PteAttributeRISCV.h 中添加**

```cpp
/*!
  \class RSW2PteAttributeRISCV
  \brief PTE attribute for stage 2 RSW (Reserved for Software) field
*/
class RSW2PteAttributeRISCV : public PteAttribute
{
public:
  Object* Clone() const override { return new RSW2PteAttributeRISCV(*this); }
  const char* Type() const override { return "RSW2PteAttributeRISCV"; }

  RSW2PteAttributeRISCV() : PteAttribute() { }
  ~RSW2PteAttributeRISCV() { }

  void Generate(const GenPageRequest& rPagingReq, const VmAddressSpace& rVmas, PageTableEntry& rPte) override;
protected:
  RSW2PteAttributeRISCV(const RSW2PteAttributeRISCV& rOther) : PteAttribute(rOther) { }
};
```

**Step 2: 在 VmFactoryRISCV::PteAttributeInstance 中注册**

```cpp
PteAttribute* VmFactoryRISCV::PteAttributeInstance(EPteAttributeType attrType) const
{
  switch (attrType)
  {
    case EPteAttributeType::Address:    return new AddressPteAttributeRISCV();
    case EPteAttributeType::DA:         return new DAPteAttributeRISCV();
    case EPteAttributeType::G:          return new GPteAttributeRISCV();
    case EPteAttributeType::U:          return new UPteAttributeRISCV();
    case EPteAttributeType::X:          return new XPteAttributeRISCV();
    case EPteAttributeType::WR:         return new WRPteAttributeRISCV();
    case EPteAttributeType::V:          return new VPteAttributeRISCV();
    case EPteAttributeType::RSW2:       return new RSW2PteAttributeRISCV();
    default:
      LOG(fail) << "{VmFactoryRISCV::PteAttributeInstance} Unknown attribute type" << endl;
      FAIL("unknown_pte_attribute_type");
  }
  return nullptr;
}
```

**Step 3: Commit**

```bash
git add riscv/inc/PteAttributeRISCV.h riscv/src/PteAttributeRISCV.cc riscv/src/VmFactoryRISCV.cc
git commit -m "feat: add RSW2 PTE attribute class for stage 2 translation"
```

---

## Phase 10: 编译和验证

### Task 14: 更新 Makefile 和编译系统

**Objective:** 确保新文件被包含在编译系统中

**Files:**
- Modify: `riscv/Makefile` — 确认新 .cc 文件自动被包含
- Modify: `base/Makefile` — 确认 TwoStageVmMapper.cc 被包含

**Step 1: 检查 Makefile 的自动发现机制**

FORCE-RISCV 的 Makefile 通常使用 `wildcard` 自动发现源文件：
```bash
grep "wildcard\|SRCS" base/Makefile riscv/Makefile
```

如果使用 wildcard，新文件会自动被包含。否则需要手动添加。

**Step 2: 尝试编译**

```bash
cd /home/guoshibo/force-riscv
make clean
make -j4
```

**Step 3: 修复编译错误**

根据编译错误逐一修复：
- 缺少头文件 include
- 构造函数签名不匹配
- 虚函数 override 签名不一致

**Step 4: Commit**

```bash
git add base/Makefile riscv/Makefile
git commit -m "build: update Makefiles for two-stage translation source files"
```

---

### Task 15: 编写单元测试

**Objective:** 验证两阶转译的正确性

**Files:**
- Create: `unit_tests/test_two_stage_translation.py`

**Step 1: 创建测试文件**

```python
"""
Test two-stage address translation (GVA -> GPA -> SPA)
"""
import Macros
from base.Sequence import Sequence


class TestTwoStageTranslation(Sequence):
    """Test basic two-stage address translation"""

    def generate(self, **kwargs):
        # 1. Setup VS-stage page tables (GVA -> GPA)
        self.genThread.setupVsStagePaging(mode="Sv39")

        # 2. Setup G-stage page tables (GPA -> SPA)
        self.genThread.setupGStagePaging(mode="Sv39x4")

        # 3. Verify two-stage mapper is active
        assert self.genThread.isTwoStageEnabled(), "Two-stage should be enabled"

        # 4. Generate some instructions that use virtual addresses
        for i in range(10):
            self.genInstruction("ADDI")
            self.genInstruction("LD")

        # 5. Verify page faults can occur at both stages
        self.genInstruction("LD", exception_check=True)
```

**Step 2: Commit**

```bash
git add unit_tests/test_two_stage_translation.py
git commit -m "test: add basic two-stage translation unit test"
```

---

## Phase 11: 文档和示例

### Task 16: 创建两阶转译示例模板

**Objective:** 提供一个完整的 Python 测试模板示例

**Files:**
- Create: `examples/riscv/two_stage_translation_example.py`

**Step 1: 创建示例文件**

```python
"""
Example: Two-Stage Address Translation Test

This example demonstrates how to use FORCE-RISCV to generate tests
for RISC-V Hypervisor Extension two-stage address translation.

Usage:
  friscv -c config/riscv_rv64_twostage.config examples/riscv/two_stage_translation_example.py
"""

import Macros
from base.Sequence import Sequence
import riscv.GenThreadRISCV as GenThreadRISCV


class BootSequence(Sequence):
    """Setup hypervisor environment"""

    def generate(self, **kwargs):
        # Setup VS-stage (GVA -> GPA)
        self.genThread.setupVsStagePaging(mode="Sv39")

        # Setup G-stage (GPA -> SPA)
        self.genThread.setupGStagePaging(mode="Sv39x4")

        # Configure hstatus register
        self.genThread.setRegisterField("hstatus", "SPV", 1)  # Set to virtual mode


class MainTestSequence(Sequence):
    """Generate instructions under two-stage translation"""

    def generate(self, **kwargs):
        # Generate various memory operations
        for _ in range(100):
            self.genInstruction("LD")
            self.genInstruction("SD")
            self.genInstruction("ADDI")

        # Trigger some page faults for testing
        self.genInstruction("LD", may_fault=True)
```

**Step 2: Commit**

```bash
git add examples/riscv/two_stage_translation_example.py
git commit -m "docs: add two-stage translation example template"
```

---

## 修改文件汇总

| Phase | 类型 | 文件路径 |
|-------|------|----------|
| 1 | Modify | `utils/enum_classes/riscv_enum_classes.py` |
| 1 | Auto-gen | `riscv/inc/EnumsRISCV.h` |
| 1 | Auto-gen | `base/inc/Enums.h` |
| 2 | Create | `riscv/arch_data/paging/page_tables_sv48x4_gstage.xml` |
| 2 | Create | `riscv/arch_data/paging/page_tables_sv39x4_gstage.xml` |
| 2 | Create | `riscv/arch_data/paging/paging_choices_sv48x4_gstage.xml` |
| 3 | Modify | `base/inc/VmControlBlock.h` |
| 3 | Modify | `base/src/VmControlBlock.cc` |
| 3 | Modify | `base/inc/VmDirectMapControlBlock.h` |
| 3 | Modify | `base/src/VmDirectMapControlBlock.cc` |
| 3 | Modify | `riscv/inc/VmDirectMapControlBlockRISCV.h` |
| 3 | Modify | `riscv/src/VmDirectMapControlBlockRISCV.cc` |
| 4 | **Create** | `base/inc/TwoStageVmMapper.h` |
| 4 | **Create** | `base/src/TwoStageVmMapper.cc` |
| 4 | Modify | `base/inc/VmAddressSpace.h` |
| 5 | Modify | `base/inc/VmManager.h` |
| 5 | Modify | `base/src/VmManager.cc` |
| 5 | Modify | `riscv/inc/VmInfoRISCV.h` |
| 5 | Modify | `riscv/src/VmInfoRISCV.cc` |
| 6 | Modify | `riscv/src/VmFactoryRISCV.cc` |
| 7 | Create | `config/riscv_rv64_twostage.config` |
| 8 | Modify | `py/riscv/GenThreadRISCV.py` |
| 9 | Modify | `riscv/inc/PteAttributeRISCV.h` |
| 9 | Modify | `riscv/src/PteAttributeRISCV.cc` |
| 10 | Modify | `base/Makefile` / `riscv/Makefile` |
| 10 | Create | `unit_tests/test_two_stage_translation.py` |
| 11 | Create | `examples/riscv/two_stage_translation_example.py` |

---

## 关键架构决策

1. **组合而非继承**：TwoStageVmMapper 组合两个 VmMapper 而非继承，保持单阶转译代码不变
2. **stage 字段**：在 VmControlBlock 层级增加 stage 参数，区分 stage 1 和 stage 2
3. **XML 驱动**：通过独立的 XML 文件定义 stage 2 PTE，保持与现有配置系统一致
4. **向后兼容**：所有修改都是扩展性的，不破坏现有的单阶转译功能
5. **VS-stage 负责 GVA 空间**：虚拟地址约束和页面请求都基于 VS-stage（GVA 空间）
6. **G-stage 负责 GPA→SPA**：G-stage 将 GPA 视为"虚拟地址"，映射到 SPA

---

## 风险和注意事项

1. **页表共享问题**：VS-stage 的页表和 G-stage 的页表需要分配到不同的物理内存区域
2. **异常处理**：两阶转译会产生不同类型的页表异常（guest page fault vs regular page fault）
3. **VMID 管理**：需要实现 VMID 的分配和回收机制
4. **地址别名**：两阶转译下的地址别名为 GVA→GPA→SPA 的映射关系更复杂
5. **测试覆盖**：需要额外的测试来验证两种页表的正确交互
