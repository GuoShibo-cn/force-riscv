# RISC-V Hypervisor Extension 渐进式实现计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 在 FORCE-RISCV 项目中分三阶段完整实现 RISC-V Hypervisor Extension 支持，包括两阶地址转译、Hypervisor 指令、Guest Page Fault、虚拟化中断和特权级切换。

**Architecture:** 基于现有单阶转译架构渐进扩展：
- Phase 1: 两阶转译核心 (VS-stage + G-stage VmMapper 组合器)
- Phase 2: Hypervisor 指令 (HFENCE/HLV/HSV) + Guest Page Fault 异常 + CSR 完善
- Phase 3: 虚拟化中断 + VMID 管理 + HS/VS 特权切换 + 高级功能

**Tech Stack:** C++17, Python 3, pybind11, RISC-V Hypervisor Extension Spec v1.0

---

## Phase 1: 两阶地址转译核心 (~10 天)

**目标：** 实现 VS-stage (GVA→GPA) + G-stage (GPA→SPA) 的两阶地址转译，不依赖完整的 H-extension 指令和异常支持。

---

### Task 1: 扩展 PagingMode 枚举，添加 Hypervisor 模式

**Objective:** 在 enum_classes 中添加 Sv39x4 和 Sv48x4 等两阶 paging mode

**Files:**
- Modify: `utils/enum_classes/riscv_enum_classes.py` — 找到 "PagingMode" 条目 (第 81-91 行)

**Step 1: 修改 PagingMode 枚举定义**

```python
# 原定义 (第 81-91 行):
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

### Task 2: 扩展 VmContextParamType，添加 Hypervisor 相关参数

**Objective:** 添加 hstatus.VGEIN、hgatp.VMID 等两阶转译所需的上下文参数类型

**Files:**
- Modify: `utils/enum_classes/riscv_enum_classes.py` — 找到 "VmContextParamType" 条目 (第 31-46 行)

**Step 1: 修改 VmContextParamType 枚举**

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

### Task 3: 创建 stage 2 PTE XML 定义文件

**Objective:** 创建 G-stage 的 PTE 定义文件，支持 Sv39x4 和 Sv48x4 模式

**Files:**
- Create: `riscv/arch_data/paging/page_tables_sv48x4_gstage.xml`
- Create: `riscv/arch_data/paging/page_tables_sv39x4_gstage.xml`

**Step 1: 创建 page_tables_sv48x4_gstage.xml**

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

**Step 2: 创建 Sv39x4 版本**

类似 Sv48x4，但只有 3 级页表 (level 0/1/2)，去掉 512G。

**Step 3: Commit**

```bash
git add riscv/arch_data/paging/page_tables_sv48x4_gstage.xml riscv/arch_data/paging/page_tables_sv39x4_gstage.xml
git commit -m "feat: add stage 2 PTE definitions for Sv48x4/Sv39x4 hypervisor modes"
```

---

### Task 4: 扩展 VmControlBlock 支持 stage 字段

**Objective:** 让 VmControlBlock 能够标识自己是 stage 1 还是 stage 2

**Files:**
- Modify: `base/inc/VmControlBlock.h`
- Modify: `base/src/VmControlBlock.cc`
- Modify: `base/inc/VmDirectMapControlBlock.h`
- Modify: `base/src/VmDirectMapControlBlock.cc`
- Modify: `riscv/inc/VmDirectMapControlBlockRISCV.h`
- Modify: `riscv/src/VmDirectMapControlBlockRISCV.cc`

**Step 1: 修改 VmControlBlock 构造函数**

在 `base/inc/VmControlBlock.h` 中：
```cpp
// 原签名:
VmControlBlock(EPrivilegeLevelType privType, EMemBankType memType);

// 修改为:
VmControlBlock(EPrivilegeLevelType privType, EMemBankType memType, uint32 stage = 1);
```

在 `base/src/VmControlBlock.cc` 中：
```cpp
// 原初始化:
VmControlBlock::VmControlBlock(EPrivilegeLevelType privType, EMemBankType memType)
  : VmContext(), mPrivilegeLevel(privType), mDefaultMemoryBank(memType),
    mBigEndian(false), mStage(0), mMaxPhysicalAddress(0), mVmContextParameters()

// 修改为:
VmControlBlock::VmControlBlock(EPrivilegeLevelType privType, EMemBankType memType, uint32 stage)
  : VmContext(), mPrivilegeLevel(privType), mDefaultMemoryBank(memType),
    mBigEndian(false), mStage(stage), mMaxPhysicalAddress(0), mVmContextParameters()
