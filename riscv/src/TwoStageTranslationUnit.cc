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
#include "TwoStageTranslationUnit.h"

#include <algorithm>
#include <limits>
#include <memory>

#include "Constraint.h"
#include "GenRequest.h"
#include "Generator.h"
#include "Log.h"
#include "Page.h"
#include "UtilityFunctions.h"
#include "VmAddressSpaceRISCV.h"
#include "VmGpaAddressSpace.h"
/*!\
  \file TwoStageTranslationUnit.cc
  \brief Two-stage translation coordination unit implementation.
*/

using namespace std;

namespace Force {

  TwoStageTranslationUnit::TwoStageTranslationUnit(VmAddressSpaceRISCV* pVsAs, VmGpaAddressSpace* pHsAs)
    : mpVsAddressSpace(pVsAs), mpHsAddressSpace(pHsAs), mEnabled(false)
  {
    if (mpVsAddressSpace && mpHsAddressSpace) {
      // Connect the two stages
      mpVsAddressSpace->SetGpaAddressSpace(mpHsAddressSpace);
      LOG(info) << "{TwoStageTranslationUnit::TwoStageTranslationUnit} two-stage translation unit created" << endl;
    }
  }

  TwoStageTranslationUnit::~TwoStageTranslationUnit()
  {
    // Note: We don't own the address spaces, they're managed by VmManager
    if (mpVsAddressSpace) {
      mpVsAddressSpace->SetGpaAddressSpace(nullptr);
    }
  }

