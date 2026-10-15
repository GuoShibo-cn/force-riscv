"""Validate real VS-stage and G-stage data faults through Handcar."""

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


VS_LOAD_GVA = 0x42000000
VS_LOAD_GPA = 0x85000000
VS_LOAD_SPA = 0x131000000
VS_STORE_GVA = 0x42200000
VS_STORE_GPA = 0x85200000
VS_STORE_SPA = 0x131200000
G_LOAD_GVA = 0x42400000
G_LOAD_GPA = 0x85400000
G_LOAD_SPA = 0x131400000
G_STORE_GVA = 0x42600000
G_STORE_GPA = 0x85600000
G_STORE_SPA = 0x131600000

VS_DATA_RW_AD = 0x63
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
        block_start = self.getPEstate("PC")
        code_base = (block_start + 0xFFF) & ~0xFFF
        scenarios = self._scenarios(code_base)

        ptg = PtgBackend()
        try:
            ctx = self._prepare_context(ptg, scenarios)
            fault_pcs = self._run_fault_matrix(ptg, ctx, scenarios)
            for scenario, fault_pc in zip(scenarios, fault_pcs):
                self._assert_fault(scenario, fault_pc)

            self.notice("REAL VS/G-STAGE LOAD/STORE FAULT MATRIX: PASS")
        finally:
            ptg.destroy()

    def _scenarios(self, code_base):
        entries = [code_base + (index + 1) * 0x1000 for index in range(4)]
        handlers = [code_base + (index + 5) * 0x1000 for index in range(4)]
        result_registers = (
            (3, 4, 5, 6, 7, 9),
            (10, 11, 12, 13, 14, 15),
            (16, 17, 18, 19, 20, 21),
            (22, 23, 24, 25, 26, 27),
        )
        return (
            {
                "name": "VS-stage load page fault",
                "stage": "VS",
                "access": "load",
                "gva": VS_LOAD_GVA,
                "gpa": VS_LOAD_GPA,
                "spa": VS_LOAD_SPA,
                "cause": 13,
                "guest_entry": entries[0],
                "handler": handlers[0],
                "result_registers": result_registers[0],
            },
            {
                "name": "VS-stage store page fault",
                "stage": "VS",
                "access": "store",
                "gva": VS_STORE_GVA,
                "gpa": VS_STORE_GPA,
                "spa": VS_STORE_SPA,
                "cause": 15,
                "guest_entry": entries[1],
                "handler": handlers[1],
                "result_registers": result_registers[1],
            },
            {
                "name": "G-stage load guest-page-fault",
                "stage": "G",
                "access": "load",
                "gva": G_LOAD_GVA,
                "gpa": G_LOAD_GPA,
                "spa": G_LOAD_SPA,
                "cause": 21,
                "guest_entry": entries[2],
                "handler": handlers[2],
                "result_registers": result_registers[2],
            },
            {
                "name": "G-stage store guest-page-fault",
                "stage": "G",
                "access": "store",
                "gva": G_STORE_GVA,
                "gpa": G_STORE_GPA,
                "spa": G_STORE_SPA,
                "cause": 23,
                "guest_entry": entries[3],
                "handler": handlers[3],
                "result_registers": result_registers[3],
            },
        )

    def _prepare_context(self, ptg, scenarios):
        ctx = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Sv39x4",
            asid=0x42,
            vmid=0x22,
            gpa_base=0x96000000,
            gpa_limit=0x97000000,
            pa_base=0x150000000,
            pa_limit=0x160000000,
        )

        for index, scenario in enumerate(scenarios):
            if scenario["access"] == "execute":
                code_gpa = scenario["gpa"]
                code_spa = scenario["spa"]
            else:
                ptg.handle.add_mapping(
                    ctx,
                    "VS",
                    scenario["gva"],
                    scenario["gpa"],
                    0x1000,
                    0,
                    VS_DATA_RW_AD,
                )
                ptg.handle.add_mapping(
                    ctx,
                    "G",
                    scenario["gpa"],
                    scenario["spa"],
                    0x1000,
                    0,
                    G_RWX_UAD,
                )
                code_gpa = 0x86000000 + index * 0x1000
                code_spa = scenario["guest_entry"]
            ptg.handle.add_mapping(
                ctx,
                "VS",
                scenario["guest_entry"],
                code_gpa,
                0x1000,
                0,
                VS_CODE_X_AD,
            )
            ptg.handle.add_mapping(
                ctx,
                "G",
                code_gpa,
                code_spa,
                0x1000,
                0,
                G_RWX_UAD,
            )

        validation = ptg.validate(ctx)
        if not validation.all_ok:
            self.error("Fault matrix PTG page tables failed clean-state validation")

        for scenario in scenarios:
            scenario["v2_result"] = self._inject_v2_fault(ptg, ctx, scenario)

        ptg.load_to_force(ctx, "VS", self.genThread)
        ptg.load_to_force(ctx, "G", self.genThread)
        return ctx

    def _inject_v2_fault(self, ptg, ctx, scenario):
        request = ptg.create_fault_request_v2()
        request.stage = PTG_STAGE_VS if scenario["stage"] == "VS" else PTG_STAGE_G
        request.scope = PTG_FAULT_SCOPE_DIRECT
        request.address_kind = PTG_FAULT_ADDRESS_STAGE_NATIVE
        request.selection_mode = PTG_FAULT_SELECTION_EXACT_ONE
        request.fault_cause = 1
        request.access_type = {
            "load": PTG_FAULT_ACCESS_READ,
            "store": PTG_FAULT_ACCESS_WRITE,
        }[scenario["access"]]
        request.privilege = PTG_FAULT_PRIV_VS
        request.verification_mode = PTG_FAULT_VERIFY_REQUIRE_FAULT
        request.target_level = 0
        request.has_target_address = 1
        request.target_address = (
            scenario["gva"] if scenario["stage"] == "VS" else scenario["gpa"]
        )
        request.dry_run = 1

        before = tuple(sorted(ptg.handle.get_force_blocks(ctx, scenario["stage"])))
        status, dry_results = ptg.inject_fault_v2(ctx, request)
        if status != PTG_FAULT_OK or len(dry_results) != 1:
            self.error(
                f"{scenario['name']} V2 dry-run failed: status={status}, "
                f"results={len(dry_results)}"
            )
        if tuple(sorted(ptg.handle.get_force_blocks(ctx, scenario["stage"]))) != before:
            self.error(f"{scenario['name']} V2 dry-run changed page-table bytes")

        dry_result = dry_results[0]
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
        target = request.target_address
        if (
            dry_result.status != PTG_FAULT_OK
            or dry_result.stage != request.stage
            or dry_result.scope != request.scope
            or dry_result.requested_cause != 1
            or dry_result.actual_cause != 1
            or dry_result.requested_level != 0
            or dry_result.resolved_level != 0
            or dry_result.requested_address != target
            or dry_result.resolved_address != target
            or (dry_result.valid_fields & required_fields) != required_fields
            or dry_result.expected_mcause != scenario["cause"]
            or dry_result.actual_mcause != scenario["cause"]
            or (dry_result.old_pte & 1) == 0
            or (dry_result.new_pte & 1) != 0
        ):
            self.error(f"{scenario['name']} V2 dry-run result metadata mismatch")
        if scenario["stage"] == "G" and dry_result.failing_gpa != scenario["gpa"]:
            self.error(
                f"{scenario['name']} failing GPA mismatch: "
                f"0x{dry_result.failing_gpa:X} != 0x{scenario['gpa']:X}"
            )

        request.dry_run = 0
        status, commit_results = ptg.inject_fault_v2(ctx, request)
        if status != PTG_FAULT_OK or len(commit_results) != 1:
            self.error(
                f"{scenario['name']} V2 commit failed: status={status}, "
                f"results={len(commit_results)}"
            )
        commit_result = commit_results[0]
        if bytes(commit_result) != bytes(dry_result):
            self.error(f"{scenario['name']} V2 dry-run and commit records differ")
        after = tuple(sorted(ptg.handle.get_force_blocks(ctx, scenario["stage"])))
        if after == before or not self._blocks_contain_pte(
            after, commit_result.new_pte
        ):
            self.error(f"{scenario['name']} committed PTE is absent from PTG output")

        self.notice(
            f"V2_RESULT name={scenario['name']} pte_pa=0x{commit_result.pte_pa:X} "
            f"old=0x{commit_result.old_pte:X} new=0x{commit_result.new_pte:X} "
            f"mcause={commit_result.actual_mcause} failing_gpa="
            f"0x{commit_result.failing_gpa:X}"
        )
        return commit_result

    def _blocks_contain_pte(self, blocks, pte):
        encoded = int(pte).to_bytes(8, byteorder="little")
        return any(encoded in data for _, data in blocks)

    def _run_fault_matrix(self, ptg, ctx, scenarios):
        block_id = self.beginLinearBlock()
        self.genThread.setupPtgCSRs(
            ptg_handle=ptg.handle,
            ctx_id=ctx,
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
            self._load_gpr(1, scenario["gva"])
            if scenario["access"] == "store":
                self._load_gpr(2, 0xDEADBEEF01234567)
            fault_pcs.append(self.getPEstate("PC"))
            if scenario["access"] == "load":
                self.genInstruction(
                    "LD##RISCV",
                    {"rd": 2, "rs1": 1, "simm12": 0, "NoRestriction": 1},
                )
            else:
                self.genInstruction(
                    "SD##RISCV",
                    {"rs1": 1, "rs2": 2, "simm12": 0, "NoRestriction": 1},
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
        csrs = (
            CSR_MCAUSE,
            CSR_MEPC,
            CSR_MTVAL,
            CSR_MTVAL2,
            CSR_MTINST,
            CSR_MSTATUS,
        )
        for csr, register_index in zip(csrs, registers):
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