```

**Step 2: 同步修改派生类**

同样模式修改 VmDirectMapControlBlock 和 VmDirectMapControlBlockRISCV。

**Step 3: Commit**

```bash
git add base/inc/VmControlBlock.h base/src/VmControlBlock.cc base/inc/VmDirectMapControlBlock.h base/src/VmDirectMapControlBlock.cc riscv/inc/VmDirectMapControlBlockRISCV.h riscv/src/VmDirectMapControlBlockRISCV.cc
git commit -m "refactor: add stage parameter to VmControlBlock constructor hierarchy"
```

---

### Task 5: 创建 TwoStageVmMapper 类（核心组件）

**Objective:** 创建组合 VmMapper，串联 VS-stage (GVA→GPA) 和 G-stage (GPA→SPA) 的两阶转译

**Files:**
- Create: `base/inc/TwoStageVmMapper.h`
- Create: `base/src/TwoStageVmMapper.cc`
- Modify: `base/inc/VmAddressSpace.h` — 添加 LookupVirtualAddress 方法

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
  class VmPaMapper;

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
    bool TranslateGvaToGpa(uint64 gva, uint64& rGpa, bool isInstr) const;
    bool TranslateGpaToSpa(uint64 gpa, uint64& rSpa, bool isInstr) const;
    bool TranslateGvaToSpa(uint64 gva, uint64& rSpa, bool isInstr) const;

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
    if (mpVsStageMapper) mpVsStageMapper->Setup(gen);
    if (mpGStageMapper) mpGStageMapper->Setup(gen);
  }

  void TwoStageVmMapper::Activate()
  {
    if (mpVsStageMapper) mpVsStageMapper->Activate();
    if (mpGStageMapper) mpGStageMapper->Activate();
    VmMapper::Activate();
  }

  void TwoStageVmMapper::Initialize()
  {
    if (mpVsStageMapper) mpVsStageMapper->Initialize();
    if (mpGStageMapper) mpGStageMapper->Initialize();
    VmMapper::Initialize();
  }

  void TwoStageVmMapper::Deactivate()
  {
    if (mpVsStageMapper) mpVsStageMapper->Deactivate();
    if (mpGStageMapper) mpGStageMapper->Deactivate();
    VmMapper::Deactivate();
  }

  void TwoStageVmMapper::AddPhysicalRegion(PhysicalRegion* pRegion, bool map)
  {
    if (mpVsStageMapper) mpVsStageMapper->AddPhysicalRegion(pRegion, map);
    if (mpGStageMapper) mpGStageMapper->AddPhysicalRegion(pRegion, map);
  }

  void TwoStageVmMapper::Update()
  {
    if (mpVsStageMapper) mpVsStageMapper->Update();
    if (mpGStageMapper) mpGStageMapper->Update();
  }

  const ConstraintSet* TwoStageVmMapper::VirtualUsableConstraintSet(bool isInstr) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->VirtualUsableConstraintSet(isInstr);
    return nullptr;
  }

  ConstraintSet* TwoStageVmMapper::VirtualUsableConstraintSetClone(bool isInstr) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->VirtualUsableConstraintSetClone(isInstr);
    return nullptr;
  }

  const ConstraintSet* TwoStageVmMapper::VirtualSharedConstraintSet() const
  {
    if (mpVsStageMapper) return mpVsStageMapper->VirtualSharedConstraintSet();
    return nullptr;
  }

  void TwoStageVmMapper::ApplyVirtualUsableConstraint(EMemDataType memDataType, EMemAccessType memAccessType,
                                                       const AddressReuseMode& rAddrReuseMode,
                                                       ConstraintSet* constrSet) const
  {
    if (mpVsStageMapper) {
      mpVsStageMapper->ApplyVirtualUsableConstraint(memDataType, memAccessType, rAddrReuseMode, constrSet);
    }
  }

  GenPageRequest* TwoStageVmMapper::GenPageRequestInstance(bool isInstr, EMemAccessType memAccessType) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->GenPageRequestInstance(isInstr, memAccessType);
    return nullptr;
  }

  GenPageRequest* TwoStageVmMapper::GenPageRequestRegulated(bool isInstr, EMemAccessType memAccessType, bool noFault) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->GenPageRequestRegulated(isInstr, memAccessType, noFault);
    return nullptr;
  }

  bool TwoStageVmMapper::VerifyVirtualAddress(uint64 va, uint64 size, bool isInstr, const GenPageRequest* pPageReq) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->VerifyVirtualAddress(va, size, isInstr, pPageReq);
    return false;
  }

  bool TwoStageVmMapper::VerifyStreamingVa(uint64 va, uint64 size, bool isInstr) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->VerifyStreamingVa(va, size, isInstr);
    return false;
  }

  const AddressTagging* TwoStageVmMapper::GetAddressTagging() const
  {
    if (mpVsStageMapper) return mpVsStageMapper->GetAddressTagging();
    return nullptr;
  }

  VmPaMapper* TwoStageVmMapper::VmPaMapperInstance() const
  {
    if (mpGStageMapper) return mpGStageMapper->VmPaMapperInstance();
    return nullptr;
  }

  bool TwoStageVmMapper::TranslateGvaToGpa(uint64 gva, uint64& rGpa, bool isInstr) const
  {
    auto va_mapper = dynamic_cast<VmAddressSpace*>(mpVsStageMapper);
    if (va_mapper == nullptr) {
      LOG(fail) << "{TwoStageVmMapper::TranslateGvaToGpa} VS-stage mapper is not VmAddressSpace" << endl;
      return false;
    }
    return va_mapper->LookupVirtualAddress(gva, rGpa, isInstr);
  }

  bool TwoStageVmMapper::TranslateGpaToSpa(uint64 gpa, uint64& rSpa, bool isInstr) const
  {
    auto gpa_mapper = dynamic_cast<VmAddressSpace*>(mpGStageMapper);
    if (gpa_mapper == nullptr) {
      LOG(fail) << "{TwoStageVmMapper::TranslateGpaToSpa} G-stage mapper is not VmAddressSpace" << endl;
      return false;
    }
    return gpa_mapper->LookupVirtualAddress(gpa, rSpa, isInstr);
  }

  bool TwoStageVmMapper::TranslateGvaToSpa(uint64 gva, uint64& rSpa, bool isInstr) const
  {
    uint64 gpa = 0;
    if (!TranslateGvaToGpa(gva, gpa, isInstr)) {
      return false;
    }
    return TranslateGpaToSpa(gpa, rSpa, isInstr);
  }

}
```