  void TwoStageTranslationUnit::SetupFullTranslation(uint64 GVA, uint64 GPA, uint64 HPA, uint64 size, bool isInstr)
  {
    if (!mpVsAddressSpace || !mpHsAddressSpace) {
      LOG(fail) << "{TwoStageTranslationUnit::SetupFullTranslation} address spaces not initialized" << endl;
      FAIL("two-stage-address-spaces-null");
    }

    if (mpVsAddressSpace == mpHsAddressSpace || mpHsAddressSpace->IsTwoStageEnabled() ||
        !mpVsAddressSpace->GetGenerator() ||
        mpVsAddressSpace->GetGenerator() != mpHsAddressSpace->GetGenerator()) {
      LOG(fail) << "{TwoStageTranslationUnit::SetupFullTranslation} invalid stage configuration" << endl;
      FAIL("two-stage-invalid-configuration");
    }

    const uint64 max_address = numeric_limits<uint64>::max();
    if (size == 0 || size - 1 > max_address - GVA || size - 1 > max_address - GPA ||
        size - 1 > max_address - HPA) {
      LOG(fail) << "{TwoStageTranslationUnit::SetupFullTranslation} empty or wrapping range" << endl;
      FAIL("two-stage-invalid-range");
    }
    // Both stages preserve at least the low 12 address bits, including unaligned accesses.
    const uint64 page_mask = 0xfff;
    if (((GVA ^ GPA) & page_mask) || ((GPA ^ HPA) & page_mask)) {
      LOG(fail) << "{TwoStageTranslationUnit::SetupFullTranslation} incompatible page offsets" << endl;
      FAIL("two-stage-offset-mismatch");
    }
    if (GPA + size - 1 > mpVsAddressSpace->MaxPhysicalAddress() ||
        GPA + size - 1 > mpHsAddressSpace->MaxVirtualAddress() ||
        HPA + size - 1 > mpHsAddressSpace->MaxPhysicalAddress()) {
      LOG(fail) << "{TwoStageTranslationUnit::SetupFullTranslation} address exceeds stage limits" << endl;
      FAIL("two-stage-address-out-of-range");
    }

    struct StageMapping {
      VmAddressSpaceRISCV* addressSpace;
      uint64 input;
      uint64 output;
      bool guestPhysical;
    };
    const StageMapping stages[] = {
      {mpHsAddressSpace, GPA, HPA, true}, {mpVsAddressSpace, GVA, GPA, false}
    };

    // Check both stages before allocating: MapAddressRange silently reuses existing pages.
    // Read individual Page objects, not the enabled VS mapper's composed translation/cache.
    for (const auto& stage : stages) {
      for (uint64 offset = 0; offset < size; ) {
        uint64 address = stage.input + offset;
        uint64 chunk = min(size - offset, 0x1000 - (address & page_mask));
        if (stage.addressSpace->VaInAddressErrorRange(address) ||
            stage.addressSpace->VaInAddressErrorRange(address + chunk - 1)) {
          LOG(fail) << "{TwoStageTranslationUnit::SetupFullTranslation} address error range" << endl;
          FAIL("two-stage-address-out-of-range");
        }
        const Page* page = stage.addressSpace->GetPage(address);
        if (page != nullptr) {
          uint64 translated = 0;
          uint32 bank = 0;
          if (page->TranslationResultType() != ETranslationResultType::Mapped ||
              page->TranslateVaToPa(address, translated, bank) != ETranslationResultType::Mapped ||
              translated != stage.output + offset || page->Upper() < address + chunk - 1 ||
              bank != uint32(stage.addressSpace->DefaultMemoryBank())) {
            LOG(fail) << "{TwoStageTranslationUnit::SetupFullTranslation} conflicting existing mapping" << endl;
            FAIL("two-stage-mapping-conflict");
          }
        }
        offset += chunk;
      }
    }

    // Avoid the legacy automatic G-stage mapping of GVA, and never enable a partial chain.
    // Allocation failures retain committed pages for diagnosis; there is no mapper rollback API.
    EnableTwoStage(false);
    mpVsAddressSpace->InvalidateTranslationCache();
    for (const auto& stage : stages) {
      unique_ptr<GenPageRequest> request(stage.addressSpace->GenPageRequestInstance(
        isInstr, isInstr ? EMemAccessType::Unknown : EMemAccessType::ReadWrite));
      request->SetGenBoolAttribute(EPageGenBoolAttrType::FlatMap, false);
      request->SetGenBoolAttribute(EPageGenBoolAttrType::Privileged, !stage.guestPhysical);
      request->SetGenBoolAttribute(EPageGenBoolAttrType::NoInstrPageFault, true);
      request->SetGenBoolAttribute(EPageGenBoolAttrType::NoDataPageFault, true);
      request->SetGenAttributeValue(EPageGenAttributeType::Invalid, 0);
      request->SetPteAttribute(EPteAttributeType::V, 1);
      request->SetPteAttribute(EPteAttributeType::G, 0);
      request->SetPteAttribute(EPteAttributeType::U, stage.guestPhysical ? 1 : 0);
      request->SetPteAttribute(EPteAttributeType::WR, isInstr ? 1 : 3);
      request->SetPteAttribute(EPteAttributeType::X, isInstr ? 1 : 0);
      request->SetPteAttribute(EPteAttributeType::DA, 3);
      for (uint64 offset = 0; offset < size; ) {
        uint64 address = stage.input + offset;
        uint64 chunk = min(size - offset, 0x1000 - (address & page_mask));
        request->SetAttributeValue(EPageRequestAttributeType::PA, stage.output + offset);
        // A fresh PA per granule prevents a multi-page range from aliasing its first PA.
        stage.addressSpace->MapAddressRange(address, chunk, isInstr, request.get());
        const Page* page = stage.addressSpace->GetPage(address);
        uint64 translated = 0;
        uint32 bank = 0;
        if (page == nullptr ||
            page->TranslationResultType() != ETranslationResultType::Mapped ||
            page->TranslateVaToPa(address, translated, bank) != ETranslationResultType::Mapped ||
            translated != stage.output + offset || page->Upper() < address + chunk - 1 ||
            bank != uint32(stage.addressSpace->DefaultMemoryBank())) {
          LOG(fail) << "{TwoStageTranslationUnit::SetupFullTranslation} mapping did not satisfy request" << endl;
          FAIL("two-stage-mapping-failed");
        }
        offset += chunk;
      }
    }

    // The internal allocator currently gives VS tables host physical addresses. Keep those
    // numbers as their GPAs and explicitly identity-map the backing, without relocating PTEs.
    unique_ptr<GenPageRequest> table_request(mpHsAddressSpace->GenPageRequestInstance(
      false, EMemAccessType::ReadWrite));
    table_request->SetGenBoolAttribute(EPageGenBoolAttrType::FlatMap, true);
    table_request->SetGenAttributeValue(EPageGenAttributeType::Invalid, 0);
    table_request->SetPteAttribute(EPteAttributeType::SystemPage, 1);
    table_request->SetPteAttribute(EPteAttributeType::V, 1);
    table_request->SetPteAttribute(EPteAttributeType::U, 1);
    table_request->SetPteAttribute(EPteAttributeType::G, 0);
    table_request->SetPteAttribute(EPteAttributeType::WR, 3);
    table_request->SetPteAttribute(EPteAttributeType::X, 0);
    table_request->SetPteAttribute(EPteAttributeType::DA, 3);
    for (const auto range : mpVsAddressSpace->GetVmConstraint(EVmConstraintType::PageTable)->GetConstraints()) {
      for (uint64 address = range->LowerBound(); ; address += 0x1000) {
        if (mpHsAddressSpace->VaInAddressErrorRange(address) ||
            address > mpHsAddressSpace->MaxPhysicalAddress()) {
          LOG(fail) << "{TwoStageTranslationUnit::SetupFullTranslation} VS table outside G-stage range" << endl;
          FAIL("two-stage-page-table-backing-failed");
        }
        mpHsAddressSpace->MapAddressRange(address, 0x1000, false, table_request.get());
        const Page* page = mpHsAddressSpace->GetPage(address);
        uint64 translated = 0;
        uint32 bank = 0;
        if (!page || page->TranslationResultType() != ETranslationResultType::Mapped ||
            page->TranslateVaToPa(address, translated, bank) != ETranslationResultType::Mapped ||
            translated != address || page->Upper() - address < 0xfff ||
            bank != uint32(mpVsAddressSpace->DefaultMemoryBank()) ||
            (page->Descriptor() & 0xd7) != 0xd7) {
          LOG(fail) << "{TwoStageTranslationUnit::SetupFullTranslation} incompatible VS table backing" << endl;
          FAIL("two-stage-page-table-backing-failed");
        }
        if (range->UpperBound() - address < 0x1000) break;
      }
    }

    EnableTwoStage(true);
    LOG(info) << "{TwoStageTranslationUnit::SetupFullTranslation} translation chain established" << endl;
  }

