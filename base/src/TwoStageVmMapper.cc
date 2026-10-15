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
#include "TwoStageVmMapper.h"

#include "AddressTagging.h"
#include "Constraint.h"
#include "GenRequest.h"
#include "Generator.h"
#include "Log.h"
#include "VmFactory.h"
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

  const ConstraintSet* TwoStageVmMapper::VirtualUsableConstraintSet(bool isInstr) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->VirtualUsableConstraintSet(isInstr);
    return nullptr;
  }

  ConstraintSet* TwoStageVmMapper::VirtualUsableConstraintSetClone(bool isInstr)
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

  // --- Missing pure virtual method implementations ---

  void TwoStageVmMapper::DumpPage(EDumpFormat dumpFormat, std::ofstream& os) const
  {
    if (mpVsStageMapper) mpVsStageMapper->DumpPage(dumpFormat, os);
  }

  void TwoStageVmMapper::GetVmContextDelta(std::map<std::string, uint64>& rDeltaMap) const
  {
    if (mpVsStageMapper) mpVsStageMapper->GetVmContextDelta(rDeltaMap);
  }

  bool TwoStageVmMapper::GetPageInfo(uint64 addr, const std::string& type, uint32 bank, PageInformation& rPageInfo) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->GetPageInfo(addr, type, bank, rPageInfo);
    return false;
  }

  bool TwoStageVmMapper::GetTranslationRange(uint64 VA, TranslationRange& rTransRange) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->GetTranslationRange(VA, rTransRange);
    return false;
  }

  bool TwoStageVmMapper::MapAddressRange(uint64 VA, uint64 size, bool isInstr, const GenPageRequest* pPageReq)
  {
    if (mpVsStageMapper) return mpVsStageMapper->MapAddressRange(VA, size, isInstr, pPageReq);
    return false;
  }

  bool TwoStageVmMapper::VaInAddressErrorRange(const uint64 VA) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->VaInAddressErrorRange(VA);
    return false;
  }

  bool TwoStageVmMapper::ValidateContext(std::string& rErrMsg) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->ValidateContext(rErrMsg);
    return false;
  }

  uint32 TwoStageVmMapper::GenContextId() const
  {
    if (mpVsStageMapper) return mpVsStageMapper->GenContextId();
    return 0;
  }

  uint64 TwoStageVmMapper::MapAddressRangeForPA(uint64 PA, EMemBankType bank, uint64 size, bool isInstr, const GenPageRequest* pPageReq)
  {
    if (mpVsStageMapper) return mpVsStageMapper->MapAddressRangeForPA(PA, bank, size, isInstr, pPageReq);
    return 0;
  }

  uint64 TwoStageVmMapper::MaxVirtualAddress() const
  {
    if (mpVsStageMapper) return mpVsStageMapper->MaxVirtualAddress();
    return 0;
  }

  uint64 TwoStageVmMapper::MaxPhysicalAddress() const
  {
    if (mpVsStageMapper) return mpVsStageMapper->MaxPhysicalAddress();
    return 0;
  }

  RegisterReload* TwoStageVmMapper::GetRegisterReload() const
  {
    if (mpVsStageMapper) return mpVsStageMapper->GetRegisterReload();
    return nullptr;
  }

  const ConstraintSet* TwoStageVmMapper::GetVmConstraint(EVmConstraintType constrType) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->GetVmConstraint(constrType);
    return nullptr;
  }

  const Page* TwoStageVmMapper::GetPage(uint64 VA) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->GetPage(VA);
    return nullptr;
  }

  ETranslationResultType TwoStageVmMapper::TranslateVaToPa(uint64 VA, uint64& PA, uint32& bank) const
  {
    // Two-stage translation: GVA --[VS-stage]--> GPA --[G-stage]--> HPA
    if (!mpVsStageMapper || !mpGStageMapper)
      return ETranslationResultType::NotMapped;

    // Stage 1: VS-stage translates GVA to GPA
    uint64 gpa = 0;
    ETranslationResultType vs_result = mpVsStageMapper->TranslateVaToPa(VA, gpa, bank);
    if (vs_result != ETranslationResultType::Mapped) {
      return vs_result;  // VS-stage fault (page fault, access fault, etc.)
    }

    // Stage 2: G-stage translates GPA to HPA (final physical address)
    ETranslationResultType gs_result = mpGStageMapper->TranslateVaToPa(gpa, PA, bank);
    if (gs_result != ETranslationResultType::Mapped) {
      return gs_result;  // G-stage fault (guest page fault, etc.)
    }

    return ETranslationResultType::Mapped;
  }

  ETranslationResultType TwoStageVmMapper::TranslatePaToVa(uint64 PA, EMemBankType bank, uint64& VA) const
  {
    // Two-stage reverse: HPA --[G-stage]--> GPA --[VS-stage]--> GVA
    if (!mpVsStageMapper || !mpGStageMapper)
      return ETranslationResultType::NotMapped;

    // Stage 1 reverse: G-stage translates HPA to GPA
    uint64 gpa = 0;
    ETranslationResultType gs_result = mpGStageMapper->TranslatePaToVa(PA, bank, gpa);
    if (gs_result != ETranslationResultType::Mapped) {
      return gs_result;  // HPA not mapped in G-stage
    }

    // Stage 2 reverse: VS-stage translates GPA to GVA
    ETranslationResultType vs_result = mpVsStageMapper->TranslatePaToVa(gpa, bank, VA);
    if (vs_result != ETranslationResultType::Mapped) {
      return vs_result;  // GPA not mapped in VS-stage
    }

    return ETranslationResultType::Mapped;
  }

  EExceptionConstraintType TwoStageVmMapper::GetExceptionConstraintType(const std::string& rExceptName) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->GetExceptionConstraintType(rExceptName);
    return EExceptionConstraintType::Invalid;
  }

  EMemBankType TwoStageVmMapper::DefaultMemoryBank() const
  {
    if (mpVsStageMapper) return mpVsStageMapper->DefaultMemoryBank();
    return EMemBankType::Default;
  }

  bool TwoStageVmMapper::VerifyStreamingPageCrossing(uint64 start, uint64 end) const
  {
    if (mpVsStageMapper) return mpVsStageMapper->VerifyStreamingPageCrossing(start, end);
    return true;
  }

  void TwoStageVmMapper::ApplyVmConstraints(const GenPageRequest* pPageReq, ConstraintSet& rConstr) const
  {
    if (mpVsStageMapper) mpVsStageMapper->ApplyVmConstraints(pPageReq, rConstr);
  }

  // --- End pure virtual method implementations ---

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
    if (mpGStagePaMapper == nullptr) {
      auto gstage_as = dynamic_cast<VmAddressSpace*>(mpGStageMapper);
      if (gstage_as != nullptr) {
        const VmFactory* factory = gstage_as->GetVmFactory();
        if (factory != nullptr) {
          mpGStagePaMapper = factory->VmPaMapperInstance(gstage_as);
        }
      }
    }
    return mpGStagePaMapper;
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