**Step 3: 在 VmAddressSpace.h 中添加 LookupVirtualAddress 方法**

```cpp
//!< Look up the physical address for a given virtual address
virtual bool LookupVirtualAddress(uint64 va, uint64& rPa, bool isInstr) const;
```

**Step 4: Commit**

```bash
git add base/inc/TwoStageVmMapper.h base/src/TwoStageVmMapper.cc base/inc/VmAddressSpace.h
git commit -m "feat: add TwoStageVmMapper for GVA->GPA->SPA two-stage translation"
```

---

### Task 6: 扩展 VmManager 支持 TwoStageVmMapper 组合

**Objective:** 让 VmManager 能够识别两阶转译模式，并组合 VS-stage 和 G-stage 的 VmMapper

**Files:**
- Modify: `base/inc/VmManager.h`
- Modify: `base/src/VmManager.cc`

**Step 1: 修改 VmManager.h**

添加成员变量：
```cpp
#include "TwoStageVmMapper.h"

// 在 private 区域添加:
TwoStageVmMapper* mpTwoStageMapper;
```

添加公共方法：
```cpp
// Two-stage translation support
bool IsTwoStageEnabled() const;
TwoStageVmMapper* GetTwoStageMapper() const;
void SetupTwoStageTranslation();
```

**Step 2: 修改 VmManager.cc**

```cpp
bool VmManager::IsTwoStageEnabled() const
{
  auto hs_regime = mVmRegimes.at(EVmRegimeTypeBaseType(EVmRegimeType::HS));
  auto vs_regime = mVmRegimes.at(EVmRegimeTypeBaseType(EVmRegimeType::VS));
  return (hs_regime != nullptr && vs_regime != nullptr &&
          hs_regime->IsActive() && vs_regime->IsActive());
}

TwoStageVmMapper* VmManager::GetTwoStageMapper() const
{
  return mpTwoStageMapper;
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

### Task 7: 扩展 VmFactoryRISCV 和 VmInfoRISCV

**Objective:** 让 Factory 传递 stage 参数，让 VmInfo 识别两阶状态

**Files:**
- Modify: `riscv/src/VmFactoryRISCV.cc`
- Modify: `riscv/inc/VmInfoRISCV.h`
- Modify: `riscv/src/VmInfoRISCV.cc`

**Step 1: 修改 VmFactoryRISCV.cc**

在创建 DirectMapControlBlock 时传递 stage：
```cpp
uint32 stage = (mVmRegimeType == EVmRegimeType::HS) ? 2 : 1;
```

**Step 2: 修改 VmInfoRISCV**

添加方法：
```cpp
bool IsTwoStageTranslation() const;
EPagingMode GStagePagingMode() const;
```

在 GetCurrentStates 中读取 hgatp/vsatp 状态。

**Step 3: Commit**

```bash
git add riscv/src/VmFactoryRISCV.cc riscv/inc/VmInfoRISCV.h riscv/src/VmInfoRISCV.cc
git commit -m "feat: add two-stage detection and stage-aware factory"
```

---

### Task 8: 创建两阶转译配置文件和示例

**Objective:** 创建配置文件和 Python 测试模板

**Files:**
- Create: `config/riscv_rv64_twostage.config`
- Create: `examples/riscv/two_stage_translation_example.py`

**Step 1: 创建配置文件**

基于 riscv_rv64_sv39.config 复制，添加：
```xml
<paging_files>
  <paging_file file="riscv/arch_data/paging/page_tables_sv39.xml"/>
  <paging_file file="riscv/arch_data/paging/page_tables_sv39x4_gstage.xml"/>
</paging_files>
```

**Step 2: 创建示例模板**

```python
"""Two-Stage Address Translation Example"""
from base.Sequence import Sequence

class TwoStageSetup(Sequence):
    def generate(self, **kwargs):
        self.genThread.setupVsStagePaging(mode="Sv39")
        self.genThread.setupGStagePaging(mode="Sv39x4")

