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
#ifndef Force_GStagePteAttribute_H
#define Force_GStagePteAttribute_H

#include "Defines.h"
#include "Enums.h"
#include ARCH_ENUM_HEADER

namespace Force {

  /*!
    \class GStagePteAttribute
    \brief G-stage PTE attribute constants and helpers for Sv39x4/Sv48x4.
    
    Key differences from S-stage PTEs:
    - No U (User) bit — all pages are supervisor-level
    - RSW field is 2-bit (RSW2) instead of 1-bit (bits 9-8)
    - G (Global) bit is reserved for VS-stage, must be 0 in non-leaf PTEs
    - Svpbmt extension: N (NAPOT) bit support (bit 6)
  */
  class GStagePteAttribute
  {
  public:
    // G-stage PTE bit positions (Sv39x4/Sv48x4)
    static const uint32 V_BIT  = 0;   // Valid
    static const uint32 R_BIT  = 1;   // Read
    static const uint32 W_BIT  = 2;   // Write
    static const uint32 X_BIT  = 3;   // Execute
    static const uint32 U_BIT  = 4;   // User - NOT USED in G-stage
    static const uint32 G_BIT  = 5;   // Global - reserved in non-leaf
    static const uint32 N_BIT  = 6;   // NAPOT (Svpbmt)
    static const uint32 RSW2_LOW = 8; // RSW2 bit 0
    static const uint32 RSW2_HIGH = 9; // RSW2 bit 1

    // G-stage MODE values for hgatp
    static const uint32 MODE_BARE = 0;
    static const uint32 MODE_Sv39x4 = 8;
    static const uint32 MODE_Sv48x4 = 9;

    // Helper: Check if PTE is a leaf (has R, W, or X set)
    static bool IsLeafPte(uint64 pteValue);

    // Helper: Encode hgatp register value
    static uint64 EncodeHgatp(uint64 ppn, uint32 mode, uint32 vmid = 0);

    // Helper: Decode hgatp register value
    static void DecodeHgatp(uint64 hgatpValue, uint64& ppn, uint32& mode, uint32& vmid);

    // Validate G-stage PTE attributes
    static bool ValidateGStagePte(uint64 pteValue, bool isLeaf, bool& rValid);
  };
}

#endif //Force_GStagePteAttribute_H
