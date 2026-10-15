"""Validate HLV.D and HSV.D faults from invalid VS/G-stage leaf PTEs."""

import ctypes
import struct

from base.Sequence import Sequence
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from riscv.Utils import LoadGPR64
from riscv.paging.PtgBackend import (
    PTG_FAULT_ACCESS_READ,
    PTG_FAULT_ACCESS_WRITE,
    PTG_FAULT_ADDRESS_STAGE_NATIVE,
    PTG_FAULT_OK,
    PTG_FAULT_PRIV_VS,
    PTG_FAULT_SCOPE_DIRECT,
    PTG_FAULT_SELECTION_EXACT_ONE,
    PTG_FAULT_VALID_ACTUAL_MCAUSE,
    PTG_FAULT_VALID_EXPECTED_MCAUSE,
    PTG_FAULT_VALID_FAILING_GPA,
    PTG_FAULT_VALID_NEW_PTE,
    PTG_FAULT_VALID_OLD_PTE,
    PTG_FAULT_VALID_PTE_PA,
    PTG_FAULT_VALID_REQUESTED_ADDRESS,
    PTG_FAULT_VALID_RESOLVED_ADDRESS,
    PTG_FAULT_VERIFY_REQUIRE_FAULT,
    PTG_STAGE_G,
    PTG_STAGE_VS,
    PtgBackend,
)


VS_LOAD_GVA = 0x43000000
VS_LOAD_GPA = 0x86000000
VS_LOAD_SPA = 0x132000000
VS_STORE_GVA = 0x43200000
VS_STORE_GPA = 0x86200000
VS_STORE_SPA = 0x132200000
G_LOAD_GVA = 0x43400000
G_LOAD_GPA = 0x86400000
G_LOAD_SPA = 0x132400000
G_STORE_GVA = 0x43600000
G_STORE_GPA = 0x86600000
G_STORE_SPA = 0x132600000

VS_DATA_RW_AD = 0x63
G_RWX_UAD = 0x77

MSTATUS_MPP = 0x1800
MSTATUS_MPRV = 1 << 17
MSTATUS_GVA = 1 << 38
MSTATUS_MPV = 1 << 39

CSR_MSTATUS = 0x300
CSR_MEDELEG = 0x302
CSR_MTVEC = 0x305
CSR_MEPC = 0x341
CSR_MCAUSE = 0x342
CSR_MTVAL = 0x343
CSR_MTINST = 0x34A
CSR_MTVAL2 = 0x34B
CSR_HSTATUS = 0x600
CSR_HEDELEG = 0x602
CSR_SATP = 0x180