  void TwoStageTranslationUnit::SetupGuestPageFaultScenario(uint64 GVA, uint64 GPA)
  {
    LOG(info) << "{TwoStageTranslationUnit::SetupGuestPageFaultScenario} GVA 0x" << hex << GVA 
              << " → GPA 0x" << GPA << " (no HPA mapping)" << dec << endl;

    // For guest page fault scenarios:
    // - VS-stage maps GVA → GPA (valid)
    // - G-stage does NOT map GPA → HPA (causes guest page fault)
    
    // This is useful for testing exception handling
    EnableTwoStage(true);
  }

  bool TwoStageTranslationUnit::ValidateTranslationChain(uint64 GVA, uint64& HPA) const
  {
    if (!mEnabled || !mpVsAddressSpace || !mpHsAddressSpace || !mpVsAddressSpace->IsTwoStageEnabled()) {
      return false;
    }

    // Validate the complete GVA→GPA→HPA chain
    uint32 bank = 0;
    ETranslationResultType result = mpVsAddressSpace->TranslateGvaToHpa(GVA, HPA, bank);
    
    if (result != ETranslationResultType::Mapped) {
      LOG(warn) << "{TwoStageTranslationUnit::ValidateTranslationChain} validation failed for GVA 0x" 
                << hex << GVA << " result: " << ETranslationResultType_to_string(result) << dec << endl;
      return false;
    }

    LOG(info) << "{TwoStageTranslationUnit::ValidateTranslationChain} GVA 0x" << hex << GVA 
              << " → HPA 0x" << HPA << dec << endl;
    
    return true;
  }

  void TwoStageTranslationUnit::GenerateSetupInstructions(Generator* pGen)
  {
    if (!pGen) {
      LOG(fail) << "{TwoStageTranslationUnit::GenerateSetupInstructions} null generator" << endl;
      FAIL("null-generator");
    }

    LOG(info) << "{TwoStageTranslationUnit::GenerateSetupInstructions} generating CSR setup sequence" << endl;

    // This would generate the instruction sequence to:
    // 1. Configure hstatus (VSXL, SPV, etc.)
    // 2. Set up hgatp with G-stage page table base
    // 3. Set up vsatp with VS-stage page table base
    // 4. Configure hideleg/hedeleg for interrupt delegation
    // 5. Enable two-stage translation via appropriate CSRs
    
    // Implementation would use the generator's instruction emission capabilities
  }

  void TwoStageTranslationUnit::EnableTwoStage(bool enabled)
  {
    mEnabled = enabled;
    if (mpVsAddressSpace) {
      mpVsAddressSpace->SetTwoStageEnabled(enabled);
    }
    
    LOG(info) << "{TwoStageTranslationUnit::EnableTwoStage} two-stage translation " 
              << (enabled ? "enabled" : "disabled") << endl;
  }

}
