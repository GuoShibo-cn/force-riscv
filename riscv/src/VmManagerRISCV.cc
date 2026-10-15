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
#include "VmManagerRISCV.h"

#include "Config.h"
#include "Log.h"
#include "VmAddressSpaceRISCV.h"
#include "VmFactoryRISCV.h"
#include "VmGpaAddressSpace.h"
#include "VmInfoRISCV.h"

using namespace std;

namespace Force {

  VmManagerRISCV::VmManagerRISCV(const VmManagerRISCV& rOther)
    : VmManager(rOther), mTwoStageSetupDone(rOther.mTwoStageSetupDone)
  {
  }

  VmManagerRISCV::~VmManagerRISCV()
  {
  }

  VmInfo* VmManagerRISCV::VmInfoInstance() const
  {
    return new VmInfoRISCV();
  }

  VmFactory* VmManagerRISCV::VmFactoryInstance(EVmRegimeType vmRegimeType) const
  {
    return new VmFactoryRISCV(vmRegimeType);
  }
  void VmManagerRISCV::Update()
  {
    VmManager::Update();

    // Lazily set up two-stage translation when VS/HS regimes exist.
    // Only attempt if regimes are already registered to avoid std::out_of_range.
    if (mTwoStageSetupDone)
      return;

    auto hs_idx = EVmRegimeTypeBaseType(EVmRegimeType::HS);
    auto vs_idx = EVmRegimeTypeBaseType(EVmRegimeType::VS);
    if (mVmRegimes.size() <= size_t(hs_idx) || mVmRegimes.size() <= size_t(vs_idx))
      return;

    mTwoStageSetupDone = true;
    SetupTwoStageRISCV();
  }

  void VmManagerRISCV::SetupTwoStageRISCV()
  {
    LOG(notice) << "{VmManagerRISCV::SetupTwoStageRISCV} Attempting two-stage address translation setup" << endl;

    // Get VS and HS regime objects
    auto vs_regime = GetVmRegime(EVmRegimeType::VS);
    auto hs_regime = GetVmRegime(EVmRegimeType::HS);

    if (!vs_regime || !hs_regime) {
      LOG(warn) << "{VmManagerRISCV::SetupTwoStageRISCV} VS or HS regime not registered" << endl;
      return;
    }

    // Activate regimes to ensure mappers are created.
    // Activate() is safe to call multiple times.
    vs_regime->Activate();
    hs_regime->Activate();

    VmMapper* vs_mapper = vs_regime->CurrentVmMapper();
    VmMapper* hs_mapper = hs_regime->CurrentVmMapper();

    if (!vs_mapper || !hs_mapper) {
      LOG(warn) << "{VmManagerRISCV::SetupTwoStageRISCV} VS or HS mapper still null after activation" << endl;
      return;
    }

    // Cast mappers to paging mappers to access address spaces
    VmPagingMapper* vs_paging_mapper = dynamic_cast<VmPagingMapper*>(vs_mapper);
    VmPagingMapper* hs_paging_mapper = dynamic_cast<VmPagingMapper*>(hs_mapper);

    if (!vs_paging_mapper || !hs_paging_mapper) {
      LOG(warn) << "{VmManagerRISCV::SetupTwoStageRISCV} VS or HS mapper is not a paging mapper" << endl;
      return;
    }

    // Get address spaces from paging mappers
    VmAddressSpace* vs_as_raw = vs_paging_mapper->CurrentAddressSpace();
    VmAddressSpace* hs_as_raw = hs_paging_mapper->CurrentAddressSpace();

    if (!vs_as_raw || !hs_as_raw) {
      LOG(warn) << "{VmManagerRISCV::SetupTwoStageRISCV} VS or HS address space is null" << endl;
      return;
    }

    // Cast to RISC-V specific address spaces
    VmAddressSpaceRISCV* vs_as = dynamic_cast<VmAddressSpaceRISCV*>(vs_as_raw);
    VmGpaAddressSpace* hs_as = dynamic_cast<VmGpaAddressSpace*>(hs_as_raw);

    if (!vs_as || !hs_as) {
      LOG(warn) << "{VmManagerRISCV::SetupTwoStageRISCV} Failed to cast to RISC-V address space types" << endl;
      return;
    }

    // Connect VS-stage to G-stage address space
    vs_as->SetGpaAddressSpace(hs_as);
    vs_as->SetTwoStageEnabled(true);

    LOG(notice) << "{VmManagerRISCV::SetupTwoStageRISCV} Two-stage translation chain: GVA -> GPA -> HPA established" << endl;

    // Call base class two-stage setup
    SetupTwoStageTranslation();

    LOG(notice) << "{VmManagerRISCV::SetupTwoStageRISCV} COMPLETED successfully" << endl;
  }

}
