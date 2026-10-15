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
#ifndef Force_VmasControlBlockHS_H
#define Force_VmasControlBlockHS_H

#include "VmasControlBlockRISCV.h"

namespace Force {

  class PhysicalRegion;

  /*!
    \class VmasControlBlockHS
    \brief HS-stage (Hypervisor Supervisor) address space control block.
    
    Manages the G-stage (Guest-stage) page tables for GPA→HPA translation.
    Uses hgatp (instead of satp) and hstatus (instead of sstatus) registers.
    G-stage leaf PTEs require U=1; guest physical addresses are unsigned.
  */
  class VmasControlBlockHS : public VmasControlBlockRISCV
  {
  public:
    VmasControlBlockHS(EPrivilegeLevelType privType, EMemBankType memType, uint32 stage = 2);
    virtual ~VmasControlBlockHS() override { }
    ASSIGNMENT_OPERATOR_ABSENT(VmasControlBlockHS);

    Object*           Clone()    const override { return new VmasControlBlockHS(*this); }
    const char*       Type()     const override { return "VmasControlBlockHS"; }

    void Setup(Generator* pGen) override;
    void GetAddressErrorRanges(std::vector<TranslationRange>& rRanges) const override;
    bool InitializeRootPageTable(VmAddressSpace* pVmas, RootPageTable* pRootTable) override;
    ConstraintSet* InitialVirtualConstraint() const override;
    uint32 HighestVaBitCurrent(uint32 rangeNum = 0ul) const override;

  protected:
    VmasControlBlockHS() : VmasControlBlockRISCV() { }
    VmasControlBlockHS(const VmasControlBlockHS& rOther) : VmasControlBlockRISCV(rOther) { }

    void FillRegisterReload(RegisterReload* pRegContext) const override;
    uint64 GetMaxPhysicalAddress() const override;
    EPageGranuleType GetGranuleType() const override;

    const std::string StatusRegisterName() const override { return "hstatus"; }
    const std::string AtpRegisterName() const override { return "hgatp"; }
  };
}

#endif //Force_VmasControlBlockHS_H
