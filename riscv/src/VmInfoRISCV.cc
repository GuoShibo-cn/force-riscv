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
#include "VmInfoRISCV.h"

#include <sstream>

#include "Generator.h"
#include "Log.h"
#include "Register.h"

using namespace std;

/*!
  \file VmInfoRISCV.cc
  \brief RISC-V specific VM lookup info code.
*/

namespace Force {

  EVmRegimeType VmInfoRISCV::RegimeType(bool* pIsValid) const
  {
    if (nullptr != pIsValid) {
      *pIsValid = true;
    }

    if (mPrivilegeLevelType == EPrivilegeLevelType::M)
    {
      return EVmRegimeType::M;
    }
    else if (mPrivilegeLevelType == EPrivilegeLevelType::H)
    {
      return EVmRegimeType::HS;
    }
    else if (mPrivilegeLevelType == EPrivilegeLevelType::S)
    {
      return EVmRegimeType::S;
    }
    // U-mode: if virtualized (v=1), it's VS regime; otherwise S regime
    else if (mPrivilegeLevelType == EPrivilegeLevelType::U)
    {
      return EVmRegimeType::S;
    }

    return EVmRegimeType::M;
  }

  const string VmInfoRISCV::ToString() const
  {
    stringstream out_str;

    out_str << "PrivilegeLevel="  << EPrivilegeLevelType_to_string(mPrivilegeLevelType)
            << " MODE=" << BoolAttribute(EVmInfoBoolType::MODE)
            << " MPRV=" << BoolAttribute(EVmInfoBoolType::MPRV)
            << " TVM=" << BoolAttribute(EVmInfoBoolType::TVM);
            //<< " MPP=" << BoolAttribute(EVmInfoBoolType::MPP);

    return out_str.str();
  }

  void VmInfoRISCV::GetCurrentStates(const Generator& rGen)
  {
    SetPrivilegeLevel(rGen.PrivilegeLevel());
    auto reg_file = rGen.GetRegisterFile();
    auto satp_reg = reg_file->RegisterLookup("satp");
    GetRegisterFieldState(satp_reg, EVmInfoBoolType::MODE);

    auto mstatus_reg = reg_file->RegisterLookup("mstatus");
    GetRegisterFieldState(mstatus_reg, EVmInfoBoolType::MPRV);
    GetRegisterFieldState(mstatus_reg, EVmInfoBoolType::TVM); //Trap Virtual Memory - if paging enable will cause exceptions on all vm ops
    //need MPP to determine paging enabled for priv=m MPRV=1 MPP=S
    //this can create a new unique case where instr's are direct mapped and data accesses are translated via 'S' addr translation and protection

    // Read G-stage paging mode from hgatp register (only if initialized)
    auto hgatp_reg = reg_file->RegisterLookup("hgatp");
    if (hgatp_reg && hgatp_reg->IsInitialized()) {
      uint64 val = 0;
      try { val = hgatp_reg->Value(); } catch (...) { return; }
      uint32 mode = (val >> 60) & 0xF;
      switch (mode) {
        case 8: mGStagePagingMode = EPagingMode::Sv39x4; break;
        case 9: mGStagePagingMode = EPagingMode::Sv48x4; break;
        default: mGStagePagingMode = EPagingMode::Bare; break;
      }
    }
  }

  const string VmInfoRISCV::GetRegisterNameForField(EVmInfoBoolType attrType, const Generator& rGen) const
  {
    switch (attrType)
    {
      case EVmInfoBoolType::MODE:
        return "satp";
      case EVmInfoBoolType::MPRV:
      case EVmInfoBoolType::TVM:
        return "mstatus";
      default:
        LOG(fail) << "{VmInfoRISCV::GetRegisterNameForField} Unsupported bool attr enum value: " << EVmInfoBoolType_to_string(attrType) << endl;
        FAIL("invalid_attr_type");
    }
    return "";
  }

  bool VmInfoRISCV::PagingEnabled() const
  {
    if (BoolAttribute(EVmInfoBoolType::MODE) &&
        (mPrivilegeLevelType == EPrivilegeLevelType::S || mPrivilegeLevelType == EPrivilegeLevelType::U))
    {
      return true;
    }

    //if (mPrivilegeLevelType == EPrivilegeLevelType::M && BoolAttribute(EVmInfoBoolType::MPRV) && MPP == EPrivilegeLevelType::S)
    //  data accesses are paging enabled/instructions are not

    return false;
  }

  bool VmInfoRISCV::IsTwoStageTranslation() const
  {
    // Two-stage translation is active when both VS-stage (vsatp MODE != Bare)
    // and G-stage (hgatp MODE != Bare) translation are enabled.
    // This requires the hypervisor extension and VS/HS regime.
    if (mPrivilegeLevelType != EPrivilegeLevelType::S) {
      return false;
    }
    // Check if we have both vsatp and hgatp MODE fields set (non-Bare)
    bool vsatp_enabled = BoolAttribute(EVmInfoBoolType::MODE);
    // For two-stage, we need both stages active; vsatp MODE indicates VS-stage,
    // and G-stage mode is checked via GStagePagingMode().
    return vsatp_enabled && (GStagePagingMode() != EPagingMode::Bare);
  }

  EPagingMode VmInfoRISCV::GStagePagingMode() const
  {
    return mGStagePagingMode;
  }

}
