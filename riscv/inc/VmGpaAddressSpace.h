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
#ifndef Force_VmGpaAddressSpace_H
#define Force_VmGpaAddressSpace_H

#include "VmAddressSpaceRISCV.h"

namespace Force {

  /*!
    \class VmGpaAddressSpace
    \brief G-stage (Guest-stage) address space for GPA→HPA translation.
    
    This specialized address space handles the second stage of RISC-V
    two-stage address translation. Key characteristics:
    
    - Uses GPA (Guest Physical Address) as the "virtual" input
    - Maps to HPA (Host Physical Address) as the "physical" output
    - Controlled by hgatp register (not satp or vsatp)
    - Uses Sv39x4/Sv48x4 paging modes (no U bit in PTEs)
    - No instruction/data distinction for G-stage translations
  */
  class VmGpaAddressSpace : public VmAddressSpaceRISCV
  {
  public:
    VmGpaAddressSpace(const VmFactory* pFactory, VmasControlBlock* pVmasCtlrBlock);
    virtual ~VmGpaAddressSpace() override;
    ASSIGNMENT_OPERATOR_ABSENT(VmGpaAddressSpace);

    Object* Clone() const override { return new VmGpaAddressSpace(*this); }
    const char* Type() const override { return "VmGpaAddressSpace"; }

    // G-stage uses GPA as "virtual" address, HPA as "physical" address
    ETranslationResultType TranslateVaToPa(uint64 GPA, uint64& HPA, uint32& bank) const override;

    // G-stage page table initialization with Sv39x4/Sv48x4 format
    void InitializeGStagePageTables();

    // G-stage has no instruction/data distinction
    const ConstraintSet* VirtualUsableConstraintSet(bool isInstr) const override;

  protected:
    VmGpaAddressSpace();
    VmGpaAddressSpace(const VmGpaAddressSpace& rOther);

    void SetupGStageConstraints();
  };
}

#endif //Force_VmGpaAddressSpace_H
