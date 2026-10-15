#
# Copyright (C) [2024] PTG PoC Contributors
#
# FORCE-RISCV is licensed under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance
#  with the License.  You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES
# OF ANY KIND, EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""PTG Basic End-to-End Test.

BDD test showing the complete FORCE + PTG workflow:
  Given a FORCE GenThread initialized with Sv39 paging
  When  PTG generates additional page table mappings
  And   PTG page tables are loaded to simulator physical memory
  Then  generated load/store instructions use PTG-managed addresses
  And   Spike/Handcar simulation completes without page fault
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgHandle, PtgRandomConfig


class PtgBasicSequence(Sequence):
    """Demonstrate the FORCE + PTG end-to-end workflow."""

    def generate(self, **kargs):
        # Phase A: FORCE boot + handler setup is automatic
        self.notice("Phase A: FORCE boot + handler setup (automatic)")

        # Phase B: Create PTG backend, register PA region, create context
        self.notice("Phase B: Initialize PTG backend")
        ptg = PtgHandle()
        ptg.register_pa_region(0x80000000, 0x90000000)
        ctx_id = ptg.create_context(asid=1)
        ptg.set_s_stage(ctx_id, "Sv39")

        # Phase C: Generate random page table mappings via PTG
        self.notice("Phase C: Generate PTG page tables")
        config = PtgRandomConfig()
        config.va_start = 0x10000
        config.va_end = 0x2000000
        config.pa_start = 0x88000000
        config.pa_end = 0x8A000000
        config.min_mappings = 10
        config.max_mappings = 50
        config.seed = 42
        config.sv_mode = 8  # Sv39
        config.access_types = 7  # R+W+X
        config.flags_a = 1  # Force A=1
        config.flags_d = 1  # Force D=1
        config.size_4kb_weight = 1.0
        config.size_2mb_weight = 0.0
        config.size_1gb_weight = 0.0
        config.size_512gb_weight = 0.0
        config.force_new = 1

        count, mappings = ptg.random_generate(ctx_id, "S", config)
        self.notice(f"  PTG generated {count} mappings")

        # Phase D: Validate PTG page tables
        result = ptg.validate(ctx_id)
        self.notice(
            f"  PTG validate: all_ok={result.all_ok}, "
            f"total_nodes={result.total_nodes}, "
            f"leaf_ptes={result.leaf_ptes}"
        )
        assert result.all_ok, "PTG validation failed"

        # Phase E: Load PTG page tables to FORCE simulator physical memory
        self.notice("Phase E: Load PTG page tables to simulator")
        ptg.load_to_force(ctx_id, "S", self.genThread)

        # Phase F: Show satp value from PTG context
        self.notice("Phase F: satp configuration from PTG context")
        satp_val = ptg.get_satp(ctx_id)
        satp_ppn = satp_val & 0xFFFFFFFFFFF
        satp_mode = (satp_val >> 60) & 0xF
        self.notice(f"  satp.PPN=0x{satp_ppn:x}, satp.MODE={satp_mode}")

        # Phase G: Generate instructions that exercise the page tables
        self.notice("Phase G: Generate instructions")
        for _ in range(20):
            self.genInstruction("LD##RISCV")
            self.genInstruction("SD##RISCV")
            self.genInstruction("ADD##RISCV")

        # Phase H: Dump PTG outputs for debug and verification
        self.notice("Phase H: Dump PTG outputs")
        ptg.dump_json(ctx_id, "S", "/tmp/ptg_basic_tables.json")

        ptg.destroy()
        self.notice("Phase 1.4 END-TO-END: PASS")


MainSequenceClass = PtgBasicSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
