"""Validate V2 instruction page faults through real Handcar execution."""

from base.Sequence import Sequence
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from riscv.Utils import LoadGPR64
from riscv.paging.PtgBackend import (
    PTG_FAULT_ACCESS_EXECUTE,
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


VS_EXEC_GPA = 0x85800000
G_EXEC_GPA = 0x85A00000
VS_CODE_X_AD = 0x64
G_RWX_UAD = 0x77

MSTATUS_MPP = 0x1800
MSTATUS_MPP_S = 0x800
MSTATUS_MPRV = 1 << 17
MSTATUS_GVA = 1 << 38
MSTATUS_MPV = 1 << 39
HSTATUS_VTSR = 1 << 22

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
            self.notice("REAL V2 INSTRUCTION PAGE-FAULT MATRIX: PASS")
        finally:
            ptg.destroy()

    def _scenarios(self, code_base):
        entries = (code_base + 0x1000, code_base + 0x2000)
        handlers = (code_base + 0x3000, code_base + 0x4000)
        return (
            {
                "name": "VS-stage instruction page fault",
                "stage": "VS",
                "gva": entries[0],
                "gpa": VS_EXEC_GPA,
                "spa": entries[0],
                "cause": 12,
                "guest_entry": entries[0],
                "handler": handlers[0],
                "result_registers": (3, 4, 5, 6, 7, 9),
            },
            {
                "name": "G-stage instruction guest-page-fault",
                "stage": "G",
                "gva": entries[1],
                "gpa": G_EXEC_GPA,
                "spa": entries[1],
                "cause": 20,
                "guest_entry": entries[1],
                "handler": handlers[1],
                "result_registers": (10, 11, 12, 13, 14, 15),
            },
        )

    def _prepare_context(self, ptg, scenarios):
        context = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Sv39x4",
            asid=0x43,
            vmid=0x23,
            gpa_base=0x97000000,
            gpa_limit=0x98000000,
            pa_base=0x160000000,
            pa_limit=0x170000000,
        )
        for scenario in scenarios:
            ptg.handle.add_mapping(
                context,
                "VS",
                scenario["gva"],
                scenario["gpa"],
                0x1000,
                0,
                VS_CODE_X_AD,
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
            self.error(
                "Instruction-fault PTG page tables failed clean-state validation"
            )

        for scenario in scenarios:
            scenario["v2_result"] = self._inject_v2_fault(ptg, context, scenario)
        ptg.load_to_force(context, "VS", self.genThread)
        ptg.load_to_force(context, "G", self.genThread)
        return context

    def _inject_v2_fault(self, ptg, context, scenario):
        request = ptg.create_fault_request_v2()
        request.stage = PTG_STAGE_VS if scenario["stage"] == "VS" else PTG_STAGE_G
        request.scope = PTG_FAULT_SCOPE_DIRECT
        request.address_kind = PTG_FAULT_ADDRESS_STAGE_NATIVE
        request.selection_mode = PTG_FAULT_SELECTION_EXACT_ONE
        request.fault_cause = 1
        request.access_type = PTG_FAULT_ACCESS_EXECUTE
        request.privilege = PTG_FAULT_PRIV_VS
        request.verification_mode = PTG_FAULT_VERIFY_REQUIRE_FAULT
        request.target_level = 0
        request.has_target_address = 1
        request.target_address = (
            scenario["gva"] if scenario["stage"] == "VS" else scenario["gpa"]
        )
        request.dry_run = 1

        before = tuple(sorted(ptg.handle.get_force_blocks(context, scenario["stage"])))
        status, dry_results = ptg.inject_fault_v2(context, request)
        if status != PTG_FAULT_OK or len(dry_results) != 1:
            self.error(
                f"{scenario['name']} V2 dry-run failed: status={status}, "
                f"results={len(dry_results)}"
            )
        if (
            tuple(sorted(ptg.handle.get_force_blocks(context, scenario["stage"])))
            != before
        ):
            self.error(f"{scenario['name']} V2 dry-run changed page-table bytes")

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
            or result.requested_cause != 1
            or result.actual_cause != 1
            or result.requested_level != 0
            or result.resolved_level != 0
            or result.requested_address != request.target_address
            or result.resolved_address != request.target_address
            or (result.valid_fields & required_fields) != required_fields
            or result.expected_mcause != scenario["cause"]
            or result.actual_mcause != scenario["cause"]
            or (result.old_pte & 1) == 0
            or (result.new_pte & 1) != 0
        ):
            self.error(f"{scenario['name']} V2 result metadata mismatch")
        if scenario["stage"] == "G" and result.failing_gpa != scenario["gpa"]:
            self.error(f"{scenario['name']} V2 failing GPA mismatch")

        request.dry_run = 0
        status, commit_results = ptg.inject_fault_v2(context, request)
        if status != PTG_FAULT_OK or len(commit_results) != 1:
            self.error(f"{scenario['name']} V2 commit failed: status={status}")
        committed = commit_results[0]
        if bytes(committed) != bytes(result):
            self.error(f"{scenario['name']} dry-run and commit records differ")
        after = tuple(sorted(ptg.handle.get_force_blocks(context, scenario["stage"])))
        encoded = int(committed.new_pte).to_bytes(8, byteorder="little")
        if after == before or not any(encoded in data for _, data in after):
            self.error(f"{scenario['name']} committed PTE is absent from PTG output")
        self.notice(
            f"V2_RESULT name={scenario['name']} pte_pa=0x{committed.pte_pa:X} "
            f"old=0x{committed.old_pte:X} new=0x{committed.new_pte:X} "
            f"mcause={committed.actual_mcause} failing_gpa=0x{committed.failing_gpa:X}"
        )
        return committed

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
        self._clear_csr_bits(CSR_HSTATUS, HSTATUS_VTSR)
        self._prepare_mret(scenarios[0])

        fault_pcs = []
        for index, scenario in enumerate(scenarios):
            self.setPEstate("PC", scenario["guest_entry"])
            fault_pcs.append(self.getPEstate("PC"))
            self.genInstruction(
                "ADDI##RISCV",
                {"rd": 0, "rs1": 0, "simm12": 0, "NoRestriction": 1},
            )
            self.setPEstate("PC", scenario["handler"])
            self._capture_trap(scenario["result_registers"])
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
        self._set_csr_bits(CSR_MSTATUS, MSTATUS_MPP_S | MSTATUS_MPV)
        self._write_csr(CSR_MEPC, scenario["guest_entry"])
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

        mstatus, valid = self.readRegister(f"x{registers[5]}")
        if (
            not valid
            or (mstatus & MSTATUS_MPV) == 0
            or (mstatus & MSTATUS_GVA) == 0
            or (mstatus & MSTATUS_MPP) != MSTATUS_MPP_S
        ):
            self.error(
                f"{scenario['name']} mstatus failed: mstatus=0x{mstatus:016X}, "
                "expected MPV=1, GVA=1, and MPP=S"
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
