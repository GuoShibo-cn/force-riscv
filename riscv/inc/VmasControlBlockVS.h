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
#ifndef Force_VmasControlBlockVS_H
#define Force_VmasControlBlockVS_H

#include "VmasControlBlockRISCV.h"

namespace Force {

  class PhysicalRegion;

  /*!
    \class VmasControlBlockVS
    \brief VS-stage (Virtual Supervisor) address space control block.
    
    Manages the VS-stage page tables for Guest OS virtual address translation.
    Uses vsatp (instead of satp) and vsstatus (instead of sstatus) registers.
  */
  class VmasControlBlockVS : public VmasControlBlockRISCV
  {
  public:
    VmasControlBlockVS(EPrivilegeLevelType privType, EMemBankType memType, uint32 stage = 1);
    virtual ~VmasControlBlockVS() override { }
    ASSIGNMENT_OPERATOR_ABSENT(VmasControlBlockVS);

    Object*           Clone()    const override { return new VmasControlBlockVS(*this); }
    const char*       Type()     const override { return "VmasControlBlockVS"; }

    void Setup(Generator* pGen) override;
    void GetAddressErrorRanges(std::vector<TranslationRange>& rRanges) const override;
    bool InitializeRootPageTable(VmAddressSpace* pVmas, RootPageTable* pRootTable) override;

  protected:
    VmasControlBlockVS() : VmasControlBlockRISCV() { }
    VmasControlBlockVS(const VmasControlBlockVS& rOther) : VmasControlBlockRISCV(rOther) { }

    void FillRegisterReload(RegisterReload* pRegContext) const override;
    uint64 GetMaxPhysicalAddress() const override;

    const std::string StatusRegisterName() const override { return "vsstatus"; }
    const std::string AtpRegisterName() const override { return "vsatp"; }
  };
}

#endif //Force_VmasControlBlockVS_H