class MainTest(Sequence):
    def generate(self, **kwargs):
        for _ in range(100):
            self.genInstruction("ADDI")
            self.genInstruction("LD")
```

**Step 3: Commit**

```bash
git add config/riscv_rv64_twostage.config examples/riscv/two_stage_translation_example.py
git commit -m "docs: add two-stage config and example template"
```

---

## Phase 2: 基础 Hypervisor 支持 (~10 天)

**目标：** 添加 H-extension 指令、Guest Page Fault 异常、缺失 CSR 完善，使 Phase 1 的两阶转译能够实际运行和验证。

---

### Task 9: 添加 Hypervisor 指令定义

**Objective:** 在 priv_instructions.xml 中添加 HFENCE、HLV/HSV、HINVAL 等指令

**Files:**
- Modify: `riscv/arch_data/instr/priv_instructions.xml`

**Step 1: 添加 HFENCE 指令**

```xml
<!-- HFENCE.VVMA: Flush VS-stage TLB -->
<I name="HFENCE.VVMA" isa="RISCV" group="System" extension="RV64H">
  <O name="const_bits" type="Constant" bits="31-25,14-12,11-7,6-0" value="0010011000000001110011"/>
  <O name="rs2" type="GPR" bits="24-20" access="Read" choices="GPRs"/>
  <O name="rs1" type="GPR" bits="19-15" access="Read" choices="GPRs"/>
  <asm format="HFENCE.VVMA %s, %s" op1="rs2" op2="rs1"/>
</I>

<!-- HFENCE.GVMA: Flush G-stage TLB -->
<I name="HFENCE.GVMA" isa="RISCV" group="System" extension="RV64H">
  <O name="const_bits" type="Constant" bits="31-25,14-12,11-7,6-0" value="0010001000000001110011"/>
  <O name="rs2" type="GPR" bits="24-20" access="Read" choices="GPRs"/>
  <O name="rs1" type="GPR" bits="19-15" access="Read" choices="GPRs"/>
  <asm format="HFENCE.GVMA %s, %s" op1="rs2" op2="rs1"/>
</I>
```

**Step 2: 添加 HLV 指令（虚拟化 Load）**

```xml
<!-- HLV.B: Hypervisor Load Byte -->
<I name="HLV.B" isa="RISCV" group="System" extension="RV64H">
  <O name="const_bits" type="Constant" bits="31-25,14-12,6-0" value="01000000100001110011"/>
  <O name="rd" type="GPR" bits="11-7" access="Write" choices="GPRs"/>
  <O name="rs1" type="GPR" bits="19-15" access="Read" choices="GPRs"/>
  <O name="rs2" type="GPR" bits="24-20" access="Read" choices="GPRs"/>
  <asm format="HLV.B %s, (%s), %s" op1="rd" op2="rs1" op3="rs2"/>
</I>

<!-- HLV.H, HLV.W, HLV.D 类似 -->
```

**Step 3: 添加 HSV 指令（虚拟化 Store）**

```xml
<!-- HSV.B: Hypervisor Store Byte -->
<I name="HSV.B" isa="RISCV" group="System" extension="RV64H">
  <O name="const_bits" type="Constant" bits="31-25,14-12,6-0" value="01000000110001110011"/>
  <O name="rs1" type="GPR" bits="19-15" access="Read" choices="GPRs"/>
  <O name="rs2" type="GPR" bits="24-20" access="Read" choices="GPRs"/>
  <asm format="HSV.B %s, (%s)" op1="rs2" op2="rs1"/>
</I>
```

**Step 4: 添加 HINVAL 指令**

```xml
<!-- HINVAL.VVMA -->
<I name="HINVAL.VVMA" isa="RISCV" group="System" extension="RV64H">
  <O name="const_bits" type="Constant" bits="31-25,14-12,11-7,6-0" value="0011011000000001110011"/>
  <O name="rs2" type="GPR" bits="24-20" access="Read" choices="GPRs"/>
  <O name="rs1" type="GPR" bits="19-15" access="Read" choices="GPRs"/>
  <asm format="HINVAL.VVMA %s, %s" op1="rs2" op2="rs1"/>
