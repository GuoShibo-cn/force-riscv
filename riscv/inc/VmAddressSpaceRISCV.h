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
#ifndef Force_VmAddressSpaceRISCV_H
#define Force_VmAddressSpaceRISCV_H

#include "VmAddressSpace.h"

#include <unordered_map>

namespace Force {

  class GenPageRequest;
  class VmGpaAddressSpace;

  /*!
    \class VmAddressSpaceRISCV
    \brief RISC-V specific address space with optional two-stage translation support.
    
    Extends VmAddressSpace to support the RISC-V H-extension two-stage address translation:
    - Stage-1 (VS-stage): GVA → GPA (controlled by vsatp)
    - Stage-2 (G-stage):  GPA → HPA (controlled by hgatp)
    
    When mTwoStageEnabled is false, this class behaves identically to VmAddressSpace.
    When enabled, translations chain through the G-stage address space.
  */
  class VmAddressSpaceRISCV : public VmAddressSpace
  {
  public:
    VmAddressSpaceRISCV(const VmFactory* pFactory, VmasControlBlock* pVmasCtlrBlock);
    virtual ~VmAddressSpaceRISCV() override;
    ASSIGNMENT_OPERATOR_ABSENT(VmAddressSpaceRISCV);

    Object* Clone() const override { return new VmAddressSpaceRISCV(*this); }
    const char* Type() const override { return "VmAddressSpaceRISCV"; }

    // Two-stage translation core interfaces
    void SetGpaAddressSpace(VmAddressSpaceRISCV* pGpaAs);
    void SetTwoStageEnabled(bool enabled);
    bool IsTwoStageEnabled() const { return mTwoStageEnabled; }

    // Override translation methods to support chained GVA→GPA→HPA translation
    ETranslationResultType TranslateVaToPa(uint64 VA, uint64& PA, uint32& bank) const override;
    ETranslationResultType TranslatePaToVa(uint64 PA, EMemBankType bank, uint64& VA) const override;

    // Override MapAddressRange to chain G-stage mapping when two-stage is enabled
    bool MapAddressRange(uint64 VA, uint64 size, bool isInstr, const GenPageRequest* pPageReq) override;

    // Full GVA→HPA two-stage translation
    ETranslationResultType TranslateGvaToHpa(uint64 GVA, uint64& HPA, uint32& bank) const;

    // Page table operations for two-stage setup
    void SetupTwoStagePageTables(uint64 GVA, uint64 size, bool isInstr, GenPageRequest* pPageReq);

    // Translation cache management
    void InvalidateTranslationCache();
    void InvalidateCacheEntry(uint64 GVA);

  protected:
    VmAddressSpaceRISCV();
    VmAddressSpaceRISCV(const VmAddressSpaceRISCV& rOther);

  protected:
    VmAddressSpaceRISCV* mpGpaAddressSpace;  // Points to G-stage address space (only for VS regime)
    bool mTwoStageEnabled;

    // Simple translation cache for two-stage translation (iteration 1)
    struct TranslationCacheEntry {
      uint64 gva;      // Guest Virtual Address (page-aligned)
      uint64 hpa;      // Host Physical Address
      uint32 bank;     // Memory bank
      bool valid;      // Cache entry validity
    };
    mutable std::unordered_map<uint64, TranslationCacheEntry> mTranslationCache;
    static const uint64 CACHE_PAGE_SIZE = 4096; // 4KB page size for cache granularity
    static const uint64 MAX_CACHE_SIZE = 256;   // Limit cache size to 256 entries
  };
}

#endif //Force_VmAddressSpaceRISCV_H
