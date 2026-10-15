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
#include "VmAddressSpaceRISCV.h"

#include <algorithm>
#include <memory>

#include "Constraint.h"
#include "GenRequest.h"
#include "Generator.h"
#include "Log.h"
#include "Memory.h"
#include "Page.h"
#include "PagingInfo.h"
#include "UtilityFunctions.h"
#include "VmUtils.h"
/*!\
  \file VmAddressSpaceRISCV.cc
  \brief RISC-V address space with two-stage translation support.
*/

using namespace std;

namespace Force {

  VmAddressSpaceRISCV::VmAddressSpaceRISCV(const VmFactory* pFactory, VmasControlBlock* pVmasCtlrBlock)
    : VmAddressSpace(pFactory, pVmasCtlrBlock), mpGpaAddressSpace(nullptr), mTwoStageEnabled(false),
      mTranslationCache()
  {
  }

  VmAddressSpaceRISCV::VmAddressSpaceRISCV()
    : VmAddressSpace(), mpGpaAddressSpace(nullptr), mTwoStageEnabled(false),
      mTranslationCache()
  {
  }

  VmAddressSpaceRISCV::VmAddressSpaceRISCV(const VmAddressSpaceRISCV& rOther)
    : VmAddressSpace(rOther), mpGpaAddressSpace(rOther.mpGpaAddressSpace), mTwoStageEnabled(rOther.mTwoStageEnabled),
      mTranslationCache()
  {
    // G-stage address space is not cloned - it's shared
    // Cache is not copied - will be rebuilt as needed
  }

  VmAddressSpaceRISCV::~VmAddressSpaceRISCV()
  {
    // Note: mpGpaAddressSpace is not owned by this object, so we don't delete it
    mpGpaAddressSpace = nullptr;
  }

  void VmAddressSpaceRISCV::SetGpaAddressSpace(VmAddressSpaceRISCV* pGpaAs)
  {
    mpGpaAddressSpace = pGpaAs;
  }

  void VmAddressSpaceRISCV::SetTwoStageEnabled(bool enabled)
  {
    mTwoStageEnabled = enabled;
  }

  bool VmAddressSpaceRISCV::MapAddressRange(uint64 VA, uint64 size, bool isInstr, const GenPageRequest* pPageReq)
  {
    // Always call base class to map GVA→GPA in VS-stage
    bool result = VmAddressSpace::MapAddressRange(VA, size, isInstr, pPageReq);

    // If two-stage is enabled, also map the corresponding GPA range in G-stage
    // This ensures HLV/HSV addresses (and any GVA) have G-stage pages allocated
    if (mTwoStageEnabled && mpGpaAddressSpace != nullptr) {
      LOG(trace) << "{VmAddressSpaceRISCV::MapAddressRange} chaining G-stage map for GPA 0x"
                 << std::hex << VA << " size 0x" << size << std::dec << std::endl;
      mpGpaAddressSpace->MapAddressRange(VA, size, isInstr, pPageReq);
    }
    return result;
  }

