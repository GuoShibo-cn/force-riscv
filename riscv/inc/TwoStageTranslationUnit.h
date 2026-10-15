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
#ifndef Force_TwoStageTranslationUnit_H
#define Force_TwoStageTranslationUnit_H

#include <cstdint>
#include <string>

#include "Defines.h"

namespace Force {

  class VmAddressSpaceRISCV;
  class VmGpaAddressSpace;
  class Generator;
  class GenPageRequest;

  /*!
    \class TwoStageTranslationUnit
    \brief Coordinates two-stage address translation (GVA→GPA→HPA).
    
    This class manages the complete two-stage translation chain for
    RISC-V H-extension virtualization:
    
    - Stage 1 (VS-stage): GVA → GPA via vsatp
    - Stage 2 (G-stage):  GPA → HPA via hgatp
    
    It provides methods to:
    - Set up complete translation chains
    - Generate guest page fault scenarios
    - Validate translation consistency
    - Generate CSR configuration sequences
  */
  class TwoStageTranslationUnit
  {
  public:
    TwoStageTranslationUnit(VmAddressSpaceRISCV* pVsAs, VmGpaAddressSpace* pHsAs);
    ~TwoStageTranslationUnit();
    ASSIGNMENT_OPERATOR_ABSENT(TwoStageTranslationUnit);
    COPY_CONSTRUCTOR_ABSENT(TwoStageTranslationUnit);

    // Create contiguous VS/G leaf mappings in prepared address spaces, then enable composition.
    // Existing mappings must agree. New leaves are VS supervisor and G user-accessible.
    // VS table backing is identity-mapped through G-stage; conflicting mappings are rejected.
    // This does not configure CSRs or declare RAM to an ISS.
    // Allocation failure leaves composition disabled and may retain already committed pages.
    void SetupFullTranslation(uint64 GVA, uint64 GPA, uint64 HPA, uint64 size, bool isInstr);

    // Generate G-stage exception scenarios (guest page fault)
    void SetupGuestPageFaultScenario(uint64 GVA, uint64 GPA);

    // Validate two-stage translation consistency
    bool ValidateTranslationChain(uint64 GVA, uint64& HPA) const;

    // Generate two-stage translation related CSR configuration sequence
    void GenerateSetupInstructions(Generator* pGen);

    // Enable/disable two-stage translation
    void EnableTwoStage(bool enabled);
    bool IsEnabled() const { return mEnabled; }

  private:
    VmAddressSpaceRISCV* mpVsAddressSpace;  // Stage-1 (VS-stage)
    VmGpaAddressSpace*   mpHsAddressSpace;  // Stage-2 (G-stage)
    bool mEnabled;
  };
}

#endif //Force_TwoStageTranslationUnit_H
