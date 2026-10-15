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
#include "GStagePteAttribute.h"

#include "Log.h"
#include "UtilityFunctions.h"
/*!\
  \file GStagePteAttribute.cc
  \brief G-stage PTE attribute helpers for Sv39x4/Sv48x4.
*/

using namespace std;

namespace Force {

  bool GStagePteAttribute::IsLeafPte(uint64 pteValue)
  {
    // Leaf PTE has at least one of R, W, or X set
    return (pteValue & 0xE) != 0;  // bits 3:1 (X, W, R)
  }

  uint64 GStagePteAttribute::EncodeHgatp(uint64 ppn, uint32 mode, uint32 vmid)
  {
    // hgatp format (RV64):
    // [63:60] - MODE
    // [59:44] - VMID
    // [43:0]  - PPN
    // MODE: 0=Bare, 8=Sv39x4, 9=Sv48x4
    
    uint64 hgatp = 0;
    
    // Set MODE in bits 63:60
    hgatp |= (static_cast<uint64>(mode & 0xF) << 60);
    
    // Set PPN in bits 43:0
    hgatp |= ppn & 0xFFFFFFFFFFFULL;
    
    // Set VMID in bits 59:44
    hgatp |= ((static_cast<uint64>(vmid) & 0x3FFFULL) << 44);
    
    return hgatp;
  }

  void GStagePteAttribute::DecodeHgatp(uint64 hgatpValue, uint64& ppn, uint32& mode, uint32& vmid)
  {
    // Extract MODE (bits 63:60)
    mode = (hgatpValue >> 60) & 0xF;
    
    // Extract PPN (bits 43:0)
    ppn = hgatpValue & 0xFFFFFFFFFFFULL;
    
    // Extract VMID (bits 59:44)
    vmid = (hgatpValue >> 44) & 0x3FFF;
  }

  bool GStagePteAttribute::ValidateGStagePte(uint64 pteValue, bool isLeaf, bool& rValid)
  {
    rValid = true;
    
    // Check V (Valid) bit
    if ((pteValue & 0x1) == 0) {
      // Invalid PTE - not necessarily an error
      rValid = false;
      return true;
    }
    
    if (isLeaf) {
      // Leaf PTE: must have at least one of R, W, X set
      if ((pteValue & 0xE) == 0) {
        LOG(warn) << "{GStagePteAttribute::ValidateGStagePte} leaf PTE has no R/W/X set" << endl;
        rValid = false;
        return false;
      }
      
      // Leaf PTE: G bit can be used
      // U bit must be 0 in G-stage
      if (pteValue & (1ULL << U_BIT)) {
        LOG(warn) << "{GStagePteAttribute::ValidateGStagePte} G-stage leaf PTE has U bit set" << endl;
        rValid = false;
        return false;
      }
    } else {
      // Non-leaf PTE (pointer to next level table):
      // - Must have V=1, R=0, W=0, X=0
      if (pteValue & 0xE) {
        LOG(warn) << "{GStagePteAttribute::ValidateGStagePte} non-leaf PTE has R/W/X set" << endl;
        rValid = false;
        return false;
      }
      
      // - G bit must be 0 in G-stage
      if (pteValue & (1ULL << G_BIT)) {
        LOG(warn) << "{GStagePteAttribute::ValidateGStagePte} G-stage non-leaf PTE has G bit set" << endl;
        rValid = false;
        return false;
      }
      
      // - U bit must be 0
      if (pteValue & (1ULL << U_BIT)) {
        LOG(warn) << "{GStagePteAttribute::ValidateGStagePte} G-stage non-leaf PTE has U bit set" << endl;
        rValid = false;
        return false;
      }
    }
    
    return true;
  }

}