  ETranslationResultType VmAddressSpaceRISCV::TranslateVaToPa(uint64 VA, uint64& PA, uint32& bank) const
  {
    if (!mTwoStageEnabled || mpGpaAddressSpace == nullptr) {
      // Single-stage translation: GVA → GPA (or VA → PA in non-virtualized mode)
      return VmAddressSpace::TranslateVaToPa(VA, PA, bank);
    }

    // Check translation cache first
    uint64 cache_key = VA / CACHE_PAGE_SIZE;
    auto cache_it = mTranslationCache.find(cache_key);
    if (cache_it != mTranslationCache.end() && cache_it->second.valid) {
      // Cache hit - return cached translation
      PA = cache_it->second.hpa | (VA % CACHE_PAGE_SIZE);
      bank = cache_it->second.bank;
      LOG(trace) << "{VmAddressSpaceRISCV::TranslateVaToPa} Cache hit: GVA 0x" << hex << VA 
                 << " → HPA 0x" << PA << dec << endl;
      return ETranslationResultType::Mapped;
    }

    // Cache miss - perform two-stage translation
    uint64 GPA = 0;
    uint32 gpa_bank = 0;
    
    // Stage 1: GVA → GPA
    ETranslationResultType s1_result = VmAddressSpace::TranslateVaToPa(VA, GPA, gpa_bank);
    if (s1_result != ETranslationResultType::Mapped) {
      LOG(trace) << "{VmAddressSpaceRISCV::TranslateVaToPa} Stage-1 translation failed for GVA 0x" 
                 << hex << VA << " result: " << ETranslationResultType_to_string(s1_result) << endl;
      PA = VA; // Return untranslated address on failure
      bank = gpa_bank;
      return s1_result;
    }

    LOG(trace) << "{VmAddressSpaceRISCV::TranslateVaToPa} Stage-1: GVA 0x" << hex << VA 
               << " → GPA 0x" << GPA << dec << endl;

    // Stage 2: GPA → HPA
    ETranslationResultType s2_result = mpGpaAddressSpace->TranslateVaToPa(GPA, PA, bank);
    if (s2_result != ETranslationResultType::Mapped) {
      LOG(trace) << "{VmAddressSpaceRISCV::TranslateVaToPa} Stage-2 translation failed for GPA 0x" 
                 << hex << GPA << " result: " << ETranslationResultType_to_string(s2_result) << endl;
      PA = GPA; // Return GPA on stage-2 failure (for fault handling)
      bank = gpa_bank;
      return s2_result;
    }

    LOG(trace) << "{VmAddressSpaceRISCV::TranslateVaToPa} Stage-2: GPA 0x" << hex << GPA 
               << " → HPA 0x" << PA << dec << endl;

    // Cache the successful translation
    TranslationCacheEntry entry;
    entry.gva = VA - (VA % CACHE_PAGE_SIZE); // Page-aligned GVA
    entry.hpa = PA - (PA % CACHE_PAGE_SIZE); // Page-aligned HPA
    entry.bank = bank;
    entry.valid = true;
    
    // Limit cache size
    if (mTranslationCache.size() >= MAX_CACHE_SIZE) {
      // Clear half of the cache when full
      uint64 entries_to_remove = MAX_CACHE_SIZE / 2;
      uint64 removed = 0;
      for (auto it = mTranslationCache.begin(); it != mTranslationCache.end() && removed < entries_to_remove; ) {
        it = mTranslationCache.erase(it);
        removed++;
      }
    }
    
    mTranslationCache[cache_key] = entry;

    return ETranslationResultType::Mapped;
  }

  ETranslationResultType VmAddressSpaceRISCV::TranslatePaToVa(uint64 PA, EMemBankType bank, uint64& VA) const
  {
    if (!mTwoStageEnabled || mpGpaAddressSpace == nullptr) {
      return VmAddressSpace::TranslatePaToVa(PA, bank, VA);
    }

    // Two-stage reverse: HPA → GPA → GVA
    uint64 GPA = 0;
    ETranslationResultType s2_result = mpGpaAddressSpace->TranslatePaToVa(PA, bank, GPA);
    if (s2_result != ETranslationResultType::Mapped) {
      return s2_result;
    }

    return VmAddressSpace::TranslatePaToVa(GPA, bank, VA);
  }

  ETranslationResultType VmAddressSpaceRISCV::TranslateGvaToHpa(uint64 GVA, uint64& HPA, uint32& bank) const
  {
    return TranslateVaToPa(GVA, HPA, bank);
  }

  void VmAddressSpaceRISCV::SetupTwoStagePageTables(uint64 GVA, uint64 size, bool isInstr, GenPageRequest* pPageReq)
  {
    if (!mTwoStageEnabled || mpGpaAddressSpace == nullptr) {
      LOG(warn) << "{VmAddressSpaceRISCV::SetupTwoStagePageTables} two-stage translation not enabled" << endl;
      return;
    }

    LOG(info) << "{VmAddressSpaceRISCV::SetupTwoStagePageTables} setting up GVA 0x" << hex << GVA 
              << " size 0x" << size << dec << endl;

    // Map G-stage (GPA → HPA) first, then VS-stage (GVA → GPA)
    uint64 GPA = GVA; // initially same as GVA for the mapping range base
    if (mpGpaAddressSpace) {
      mpGpaAddressSpace->MapAddressRange(GPA, size, isInstr, pPageReq);
    }
    MapAddressRange(GVA, size, isInstr, pPageReq);

    // Invalidate cache entries for the mapped range
    InvalidateCacheEntry(GVA);
  }

  void VmAddressSpaceRISCV::InvalidateTranslationCache()
  {
    mTranslationCache.clear();
    LOG(trace) << "{VmAddressSpaceRISCV::InvalidateTranslationCache} cache cleared" << endl;
  }

  void VmAddressSpaceRISCV::InvalidateCacheEntry(uint64 GVA)
  {
    uint64 cache_key = GVA / CACHE_PAGE_SIZE;
    mTranslationCache.erase(cache_key);
    LOG(trace) << "{VmAddressSpaceRISCV::InvalidateCacheEntry} invalidated entry for GVA 0x" << hex << GVA << dec << endl;
  }

}