class MainSequence(Sequence):
    def generate(self, **kargs):
        code_base = (self.getPEstate("PC") + 0xFFF) & ~0xFFF
        scenarios = self._scenarios(code_base)

        ptg = PtgBackend()
        try:
            context = self._prepare_context(ptg, scenarios)
            fault_pcs = self._run_matrix(ptg, context, scenarios)
            for scenario, fault_pc in zip(scenarios, fault_pcs):
                self._assert_fault(scenario, fault_pc)

            self.notice("HLV/HSV INVALID VS/G PTE FAULT MATRIX: PASS")
        finally:
            ptg.destroy()

    def _scenarios(self, code_base):
        entries = tuple(code_base + (index + 1) * 0x1000 for index in range(4))
        handlers = tuple(code_base + (index + 5) * 0x1000 for index in range(4))
        result_registers = (
            (3, 4, 5, 6, 7, 9),
            (10, 11, 12, 13, 14, 15),
            (16, 17, 18, 19, 20, 21),
            (22, 23, 24, 25, 26, 27),
        )
        return (
            {
                "name": "HLV.D VS-stage invalid leaf",
                "stage": "VS",
                "access": "load",
                "gva": VS_LOAD_GVA,
                "gpa": VS_LOAD_GPA,
                "spa": VS_LOAD_SPA,
                "cause": 13,
                "side_effect_sentinel": 0x1111222233334444,
                "side_effect_register": 28,
                "entry": entries[0],
                "handler": handlers[0],
                "result_registers": result_registers[0],
            },
            {
                "name": "HSV.D VS-stage invalid leaf",
                "stage": "VS",
                "access": "store",
                "gva": VS_STORE_GVA,
                "gpa": VS_STORE_GPA,
                "spa": VS_STORE_SPA,
                "cause": 15,
                "side_effect_sentinel": 0x5555666677778888,
                "side_effect_register": 30,
                "entry": entries[1],
                "handler": handlers[1],
                "result_registers": result_registers[1],
            },
            {
                "name": "HLV.D G-stage invalid leaf",
                "stage": "G",
                "access": "load",
                "gva": G_LOAD_GVA,
                "gpa": G_LOAD_GPA,
                "spa": G_LOAD_SPA,
                "cause": 21,
                "side_effect_sentinel": 0x9999AAAABBBBCCCC,
                "side_effect_register": 29,
                "entry": entries[2],
                "handler": handlers[2],
                "result_registers": result_registers[2],
            },
            {
                "name": "HSV.D G-stage invalid leaf",
                "stage": "G",
                "access": "store",
                "gva": G_STORE_GVA,
                "gpa": G_STORE_GPA,
                "spa": G_STORE_SPA,
                "cause": 23,
                "side_effect_sentinel": 0xDDDDEEEEFFFF0001,
                "side_effect_register": 31,
                "entry": entries[3],
                "handler": handlers[3],
                "result_registers": result_registers[3],
            },
        )

    def _prepare_context(self, ptg, scenarios):
        context = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Sv39x4",
            asid=0x44,
            vmid=0x24,
            gpa_base=0x98000000,
            gpa_limit=0x99000000,
            pa_base=0x170000000,
            pa_limit=0x180000000,
        )
        for scenario in scenarios:
            ptg.handle.add_mapping(
                context,
                "VS",
                scenario["gva"],
                scenario["gpa"],
                0x1000,
                0,
                VS_DATA_RW_AD,
            )
            ptg.handle.add_mapping(
                context,
                "G",
                scenario["gpa"],
                scenario["spa"],
                0x1000,
                0,
                G_RWX_UAD,
            )

        if not ptg.validate(context).all_ok:
            self.error("HLV/HSV fault-matrix page tables failed clean-state validation")

        for scenario in scenarios:
            scenario["v2_result"] = self._inject_v2_fault(ptg, context, scenario)

        ptg.load_to_force(context, "VS", self.genThread)
        ptg.load_to_force(context, "G", self.genThread)
        for scenario in scenarios:
            if scenario["access"] == "store":
                self.genThread.writePhysicalMemory(
                    scenario["spa"],
                    struct.pack("<Q", scenario["side_effect_sentinel"]),
                    0,
                )
        return context

    def _inject_v2_fault(self, ptg, context, scenario):
        request = ptg.create_fault_request_v2()
        request.stage = PTG_STAGE_VS if scenario["stage"] == "VS" else PTG_STAGE_G
        request.scope = PTG_FAULT_SCOPE_DIRECT
        request.address_kind = PTG_FAULT_ADDRESS_STAGE_NATIVE
        request.selection_mode = PTG_FAULT_SELECTION_EXACT_ONE
        request.fault_cause = 1
        request.access_type = (
            PTG_FAULT_ACCESS_READ
            if scenario["access"] == "load"
            else PTG_FAULT_ACCESS_WRITE
        )
        request.privilege = PTG_FAULT_PRIV_VS
        request.verification_mode = PTG_FAULT_VERIFY_REQUIRE_FAULT
        request.target_level = 0
        request.has_target_address = 1
        request.target_address = (
            scenario["gva"] if scenario["stage"] == "VS" else scenario["gpa"]
        )
        request.dry_run = 1

        before = self._blocks(ptg, context, scenario["stage"])
        other_stage = "G" if scenario["stage"] == "VS" else "VS"
        before_other = self._blocks(ptg, context, other_stage)
        root_value = (
            ptg.handle.get_vsatp(context)
            if scenario["stage"] == "VS"
            else ptg.handle.get_hgatp(context)
        )
        expected_pte_pa = self._walk_pte_pa(
            before,
            (root_value & ((1 << 44) - 1)) << 12,
            request.target_address,
            0,
            9 if scenario["stage"] == "VS" else 11,
        )
        status, dry_results = ptg.inject_fault_v2(context, request)
        if status != PTG_FAULT_OK or len(dry_results) != 1:
            self.error(
                f"{scenario['name']} V2 dry-run failed: status={status}, "
                f"results={len(dry_results)}"
            )
        if self._blocks(ptg, context, scenario["stage"]) != before:
            self.error(f"{scenario['name']} V2 dry-run changed page-table bytes")
        if self._blocks(ptg, context, other_stage) != before_other:
            self.error(f"{scenario['name']} V2 dry-run changed {other_stage}-stage bytes")

        result = dry_results[0]
        required_fields = (
            PTG_FAULT_VALID_REQUESTED_ADDRESS
            | PTG_FAULT_VALID_RESOLVED_ADDRESS
            | PTG_FAULT_VALID_PTE_PA
            | PTG_FAULT_VALID_OLD_PTE
            | PTG_FAULT_VALID_NEW_PTE
            | PTG_FAULT_VALID_EXPECTED_MCAUSE
            | PTG_FAULT_VALID_ACTUAL_MCAUSE
        )
        if scenario["stage"] == "G":
            required_fields |= PTG_FAULT_VALID_FAILING_GPA
        if (
            result.status != PTG_FAULT_OK
            or result.stage != request.stage
            or result.scope != request.scope
            or result.requested_cause != 1
            or result.actual_cause != 1
            or result.requested_level != 0
            or result.resolved_level != 0
            or result.requested_address != request.target_address
            or result.resolved_address != request.target_address
            or (result.valid_fields & required_fields) != required_fields
            or result.expected_mcause != scenario["cause"]
            or result.actual_mcause != scenario["cause"]
            or result.pte_pa != expected_pte_pa
            or (result.old_pte & 1) == 0
            or result.new_pte != result.old_pte & ~1
        ):
            self.error(f"{scenario['name']} V2 result metadata mismatch")
        if scenario["stage"] == "G" and result.failing_gpa != scenario["gpa"]:
            self.error(f"{scenario['name']} V2 failing GPA mismatch")
        if self._pte_at(before, result.pte_pa) != result.old_pte:
            self.error(f"{scenario['name']} old PTE does not match pte_pa")

        request.dry_run = 0
        status, commit_results = ptg.inject_fault_v2(context, request)
        if status != PTG_FAULT_OK or len(commit_results) != 1:
            self.error(
                f"{scenario['name']} V2 commit failed: status={status}, "
                f"results={len(commit_results)}"
            )
        committed = commit_results[0]
        if bytes(committed) != bytes(result):
            self.error(f"{scenario['name']} dry-run and commit records differ")
        after = self._blocks(ptg, context, scenario["stage"])
        if self._pte_at(after, committed.pte_pa) != committed.new_pte:
            self.error(f"{scenario['name']} new PTE does not match pte_pa")
        self._assert_only_pte_changed(scenario, before, after, committed.pte_pa)
        if self._blocks(ptg, context, other_stage) != before_other:
            self.error(f"{scenario['name']} commit changed {other_stage}-stage bytes")

        self.notice(
            f"V2_RESULT name={scenario['name']} pte_pa=0x{committed.pte_pa:X} "
            f"old=0x{committed.old_pte:X} new=0x{committed.new_pte:X} "
            f"mcause={committed.actual_mcause} failing_gpa=0x{committed.failing_gpa:X}"
        )
        return committed

    def _blocks(self, ptg, context, stage):
        layout = ptg.handle.get_blocks(context, stage)
        if not layout:
            return ()
        try:
            blocks = layout.contents
            return tuple(
                sorted(
                    (
                        blocks.blocks[index].pa,
                        ctypes.string_at(
                            blocks.blocks[index].data, blocks.blocks[index].size
                        ),
                    )
                    for index in range(blocks.num_blocks)
                )
            )
        finally:
            ptg.handle.free_blocks(layout)

    def _pte_at(self, blocks, pte_pa):
        matches = []
        for base, data in blocks:
            offset = pte_pa - base
            if 0 <= offset and offset + 8 <= len(data):
                matches.append(int.from_bytes(data[offset : offset + 8], "little"))
        if len(matches) != 1:
            self.error(f"PTE PA 0x{pte_pa:X} matched {len(matches)} page-table blocks")
        return matches[0]

    def _walk_pte_pa(
        self, blocks, root_address, address, target_level, root_index_bits
    ):
        node_address = root_address
        for level in range(2, target_level - 1, -1):
            index_bits = root_index_bits if level == 2 else 9
            index = (address >> (12 + 9 * level)) & ((1 << index_bits) - 1)
            pte_pa = node_address + index * 8
            pte = self._pte_at(blocks, pte_pa)
            if level == target_level:
                return pte_pa
            node_address = (pte >> 10) << 12
        self.error(f"Unable to resolve target page-table level {target_level}")

    def _assert_only_pte_changed(self, scenario, before, after, pte_pa):
        before_by_base = dict(before)
        after_by_base = dict(after)
        if before_by_base.keys() != after_by_base.keys():
            self.error(f"{scenario['name']} changed the page-table block set")

        changed = []
        for base, old_data in before_by_base.items():
            new_data = after_by_base[base]
            if len(old_data) != len(new_data):
                self.error(f"{scenario['name']} changed a page-table block size")
            changed.extend(
                base + index
                for index, (old_byte, new_byte) in enumerate(zip(old_data, new_data))
                if old_byte != new_byte
            )
        if not changed or any(
            not pte_pa <= address < pte_pa + 8 for address in changed
        ):
            self.error(f"{scenario['name']} modified bytes outside the selected PTE")

    def _run_matrix(self, ptg, context, scenarios):
        block_id = self.beginLinearBlock()
        self.genThread.setupPtgCSRs(
            ptg_handle=ptg.handle,
            ctx_id=context,
            vs_mode="Sv39",
            g_mode="Sv39x4",
        )
        self._write_csr(CSR_SATP, 0)
        self._write_csr(CSR_MEDELEG, 0)
        self._write_csr(CSR_HEDELEG, 0)
        self._write_csr(CSR_HSTATUS, 0x300)
        self._prepare_mret(scenarios[0])

        fault_pcs = []
        for index, scenario in enumerate(scenarios):
            self.setPEstate("PC", scenario["entry"])
            self._load_gpr(1, scenario["gva"])
            if scenario["access"] == "store":
                self._load_gpr(2, 0xDEADBEEF01234567)
            else:
                self._load_gpr(2, scenario["side_effect_sentinel"])
            fault_pcs.append(self.getPEstate("PC"))
            if scenario["access"] == "load":
                self.genInstruction(
                    "HLV.D##RISCV", {"rd": 2, "rs1": 1, "NoRestriction": 1}
                )
            else:
                self.genInstruction(
                    "HSV.D##RISCV", {"rs1": 1, "rs2": 2, "NoRestriction": 1}
                )

            self.setPEstate("PC", scenario["handler"])
            self._capture_trap(scenario["result_registers"])
            if scenario["access"] == "load":
                self.genInstruction(
                    "ADDI##RISCV",
                    {
                        "rd": scenario["side_effect_register"],
                        "rs1": 2,
                        "simm12": 0,
                        "NoRestriction": 1,
                    },
                )
            else:
                self._load_gpr(1, scenario["spa"])
                self.genInstruction(
                    "LD##RISCV",
                    {
                        "rd": scenario["side_effect_register"],
                        "rs1": 1,
                        "simm12": 0,
                        "NoRestriction": 1,
                    },
                )
            if index + 1 < len(scenarios):
                self._prepare_mret(scenarios[index + 1])

        self.endLinearBlock(block_id)
        return fault_pcs

    def _prepare_mret(self, scenario):
        self._write_csr(CSR_MTVEC, scenario["handler"])
        self._write_csr(CSR_MTVAL, 0xCCCCCCCCCCCCCCCC)
        self._write_csr(CSR_MTVAL2, 0x5555555555555555)
        self._write_csr(CSR_MTINST, 0xAAAAAAAAAAAAAAAA)
        self._clear_csr_bits(CSR_MSTATUS, MSTATUS_MPP | MSTATUS_MPRV | MSTATUS_MPV)
        self._set_csr_bits(CSR_MSTATUS, MSTATUS_MPP)
        self._write_csr(CSR_MEPC, scenario["entry"])
        self.genInstruction("MRET##RISCV", {"NoRestriction": 1})

    def _capture_trap(self, registers):
        for csr, register_index in zip(
            (CSR_MCAUSE, CSR_MEPC, CSR_MTVAL, CSR_MTVAL2, CSR_MTINST, CSR_MSTATUS),
            registers,
        ):
            self._read_csr(csr, register_index)

    def _assert_fault(self, scenario, fault_pc):
        registers = scenario["result_registers"]
        self._assert_gpr(registers[0], scenario["cause"], f"{scenario['name']} mcause")
        self._assert_gpr(registers[1], fault_pc, f"{scenario['name']} mepc")
        self._assert_gpr(registers[2], scenario["gva"], f"{scenario['name']} mtval")
        result = scenario["v2_result"]
        expected_mtval2 = result.failing_gpa >> 2 if scenario["stage"] == "G" else 0
        self._assert_gpr(registers[3], expected_mtval2, f"{scenario['name']} mtval2")
        self._assert_gpr(registers[4], 0, f"{scenario['name']} mtinst")
        self._assert_gpr(
            scenario["side_effect_register"],
            scenario["side_effect_sentinel"],
            f"{scenario['name']} no side effect",
        )

        mstatus, valid = self.readRegister(f"x{registers[5]}")
        if (
            not valid
            or (mstatus & MSTATUS_MPV) != 0
            or (mstatus & MSTATUS_GVA) == 0
            or (mstatus & MSTATUS_MPP) != MSTATUS_MPP
        ):
            self.error(
                f"{scenario['name']} mstatus failed: mstatus=0x{mstatus:016X}, "
                "expected MPV=0, GVA=1, and MPP=M"
            )

    def _write_csr(self, csr, value):
        self._load_gpr(8, value)
        self.genInstruction(
            "CSRRW#register#RISCV",
            {"rd": 0, "rs1": 8, "csr": csr, "NoRestriction": 1},
        )

    def _read_csr(self, csr, register_index):
        self.genInstruction(
            "CSRRS#register#RISCV",
            {"rd": register_index, "rs1": 0, "csr": csr, "NoRestriction": 1},
        )

    def _clear_csr_bits(self, csr, mask):
        self._load_gpr(8, mask)
        self.genInstruction(
            "CSRRC#register#RISCV",
            {"rd": 0, "rs1": 8, "csr": csr, "NoRestriction": 1},
        )

    def _set_csr_bits(self, csr, mask):
        self._load_gpr(8, mask)
        self.genInstruction(
            "CSRRS#register#RISCV",
            {"rd": 0, "rs1": 8, "csr": csr, "NoRestriction": 1},
        )

    def _load_gpr(self, register_index, value):
        LoadGPR64(self.genThread).load(register_index, value)

    def _assert_gpr(self, register_index, expected, operation):
        actual, valid = self.readRegister(f"x{register_index}")
        if not valid or actual != expected:
            self.error(
                f"{operation} failed: x{register_index}=0x{actual:016X}, "
                f"expected=0x{expected:016X}"
            )


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
