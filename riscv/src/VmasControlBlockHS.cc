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
#include "VmasControlBlockHS.h"

#include <memory>
#include <sstream>

#include "Choices.h"
#include "Config.h"
#include "Constraint.h"
#include "GenRequest.h"
#include "Generator.h"
#include "Log.h"
#include "MemoryManager.h"
#include "Page.h"
#include "PageInfoRecord.h"
#include "PageTable.h"
#include "PagingChoicesAdapter.h"
#include "PagingInfo.h"
#include "PhysicalPageManager.h"
#include "PteAttribute.h"
#include "Random.h"
#include "Register.h"
#include "RegisterReload.h"
#include "SetupRootPageTableRISCV.h"
#include "UtilityFunctions.h"
#include "UtilityFunctionsRISCV.h"
#include "VmAddressSpace.h"
#include "VmUtils.h"
/*!\
  \file VmasControlBlockHS.cc
  \brief Code to configure HS-stage (Hypervisor Supervisor) address space control block.
  
  The HS-stage manages G-stage (Guest-stage) page tables for GPA→HPA translation.
  Key differences from S-mode:
  - Uses hgatp instead of satp
  - G-stage PTEs do not have U (User) bit
  - Uses Sv39x4/Sv48x4 paging modes
*/

using namespace std;

namespace Force {

  VmasControlBlockHS::VmasControlBlockHS(EPrivilegeLevelType privType, EMemBankType memType, uint32 stage)
    : VmasControlBlockRISCV(privType, memType, stage)
  {
    // HS-stage uses "h" prefix for register names (hgatp, hstatus)
    mRegisterPrefix = "h";
  }

  void VmasControlBlockHS::Setup(Generator* pGen)
  {
    LOG(notice) << "{VmasControlBlockHS::Setup} HS control block setup START" << endl;
    // Call base VmasControlBlock setup (sets up paging choices adapter / generator ptr)
    VmasControlBlock::Setup(pGen);

    VmContextParameter*      context_param = nullptr;
    EVmContextParamType      param_type;
    std::vector<std::string> status_param_names; // hstatus
    std::vector<std::string> atp_param_names;    // hgatp

    // HS-stage (hstatus) parameters
    // VSXL controls the guest XLEN
    status_param_names.push_back("VSXL");
    status_param_names.push_back("SPVP"); // Supervisor Previous Virtual Privilege
    status_param_names.push_back("SPV");  // Supervisor Previous Virtual

    atp_param_names.push_back("MODE");
    // VMID (Virtual Machine ID) for G-stage TLB management
    atp_param_names.push_back("VMID");

    for (auto& name : status_param_names)
    {
      param_type    = string_to_EVmContextParamType(name);
      context_param = new VmContextParameter(param_type, StatusRegisterName(), name);
      AddParameter(context_param);
    }

    for (auto& name : atp_param_names)
    {
      param_type    = string_to_EVmContextParamType(name);
      context_param = new VmContextParameter(param_type, AtpRegisterName(), name);
      AddParameter(context_param);
    }
  }

  void VmasControlBlockHS::FillRegisterReload(RegisterReload* pRegContext) const
  {
    VmasControlBlock::FillRegisterReload(pRegContext);

    auto reg_file = mpGenerator->GetRegisterFile();

    // Add register field updates for hgatp
    Register* hgatp_ptr = reg_file->RegisterLookup(AtpRegisterName());
    pRegContext->AddRegisterFieldUpdate(hgatp_ptr, "PPN", (mpRootPageTable->TableBase() >> 12));
  }

  uint64 VmasControlBlockHS::GetMaxPhysicalAddress() const
  {
    // HS-stage maps GPA to HPA (Host Physical Address)
    // Use the configured physical address limit
    return Config::Instance()->LimitValue(ELimitType::PhysicalAddressLimit);
  }

  EPageGranuleType VmasControlBlockHS::GetGranuleType() const
  {
    // G-stage supports 4K granule for Sv39x4/Sv48x4
    return EPageGranuleType::G4K;
  }

  uint32 VmasControlBlockHS::HighestVaBitCurrent(uint32 rangeNum) const
  {
    // x4 widens only the root index; lower-level tables retain the ordinary table step.
    return VmasControlBlockRISCV::HighestVaBitCurrent(rangeNum) + 2;
  }

  void VmasControlBlockHS::GetAddressErrorRanges(vector<TranslationRange>& rRanges) const
  {
    TranslationRange addr_err_range;
    uint64 error_start = 0x1ull << (mpRootPageTable->HighestLookUpBit() + 1);
    addr_err_range.SetBoundary(error_start, ~0ull);
    addr_err_range.SetMemoryBank(DefaultMemoryBank());

    rRanges.push_back(addr_err_range);
  }

  ConstraintSet* VmasControlBlockHS::InitialVirtualConstraint() const
  {
    return new ConstraintSet(0, (0x1ull << (mpRootPageTable->HighestLookUpBit() + 1)) - 1);
  }

  bool VmasControlBlockHS::InitializeRootPageTable(VmAddressSpace* pVmas, RootPageTable* pRootTable)
  {
    mpRootPageTable = RootPageTableInstance();
    if (nullptr == pRootTable)
    {
      SetupRootPageTable(mpRootPageTable, pVmas, mGranuleType, mPteIdentifierSuffix, AtpRegisterName());
    }
    else
    {
      mpRootPageTable  = pRootTable;
      uint64 root_addr = mpRootPageTable->TableBase();
      uint32 tb_size   = mpRootPageTable->RootTableSize();

      pVmas->AddPhysicalRegion(new PhysicalRegion(root_addr, root_addr + (tb_size - 1), EPhysicalRegionType::PageTable, pRootTable->MemoryBank(), EMemDataType::Data));
      pVmas->UpdatePageTableConstraint(root_addr, root_addr + (tb_size - 1));
      mpRootPageTable->SignUp(pVmas);
    }

    return true;
  }
}