</I>
```

**Step 5: Commit**

```bash
git add riscv/arch_data/instr/priv_instructions.xml
git commit -m "feat: add H-extension instructions (HFENCE/HLV/HSV/HINVAL)"
```

---

### Task 10: 添加 Guest Page Fault 异常支持

**Objective:** 在异常系统中添加 Guest Page Fault (code 22/23/24) 和 Virtual Instruction (code 20)

**Files:**
- Modify: `utils/enum_classes/base_enum_classes.py` — ExceptionClassType
- Modify: `utils/enum_classes/riscv_enum_classes.py` — PagingExceptionType
- Modify: `riscv/src/GenExceptionAgentRISCV.cc` — 处理新异常
- Modify: `riscv/inc/GenExceptionAgentRISCV.h`

**Step 1: 扩展 ExceptionClassType**

在 `base_enum_classes.py` 中：
```python
    [
        "ExceptionClassType",
        "unsigned char",
        "Types of exception classes.",
        [
            ("InstrAddrMisaligned", 0),
            ("InstrAccessFault", 1),
            ("IllegalInstr", 2),
            ("Breakpoint", 3),
            ("LoadAddrMisaligned", 4),
            ("LoadAccessFault", 5),
            ("StoreAmoAddrMisaligned", 6),
            ("StoreAmoAccessFault", 7),
            ("EnvCallFromUMode", 8),
            ("EnvCallFromSMode", 9),
            ("EnvCallFromVU", 10),
            ("EnvCallFromHS", 11),
            ("EnvCallFromMMode", 12),
            ("InstrPageFault", 13),
            ("LoadPageFault", 14),
            ("StoreAmoPageFault", 15),
            ("InstrGuestPageFault", 16),
            ("LoadGuestPageFault", 17),
            ("StoreAmoGuestPageFault", 18),
            ("VirtualInstruction", 19),
        ],
    ],
```

**Step 2: 扩展 PagingExceptionType**

在 `riscv_enum_classes.py` 中：
```python
    [
        "PagingExceptionType",
        "unsigned char",
        "Paging exception types.",
        [
            ("InstructionAccessFault", 0),
            ("LoadAccessFault", 1),
            ("StoreAmoAccessFault", 2),
            ("InstructionPageFault", 3),
            ("LoadPageFault", 4),
            ("StoreAmoPageFault", 5),
            ("InstrGuestPageFault", 6),
            ("LoadGuestPageFault", 7),
            ("StoreAmoGuestPageFault", 8),
        ],
    ],
```

**Step 3: 修改 GenExceptionAgentRISCV.cc**

在 HandleException 方法中添加对 Guest Page Fault 的处理：
```cpp
case EPagingExceptionType::InstrGuestPageFault:
  // Fill htval with faulting GVA
  // Fill htinst with trapped instruction
  GenerateGuestPageFaultHandler();
  break;
