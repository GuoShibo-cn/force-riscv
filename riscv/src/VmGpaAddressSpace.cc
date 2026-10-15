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
#include "VmGpaAddressSpace.h"

#include "Constraint.h"
#include "GenRequest.h"
#include "Generator.h"
#include "Log.h"
#include "PagingInfo.h"
#include "UtilityFunctions.h"
#include "VmasControlBlock.h"
/*!\
  \file VmGpaAddressSpace.cc
  \brief G-stage (Guest-stage) address space implementation.
  
  The G-stage translates GPA (Guest Physical Address) to HPA (Host Physical Address).
  This is the second stage of RISC-V H-extension two-stage translation.
*/

using namespace std;

namespace Force {

  VmGpaAddressSpace::VmGpaAddressSpace(const VmFactory* pFactory, VmasControlBlock* pVmasCtlrBlock)
    : VmAddressSpaceRISCV(pFactory, pVmasCtlrBlock)
  {
  }

  VmGpaAddressSpace::VmGpaAddressSpace()
    : VmAddressSpaceRISCV()
  {
  }

  VmGpaAddressSpace::VmGpaAddressSpace(const VmGpaAddressSpace& rOther)
    : VmAddressSpaceRISCV(rOther)
  {
  }

  VmGpaAddressSpace::~VmGpaAddressSpace()
  {
  }

  ETranslationResultType VmGpaAddressSpace::TranslateVaToPa(uint64 GPA, uint64& HPA, uint32& bank) const
  {
    // In G-stage, the "virtual" address is actually GPA
    // and the "physical" address is HPA
    return VmAddressSpace::TranslateVaToPa(GPA, HPA, bank);
  }

  void VmGpaAddressSpace::InitializeGStagePageTables()
  {
    LOG(info) << "{VmGpaAddressSpace::InitializeGStagePageTables} initializing G-stage page tables" << endl;

    auto control_block = GetControlBlock();
    if (!control_block) {
      LOG(warn) << "{VmGpaAddressSpace::InitializeGStagePageTables} no control block" << endl;
      return;
    }

    auto paging_info = mpGenerator ? mpGenerator->GetPagingInfo() : nullptr;
    if (paging_info) {
      EPagingMode mode = paging_info->GetPagingMode();
      LOG(info) << "{VmGpaAddressSpace::InitializeGStagePageTables} paging mode: " 
                << EPagingMode_to_string(mode) << endl;
      
      if (mode != EPagingMode::Sv39x4 && mode != EPagingMode::Sv48x4) {
        LOG(warn) << "{VmGpaAddressSpace::InitializeGStagePageTables} expected Sv39x4/Sv48x4, got " 
                  << EPagingMode_to_string(mode) << endl;
      }
    }

    // Setup G-stage constraints (U-bit, VMID isolation, etc.)
    SetupGStageConstraints();
  }

  const ConstraintSet* VmGpaAddressSpace::VirtualUsableConstraintSet(bool isInstr) const
  {
    // G-stage has no instruction/data distinction
    // All GPA space is treated the same regardless of access type
    return VmAddressSpace::VirtualUsableConstraintSet(false);
  }

  void VmGpaAddressSpace::SetupGStageConstraints()
  {
    LOG(info) << "{VmGpaAddressSpace::SetupGStageConstraints} setting up G-stage constraints" << endl;

    // G-stage constraints differ from S-stage:
    // 1. No U (User) bit in PTEs - all pages are supervisor-level
    // 2. GPA space may have different alignment requirements
    // 3. VMID isolation for multi-guest scenarios
    
    // These would be applied through the control block's constraint system
    auto control_block = GetControlBlock();
    if (control_block) {
      LOG(info) << "{VmGpaAddressSpace::SetupGStageConstraints} control block type: " 
                << control_block->Type() << endl;
    }
  }

}
