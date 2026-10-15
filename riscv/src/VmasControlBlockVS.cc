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
#include "VmasControlBlockVS.h"

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
  \file VmasControlBlockVS.cc
  \brief Code to configure VS-stage (Virtual Supervisor) address space control block.
*/

using namespace std;

namespace Force {

  VmasControlBlockVS::VmasControlBlockVS(EPrivilegeLevelType privType, EMemBankType memType, uint32 stage)
    : VmasControlBlockRISCV(privType, memType, stage)
  {
    // VS-stage uses "vs" prefix for register names (vsatp, vsstatus)
    mRegisterPrefix = "vs";
  }

  void VmasControlBlockVS::Setup(Generator* pGen)
  {
    // Call base VmasControlBlock setup (sets up paging choices adapter / generator ptr)
    VmasControlBlock::Setup(pGen);

    VmContextParameter*      context_param = nullptr;
    EVmContextParamType      param_type;
    std::vector<std::string> status_param_names; // vsstatus
    std::vector<std::string> atp_param_names;    // vsatp

    // VS-stage status register parameters
    status_param_names.push_back("MXR"); // Make Executable Readable
    status_param_names.push_back("SUM"); // Supervisor User Memory

    atp_param_names.push_back("MODE");

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

  void VmasControlBlockVS::FillRegisterReload(RegisterReload* pRegContext) const
  {
    VmasControlBlock::FillRegisterReload(pRegContext);

    auto reg_file = mpGenerator->GetRegisterFile();

    // Add register field updates for vsatp
    Register* vsatp_ptr = reg_file->RegisterLookup(AtpRegisterName());
    pRegContext->AddRegisterFieldUpdate(vsatp_ptr, "PPN", (mpRootPageTable->TableBase() >> 12));
  }

  uint64 VmasControlBlockVS::GetMaxPhysicalAddress() const
  {
    // VS-stage physical addresses are GPA (Guest Physical Addresses)
    // For now, use the same limit as the base class
    return Config::Instance()->LimitValue(ELimitType::PhysicalAddressLimit);
  }

  void VmasControlBlockVS::GetAddressErrorRanges(vector<TranslationRange>& rRanges) const
  {
    // VS-stage uses Guest Virtual Address (GVA) space
    // Similar canonical address checking as S-mode Sv39/Sv48
    const PagingInfo* paging_info = mpGenerator->GetPagingInfo();
    if (paging_info->GetPagingMode() == EPagingMode::Sv32) {
      return;
    }

    TranslationRange addr_err_range;
    uint64 va_bits = mpRootPageTable->HighestLookUpBit();

    uint64 error_start = 0x1ull << va_bits;
    uint64 error_end = sign_extend64((0x1ull << va_bits), va_bits + 1) - 1;

    addr_err_range.SetBoundary(error_start, error_end);
    addr_err_range.SetMemoryBank(DefaultMemoryBank());

    rRanges.push_back(addr_err_range);
  }

  bool VmasControlBlockVS::InitializeRootPageTable(VmAddressSpace* pVmas, RootPageTable* pRootTable)
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