```

**Step 4: 重新生成枚举并 Commit**

```bash
make enums
git add utils/enum_classes/*.py riscv/inc/EnumsRISCV.h base/inc/Enums.h riscv/src/GenExceptionAgentRISCV.cc
git commit -m "feat: add Guest Page Fault and Virtual Instruction exception support"
```

---

### Task 11: 完善缺失的 CSR 寄存器

**Objective:** 添加 hvip/hvien/hvictl/henvcfg 等缺失的 CSR 定义

**Files:**
- Modify: `riscv/arch_data/reg/system_registers_rv64.xml`

**Step 1: 添加缺失的寄存器**

```xml
<!-- HVIP: Hypervisor Virtual Interrupt Pending -->
<register boot="0" index="0x600" name="hvip" size="64" type="SysReg">
  <register_field name="VSSIP" physical_register="hvip" size="1" bits="2"/>
  <register_field name="VTIP" physical_register="hvip" size="1" bits="6"/>
  <register_field name="VSEIP" physical_register="hvip" size="1" bits="10"/>
  <register_field name="SGEIP" physical_register="hvip" size="1" bits="12"/>
</register>

<!-- HVIEN: Hypervisor Virtual Interrupt Enable -->
<register boot="0" index="0x630" name="hvien" size="64" type="SysReg">
  <register_field name="WPRI_VAR" physical_register="hvien" size="64"/>
</register>

<!-- HVICTL: Hypervisor Virtual Interrupt Control -->
<register boot="0" index="0x631" name="hvictl" size="64" type="SysReg">
  <register_field name="IPRIOM" physical_register="hvictl" size="1" bits="30"/>
  <register_field name="IPRIO" physical_register="hvictl" size="8" bits="22"/>
  <register_field name="VTI" physical_register="hvictl" size="1" bits="19"/>
  <register_field name="WPRI" physical_register="hvictl" size="19" bits="0"/>
</register>

<!-- HENVC FG: Hypervisor Environment Configuration -->
<register boot="0" index="0x60A" name="henvcfg" size="64" type="SysReg">
  <register_field name="WPRI" physical_register="henvcfg" size="56" bits="8"/>
  <register_field name="CBIE" physical_register="henvcfg" size="2" bits="6"/>
  <register_field name="CBCFE" physical_register="henvcfg" size="1" bits="5"/>
  <register_field name="CBZE" physical_register="henvcfg" size="1" bits="4"/>
  <register_field name="WPRI" physical_register="henvcfg" size="3" bits="1"/>
  <register_field name="FIEL" physical_register="henvcfg" size="1" bits="0"/>
</register>

<!-- HGEIP: Hypervisor Gei Pending -->
<register boot="0" index="0xe12" name="hgeip" size="64" type="SysReg">
  <register_field name="HGEIP" physical_register="hgeip" size="64"/>
</register>
```

**Step 2: 填充 vsie/vsip 字段**

将原来空的 vsie/vsip 填充：
```xml
<register boot="0" index="0x204" name="vsie" size="64" type="SysReg">
  <register_field name="VSSIE" physical_register="vsie" size="1" bits="2"/>
  <register_field name="VSTIE" physical_register="vsie" size="1" bits="6"/>
  <register_field name="VSEIE" physical_register="vsie" size="1" bits="10"/>
</register>

<register boot="0" index="0x244" name="vsip" size="64" type="SysReg">
  <register_field name="VSSIP" physical_register="vsip" size="1" bits="2"/>
  <register_field name="VTIP" physical_register="vsip" size="1" bits="6"/>
  <register_field name="VSEIP" physical_register="vsip" size="1" bits="10"/>
</register>
```

**Step 3: Commit**

```bash
git add riscv/arch_data/reg/system_registers_rv64.xml
git commit -m "feat: add missing H-extension CSR registers and fill vsie/vsip"
```

---

### Task 12: 扩展 Python 层 API

**Objective:** 在 Python 层添加 H-extension 相关的 API

**Files:**
- Modify: `py/riscv/GenThreadRISCV.py`
- Modify: `py/base/GenThread.py`

**Step 1: 添加两阶转译设置方法**

```python
class GenThreadRISCV(GenThread):
    def setupVsStagePaging(self, mode="Sv39"):
        """Setup VS-stage page tables (GVA -> GPA)"""
        self.virtualMemoryRequest("PhysicalRegion", {
            "RegionType": "VsStageRegion",
            "Size": 0x10000000,
            "Type": "IO",
            "Bank": 0,
        })
        self.setRegisterField("vsatp", "MODE", self._mode_to_value(mode))

    def setupGStagePaging(self, mode="Sv39x4"):
        """Setup G-stage page tables (GPA -> SPA)"""
        self.virtualMemoryRequest("PhysicalRegion", {
            "RegionType": "GStageRegion",
            "Size": 0x10000000,
            "Type": "IO",
            "Bank": 0,
        })
        self.setRegisterField("hgatp", "MODE", self._mode_to_value(mode))

    def _mode_to_value(self, mode):
        mode_map = {
            "Bare": 0, "Sv32": 1, "Sv39": 8, "Sv48": 9,
            "Sv39x4": 8, "Sv48x4": 9,
        }
        return mode_map.get(mode, 0)
```

**Step 2: Commit**

```bash
git add py/riscv/GenThreadRISCV.py py/base/GenThread.py
git commit -m "feat: add H-extension Python API for two-stage paging setup"
```

---

### Task 13: Phase 2 编译验证和测试

**Objective:** 验证 Phase 1+2 的编译和基本功能

**Step 1: 编译**

```bash
cd /home/guoshibo/force-riscv
make clean
make -j4
```

**Step 2: 运行单元测试**

```bash
./utils/regression/unit_tests.py
```

**Step 3: 运行冒烟测试**

```bash
friscv -c config/riscv_rv64_twostage.config examples/riscv/two_stage_translation_example.py
```

**Step 4: Commit**

```bash
git add .
git commit -m "build: phase 1+2 compile and basic test verification"
```

---

## Phase 3: 完整 Hypervisor 支持 (~10 天)

**目标：** 添加虚拟化中断、VMID 管理、HS/VS 特权切换、高级功能，实现完整的 Hypervisor 测试生成能力。

---

### Task 14: 实现虚拟化中断系统

**Objective:** 添加 VS-SWI(10)/VS-Timer(12)/VS-External(14) 中断支持

**Files:**
- Modify: `utils/enum_classes/base_enum_classes.py` — 添加中断类型
- Modify: `riscv/src/GenExceptionAgentRISCV.cc` — 处理虚拟中断
- Create: `riscv/src/VirtualInterruptManager.cc`
- Create: `riscv/inc/VirtualInterruptManager.h`

**Step 1: 添加虚拟中断枚举**

在 `base_enum_classes.py` 中：
```python
    [
        "InterruptType",
        "unsigned char",
        "Interrupt types.",
        [
            ("UserSoft", 0),
            ("SupervisorSoft", 1),
            ("MachineSoft", 3),
            ("UserTimer", 4),
            ("SupervisorTimer", 5),
            ("MachineTimer", 7),
            ("UserExternal", 8),
            ("SupervisorExternal", 9),
            ("MachineExternal", 11),
            ("VSExternal", 12),
            ("HypervisorSoft", 10),
            ("HypervisorTimer", 11),
        ],
    ],
```

**Step 2: 创建 VirtualInterruptManager**

```cpp
// riscv/inc/VirtualInterruptManager.h
#ifndef Force_VirtualInterruptManager_H
#define Force_VirtualInterruptManager_H

#include "Defines.h"
#include ARCH_ENUM_HEADER

namespace Force {
  class Generator;
  class Register;

  class VirtualInterruptManager {
  public:
    VirtualInterruptManager();
    void Setup(Generator* gen);
    
    // Generate virtual interrupt injection
    void InjectVSSoftwareInterrupt();
    void InjectVSTimerInterrupt();
    void InjectVSExternalInterrupt();
    
    // Control via hvip
    void SetHvipBit(uint32 bitIndex, bool value);
    
  private:
    Generator* mpGenerator;
    Register* mpHvipReg;
  };
}

#endif
```

**Step 3: Commit**

```bash
git add utils/enum_classes/base_enum_classes.py riscv/inc/VirtualInterruptManager.h riscv/src/VirtualInterruptManager.cc
git commit -m "feat: add virtual interrupt system (VS-SWI/Timer/External)"
```

---

### Task 15: 实现 VMID 管理

**Objective:** 创建 VMID 分配器，管理 hgatp.VMID 字段

**Files:**
- Create: `riscv/inc/VmidManager.h`
- Create: `riscv/src/VmidManager.cc`

**Step 1: 创建 VMID 管理器**

```cpp
// riscv/inc/VmidManager.h
#ifndef Force_VmidManager_H
#define Force_VmidManager_H

#include <set>
#include <vector>

namespace Force {
  class Generator;

  class VmidManager {
  public:
    VmidManager();
    
    // Allocate a new VMID
    uint16 AllocateVmid();
    
    // Release a VMID
    void ReleaseVmid(uint16 vmid);
    
    // Get current VMID count
    size_t ActiveVmidCount() const;
    
    // Maximum VMID (depends on hgatp.VMID field width)
    static constexpr uint16 MaxVmid() { return 1023; } // 10-bit VMID
    
  private:
    std::set<uint16> mAllocatedVmids;
    uint16 mNextVmid;
  };
}

#endif
```

**Step 2: Commit**

```bash
git add riscv/inc/VmidManager.h riscv/src/VmidManager.cc
git commit -m "feat: add VMID manager for hypervisor address spaces"
```

---

### Task 16: 扩展特权级切换支持 HS/VS

**Objective:** 修改 SwitchPrivilegeSolverRISCV 支持 M→HS→VS 切换链

**Files:**
- Modify: `riscv/src/SwitchPrivilegeSolverRISCV.cc`
- Modify: `riscv/inc/SwitchPrivilegeSolverRISCV.h`

**Step 1: 扩展支持的 privilege levels**

当前代码限制在 U/S/M (0-3)，需要扩展到 HS(2) 和 VS(3)：
```cpp
// 在 ValidateAndGenerateTargetState 中添加:
if (mResult.mTargetPrivLevel == EPrivilegeLevelTypeBaseType(EPrivilegeLevelType::H)) {
  // HS-mode: use MRET with MPP=S, then enter HS
  GenerateMretToHS();
}
if (mResult.mTargetPrivLevel == EPrivilegeLevelTypeBaseType(EPrivilegeLevelType::VS)) {
  // VS-mode: HS-level SRET with SPV=1
  GenerateSretToVS();
}
```

**Step 2: 添加 hstatus.SPV 处理**

```cpp
void SwitchPrivilegeSolver::GenerateSretToVS()
{
  // Set hstatus.SPV = 1 before SRET
  // This causes SRET to enter VS-mode instead of S-mode
  auto hstatus_reg = mpGenerator->GetRegisterFile()->RegisterLookup("hstatus");
  hstatus_reg->SetFieldValue("SPV", 1);
  
  // Also set hstatus.SP2P to target privilege level
  hstatus_reg->SetFieldValue("SP2P", mTargetState.mPrivLevel);
}
```

**Step 3: Commit**

```bash
git add riscv/src/SwitchPrivilegeSolverRISCV.cc riscv/inc/SwitchPrivilegeSolverRISCV.h
git commit -m "feat: extend privilege switch to support HS and VS modes"
```

---

### Task 17: 添加 htimedelta 和高级功能

**Objective:** 实现时间虚拟化和计数器虚拟化

**Files:**
- Modify: `riscv/arch_data/reg/system_registers_rv64.xml` — 添加 htimedelta
- Create: `riscv/src/TimeVirtualization.cc`

**Step 1: 添加 htimedelta 寄存器**

```xml
<register boot="0" index="0x605" name="htimedelta" size="64" type="SysReg">
  <register_field name="DELTAVAR" physical_register="htimedelta" size="64"/>
</register>
```

**Step 2: Commit**

```bash
git add riscv/arch_data/reg/system_registers_rv64.xml
git commit -m "feat: add htimedelta and time virtualization support"
```

---

### Task 18: Phase 3 集成测试和文档

**Objective:** 验证完整的 Hypervisor 支持，编写文档

**Files:**
- Create: `examples/riscv/hypervisor_full_example.py`
- Create: `docs/hypervisor-extension-implementation.md`

**Step 1: 创建完整示例**

```python
"""Full Hypervisor Extension Example"""
from base.Sequence import Sequence

class HypervisorSetup(Sequence):
    def generate(self, **kwargs):
        # Setup two-stage translation
        self.genThread.setupVsStagePaging(mode="Sv39")
        self.genThread.setupGStagePaging(mode="Sv39x4")
        
        # Setup VMID
        vmid = self.genThread.allocateVmid()
        self.genThread.setRegisterField("hgatp", "VMID", vmid)
        
        # Enter VS-mode
        self.genThread.switchPrivilege("VS")

class VirtualMachineTest(Sequence):
    def generate(self, **kwargs):
        # Run in VS-mode
        for _ in range(100):
            self.genInstruction("ADDI")
            self.genInstruction("LD")
            
        # Inject virtual interrupt
        self.genThread.injectVirtualInterrupt("VS-Software")
        
        # Flush TLB
        self.genInstruction("HFENCE.VVMA", rs1="x0", rs2="x0")
```

**Step 2: 运行完整回归测试**

```bash
./utils/regression/master_run.py -c config/riscv_rv64_twostage.config
```

**Step 3: Commit**

```bash
git add examples/riscv/hypervisor_full_example.py docs/
git commit -m "docs: add full hypervisor example and implementation documentation"
```

---

## 完整修改文件汇总

### Phase 1: 两阶地址转译 (~10 天)

| # | 类型 | 文件路径 |
|---|------|----------|
| 1 | Modify | `utils/enum_classes/riscv_enum_classes.py` |
| 2 | Auto-gen | `riscv/inc/EnumsRISCV.h`, `base/inc/Enums.h` |
| 3 | Create | `riscv/arch_data/paging/page_tables_sv48x4_gstage.xml` |
| 3 | Create | `riscv/arch_data/paging/page_tables_sv39x4_gstage.xml` |
| 4 | Modify | `base/inc/VmControlBlock.h`, `base/src/VmControlBlock.cc` |
| 4 | Modify | `base/inc/VmDirectMapControlBlock.h/.cc` |
| 4 | Modify | `riscv/inc/VmDirectMapControlBlockRISCV.h/.cc` |
| 5 | **Create** | `base/inc/TwoStageVmMapper.h` |
| 5 | **Create** | `base/src/TwoStageVmMapper.cc` |
| 5 | Modify | `base/inc/VmAddressSpace.h` |
| 6 | Modify | `base/inc/VmManager.h`, `base/src/VmManager.cc` |
| 7 | Modify | `riscv/src/VmFactoryRISCV.cc` |
| 7 | Modify | `riscv/inc/VmInfoRISCV.h`, `riscv/src/VmInfoRISCV.cc` |
| 8 | Create | `config/riscv_rv64_twostage.config` |
| 8 | Create | `examples/riscv/two_stage_translation_example.py` |

### Phase 2: 基础 Hypervisor (~10 天)

| # | 类型 | 文件路径 |
|---|------|----------|
| 9 | Modify | `riscv/arch_data/instr/priv_instructions.xml` |
| 10 | Modify | `utils/enum_classes/base_enum_classes.py` |
| 10 | Modify | `utils/enum_classes/riscv_enum_classes.py` |
| 10 | Modify | `riscv/src/GenExceptionAgentRISCV.cc/.h` |
| 11 | Modify | `riscv/arch_data/reg/system_registers_rv64.xml` |
| 12 | Modify | `py/riscv/GenThreadRISCV.py`, `py/base/GenThread.py` |

### Phase 3: 完整 Hypervisor (~10 天)

| # | 类型 | 文件路径 |
|---|------|----------|
| 14 | Modify | `utils/enum_classes/base_enum_classes.py` |
| 14 | **Create** | `riscv/inc/VirtualInterruptManager.h` |
| 14 | **Create** | `riscv/src/VirtualInterruptManager.cc` |
| 15 | **Create** | `riscv/inc/VmidManager.h` |
| 15 | **Create** | `riscv/src/VmidManager.cc` |
| 16 | Modify | `riscv/src/SwitchPrivilegeSolverRISCV.cc/.h` |
| 17 | Modify | `riscv/arch_data/reg/system_registers_rv64.xml` |
| 18 | Create | `examples/riscv/hypervisor_full_example.py` |
| 18 | Create | `docs/hypervisor-extension-implementation.md` |

---

## 风险和缓解策略

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 编译兼容性问题 | 可能阻塞 Phase 1 | 每个 task 后立即编译验证，不累积 |
| PTE XML 解析器不识别新属性 | stage 2 页表无法加载 | 在 Config.cc 中添加 stage 2 解析逻辑 |
| VmMapper 接口不兼容 | TwoStageVmMapper 无法编译 | 仔细对齐 VmMapper 的纯虚函数签名 |
| Guest Page Fault 与现有异常冲突 | 运行时崩溃 | 在独立分支测试，逐步集成 |
| 虚拟化中断时序问题 | 中断无法正确触发 | 使用手动的 hvip 写入方式，不依赖硬件模拟 |

---

## 验证策略

每个 Phase 完成后：
1. **编译验证**：`make clean && make -j4`
2. **单元测试**：`./utils/regression/unit_tests.py`
3. **冒烟测试**：运行对应的 example
4. **回归测试**：`./utils/regression/master_run.py`

Phase 3 完成后额外验证：
- 生成包含 HLV/HSV 指令的测试
- 生成包含 Guest Page Fault 的测试
- 生成 M→HS→VS 特权切换序列
- 生成虚拟化中断注入序列

---

**Plan complete. Ready to execute.**
