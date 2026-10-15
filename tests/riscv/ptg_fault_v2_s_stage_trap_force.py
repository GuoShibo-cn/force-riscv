"""Validate V2 S-stage instruction and data page faults through Handcar."""

from base.Sequence import Sequence
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from riscv.Utils import LoadGPR64
from riscv.paging.PtgBackend import (
    PTG_FAULT_ACCESS_EXECUTE,
    PTG_FAULT_ACCESS_READ,
    PTG_FAULT_ACCESS_WRITE,
    PTG_FAULT_ADDRESS_STAGE_NATIVE,
    PTG_FAULT_OK,
    PTG_FAULT_PRIV_S,
    PTG_FAULT_SCOPE_DIRECT,
    PTG_FAULT_SELECTION_EXACT_ONE,
    PTG_FAULT_VALID_ACTUAL_MCAUSE,
    PTG_FAULT_VALID_EXPECTED_MCAUSE,
    PTG_FAULT_VALID_NEW_PTE,
    PTG_FAULT_VALID_OLD_PTE,
    PTG_FAULT_VALID_PTE_PA,
    PTG_FAULT_VALID_REQUESTED_ADDRESS,
    PTG_FAULT_VALID_RESOLVED_ADDRESS,
    PTG_FAULT_VERIFY_REQUIRE_FAULT,
    PTG_STAGE_S,
    PtgBackend,
)


S_DATA_RW_AD = 0x63
S_CODE_X_AD = 0x64

