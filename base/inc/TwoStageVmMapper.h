//
// Copyright (C) [2020] Futurewei Technologies, Inc.
//
// FORCE-RISCV is licensed under the Apache License, Version 2.0 (the "License");
//  you may not use this file except in compliance with the License.
//  You may obtain a copy of the License at
//
//  http://www.apache.org/licenses/LICENSE-2.0
//
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR
// FIT FOR A PARTICULAR PURPOSE.
// See the License for the specific language governing permissions and
// limitations under the License.
//
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

  /*!
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

    // VmMapper interface implementations -- delegate to appropriate stage mapper
    void AddPhysicalRegion(PhysicalRegion* pRegion, bool map) override;
    const ConstraintSet* VirtualUsableConstraintSet(bool isInstr) const override;
    ConstraintSet* VirtualUsableConstraintSetClone(bool isInstr) override;
    const ConstraintSet* VirtualSharedConstraintSet() const override;
    void ApplyVirtualUsableConstraint(EMemDataType memDataType, EMemAccessType memAccessType,
                                       const AddressReuseMode& rAddrReuseMode,
                                       ConstraintSet* constrSet) const override;

    // Missing pure virtual method implementations
    void DumpPage(EDumpFormat dumpFormat, std::ofstream& os) const override;
    void GetVmContextDelta(std::map<std::string, uint64>& rDeltaMap) const override;
    bool GetPageInfo(uint64 addr, const std::string& type, uint32 bank, PageInformation& rPageInfo) const override;
    bool GetTranslationRange(uint64 VA, TranslationRange& rTransRange) const override;
    bool MapAddressRange(uint64 VA, uint64 size, bool isInstr, const GenPageRequest* pPageReq) override;
    bool VaInAddressErrorRange(const uint64 VA) const override;
    bool ValidateContext(std::string& rErrMsg) const override;
    uint32 GenContextId() const override;
    uint64 MapAddressRangeForPA(uint64 PA, EMemBankType bank, uint64 size, bool isInstr, const GenPageRequest* pPageReq) override;
    uint64 MaxVirtualAddress() const override;
    uint64 MaxPhysicalAddress() const override;
    RegisterReload* GetRegisterReload() const override;
    const ConstraintSet* GetVmConstraint(EVmConstraintType constrType) const override;
    const Page* GetPage(uint64 VA) const override;
    ETranslationResultType TranslateVaToPa(uint64 VA, uint64& PA, uint32& bank) const override;
    ETranslationResultType TranslatePaToVa(uint64 PA, EMemBankType bank, uint64& VA) const override;
    EExceptionConstraintType GetExceptionConstraintType(const std::string& rExceptName) const override;
    EMemBankType DefaultMemoryBank() const override;
    bool VerifyStreamingPageCrossing(uint64 start, uint64 end) const override;
    void ApplyVmConstraints(const GenPageRequest* pPageReq, ConstraintSet& rConstr) const override;

    // Two-stage address translation utilities
    bool TranslateGvaToGpa(uint64 gva, uint64& rGpa, bool isInstr) const;
    bool TranslateGpaToSpa(uint64 gpa, uint64& rSpa, bool isInstr) const;
    bool TranslateGvaToSpa(uint64 gva, uint64& rSpa, bool isInstr) const;

    // Page request interfaces -- VS-stage handles GVA requests (non-virtual, delegating to VsStageMapper)
    GenPageRequest* GenPageRequestInstance(bool isInstr = true, EMemAccessType memAccessType = EMemAccessType::Unknown) const;
    GenPageRequest* GenPageRequestRegulated(bool isInstr = true, EMemAccessType memAccessType = EMemAccessType::Unknown, bool noFault = false) const;
    bool VerifyVirtualAddress(uint64 va, uint64 size, bool isInstr, const GenPageRequest* pPageReq) const;
    bool VerifyStreamingVa(uint64 va, uint64 size, bool isInstr) const;

    // Accessors
    VmMapper* VsStageMapper() const { return mpVsStageMapper; }
    VmMapper* GStageMapper() const { return mpGStageMapper; }
    const AddressTagging* GetAddressTagging() const override;

    // VmPaMapper access — G-stage maps GPA to SPA
    VmPaMapper* VmPaMapperInstance() const;

  private:
    VmMapper* mpVsStageMapper;  // VS-stage: GVA -> GPA (uses vsatp)
    VmMapper* mpGStageMapper;   // G-stage:  GPA -> SPA (uses hgatp)
    mutable VmPaMapper* mpGStagePaMapper; // For GPA->SPA mapping
  };

}

#endif