MSTATUS_MPP = 0x1800
MSTATUS_MPP_S = 0x800
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
            self.notice("REAL V2 S-STAGE DIRECT PAGE-FAULT MATRIX: PASS")
        finally:
            ptg.destroy()

    def _scenarios(self, code_base):
        entries = tuple(code_base + (index + 1) * 0x1000 for index in range(3))
        handlers = tuple(code_base + (index + 4) * 0x1000 for index in range(3))
        accesses = (
            ("load", PTG_FAULT_ACCESS_READ, 13),
            ("store", PTG_FAULT_ACCESS_WRITE, 15),
            ("execute", PTG_FAULT_ACCESS_EXECUTE, 12),
        )
        registers = (
            (3, 4, 5, 6, 7, 9),
            (10, 11, 12, 13, 14, 15),
            (16, 17, 18, 19, 20, 21),
        )
        scenarios = []
        for index, (access, access_type, cause) in enumerate(accesses):
            va = (
                entries[index] if access == "execute" else 0x45000000 + index * 0x200000
            )
            scenarios.append(
                {
                    "name": f"S-stage {access} page fault",
                    "access": access,
                    "access_type": access_type,
                    "cause": cause,
                    "va": va,
                    "pa": 0x191000000 + index * 0x200000,
                    "entry": entries[index],
                    "handler": handlers[index],
                    "result_registers": registers[index],
                }
            )
        return tuple(scenarios)

    def _prepare_context(self, ptg, scenarios):
        context = ptg.create_s_stage_context(
            sv_mode="Sv39",
            asid=0x46,
            pa_base=0x190000000,
            pa_limit=0x1A0000000,
        )
        for index, scenario in enumerate(scenarios):
            if scenario["access"] != "execute":
                ptg.handle.add_mapping(
                    context,
                    "S",
                    scenario["va"],
                    scenario["pa"],
                    0x1000,
                    0,
                    S_DATA_RW_AD,
                )
            code_pa = (
                scenario["pa"] if scenario["access"] == "execute" else scenario["entry"]
            )
            ptg.handle.add_mapping(
                context,
                "S",
                scenario["entry"],
                code_pa,
                0x1000,
                0,
                S_CODE_X_AD,
            )

        if not ptg.validate(context).all_ok:
            self.error("S-stage PTG page tables failed clean-state validation")

        for scenario in scenarios:
            scenario["v2_result"] = self._inject_v2_fault(ptg, context, scenario)

        ptg.load_to_force(context, "S", self.genThread)
        return context

    def _inject_v2_fault(self, ptg, context, scenario):
        request = ptg.create_fault_request_v2()
        request.stage = PTG_STAGE_S
        request.scope = PTG_FAULT_SCOPE_DIRECT
        request.address_kind = PTG_FAULT_ADDRESS_STAGE_NATIVE
        request.selection_mode = PTG_FAULT_SELECTION_EXACT_ONE
        request.fault_cause = 1
        request.access_type = scenario["access_type"]
        request.privilege = PTG_FAULT_PRIV_S
        request.verification_mode = PTG_FAULT_VERIFY_REQUIRE_FAULT
        request.target_level = 0
        request.has_target_address = 1
        request.target_address = scenario["va"]
        request.dry_run = 1

        before = tuple(sorted(ptg.handle.get_force_blocks(context, "S")))
        status, dry_results = ptg.inject_fault_v2(context, request)
        if status != PTG_FAULT_OK or len(dry_results) != 1:
            self.error(
                f"{scenario['name']} V2 dry-run failed: status={status}, "
                f"results={len(dry_results)}"
            )
        if tuple(sorted(ptg.handle.get_force_blocks(context, "S"))) != before:
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
        if (
            result.status != PTG_FAULT_OK
            or result.stage != PTG_STAGE_S
            or result.scope != PTG_FAULT_SCOPE_DIRECT
            or result.requested_cause != 1
            or result.actual_cause != 1
            or result.requested_level != 0
            or result.resolved_level != 0
            or result.requested_address != scenario["va"]
            or result.resolved_address != scenario["va"]
            or (result.valid_fields & required_fields) != required_fields
            or result.expected_mcause != scenario["cause"]
            or result.actual_mcause != scenario["cause"]
            or (result.old_pte & 1) == 0
            or (result.new_pte & 1) != 0
        ):
            self.error(f"{scenario['name']} V2 dry-run result metadata mismatch")

        request.dry_run = 0
        status, commit_results = ptg.inject_fault_v2(context, request)
        if status != PTG_FAULT_OK or len(commit_results) != 1:
            self.error(
                f"{scenario['name']} V2 commit failed: status={status}, "
                f"results={len(commit_results)}"
            )
        committed = commit_results[0]
        if bytes(committed) != bytes(result):
            self.error(f"{scenario['name']} V2 dry-run and commit records differ")
        after = tuple(sorted(ptg.handle.get_force_blocks(context, "S")))
        encoded = int(committed.new_pte).to_bytes(8, byteorder="little")
        if after == before or not any(encoded in data for _, data in after):
            self.error(
                f"{scenario['name']} committed PTE is absent from S-stage output"
            )

        self.notice(
            f"V2_S_RESULT name={scenario['name']} pte_pa=0x{committed.pte_pa:X} "
            f"old=0x{committed.old_pte:X} new=0x{committed.new_pte:X} "
            f"mcause={committed.actual_mcause}"
        )
        return committed

    def _run_matrix(self, ptg, context, scenarios):
        block_id = self.beginLinearBlock()
        self._write_csr(CSR_SATP, ptg.handle.get_satp(context))
        self._write_csr(CSR_MEDELEG, 0)
        self._prepare_mret(scenarios[0])

        fault_pcs = []
        for index, scenario in enumerate(scenarios):
            self.setPEstate("PC", scenario["entry"])
            if scenario["access"] != "execute":
                self._load_gpr(1, scenario["va"])
            if scenario["access"] == "store":
                self._load_gpr(2, 0xDEADBEEF01234567)
            fault_pcs.append(self.getPEstate("PC"))
            if scenario["access"] == "load":
                self.genInstruction(
                    "LD##RISCV",
                    {"rd": 2, "rs1": 1, "simm12": 0, "NoRestriction": 1},
                )
            elif scenario["access"] == "store":
                self.genInstruction(
                    "SD##RISCV",
                    {"rs1": 1, "rs2": 2, "simm12": 0, "NoRestriction": 1},
                )
            else:
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
        self._set_csr_bits(CSR_MSTATUS, MSTATUS_MPP_S)
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
        self._assert_gpr(registers[2], scenario["va"], f"{scenario['name']} mtval")
        self._assert_gpr(registers[3], 0, f"{scenario['name']} mtval2")
        self._assert_gpr(registers[4], 0, f"{scenario['name']} mtinst")

        mstatus, valid = self.readRegister(f"x{registers[5]}")
        if (
            not valid
            or (mstatus & MSTATUS_MPV) != 0
            or (mstatus & MSTATUS_GVA) != 0
            or (mstatus & MSTATUS_MPP) != MSTATUS_MPP_S
        ):
            self.error(
                f"{scenario['name']} mstatus failed: mstatus=0x{mstatus:016X}, "
                "expected MPV=0, GVA=0, and MPP=S"
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
