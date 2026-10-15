"""Validate PTG V2 causes 2-9 across Sv39 privilege, access, and target level."""

import ctypes

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
    PTG_FAULT_PRIV_U,
    PTG_FAULT_PRIV_VS,
    PTG_FAULT_PRIV_VU,
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
    PTG_FAULT_VERIFY_MUTATION_ONLY,
    PTG_FAULT_VERIFY_REQUIRE_FAULT,
    PTG_STAGE_G,
    PTG_STAGE_S,
    PTG_STAGE_VS,
    PtgBackend,
)


PTE_R = 1 << 1
PTE_W = 1 << 2
PTE_X = 1 << 3
PTE_U = 1 << 4
PTE_A = 1 << 6
PTE_D = 1 << 7
PTE_PBMT_MASK = 0x3 << 61
PTE_N = 1 << 63
PTE_RESERVED_SV39 = 0x3FC0000000000000

S_DATA_RW_AD = 0x63
S_DATA_RWX_AD = 0x67
S_DATA_RWX = 0x07
S_CODE_X_AD = 0x64
G_RWX_UAD = 0x77

MSTATUS_MPP = 0x1800
MSTATUS_MPP_S = 0x800
MSTATUS_MPRV = 1 << 17
MSTATUS_SUM = 1 << 18
MSTATUS_MXR = 1 << 19
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
CSR_SSTATUS = 0x100
CSR_SEPC = 0x141
CSR_VSSTATUS = 0x200
CSR_HSTATUS = 0x600
CSR_HEDELEG = 0x602

HSTATUS_VTSR = 1 << 22
SSTATUS_SPP = 1 << 8

VALID_LEVELS = {
    2: (0, 1, 2),
    3: (0, 1, 2),
    4: (1, 2),
    5: (0, 1, 2),
    6: (0, 1, 2),
    7: (1, 2),
    8: (0, 1, 2),
    9: (0,),
}

ACCESS_CASES = {
    PTG_FAULT_ACCESS_EXECUTE: ("execute", 12),
    PTG_FAULT_ACCESS_READ: ("load", 13),
    PTG_FAULT_ACCESS_WRITE: ("store", 15),
}

STAGE_NAMES = {
    PTG_STAGE_S: "S",
    PTG_STAGE_VS: "VS",
    PTG_STAGE_G: "G",
}

PRIVILEGE_CASES = {
    PTG_FAULT_PRIV_S: (
        "S",
        "S",
        PTG_STAGE_S,
        MSTATUS_MPP_S,
        MSTATUS_MPP_S,
        0,
        0,
    ),
    PTG_FAULT_PRIV_U: ("U", "S", PTG_STAGE_S, 0, 0, 0, 0),
    PTG_FAULT_PRIV_VS: (
        "VS",
        "VS",
        PTG_STAGE_VS,
        MSTATUS_MPP_S,
        MSTATUS_MPP_S,
        MSTATUS_MPV,
        MSTATUS_GVA,
    ),
    PTG_FAULT_PRIV_VU: (
        "VU",
        "VS",
        PTG_STAGE_VS,
        0,
        MSTATUS_MPP_S,
        MSTATUS_MPV,
        MSTATUS_GVA,
    ),
}


class MainSequence(Sequence):
    def generate(self, **kargs):
        cause = self._required_int_option("FaultCause")
        level = self._required_int_option("FaultLevel")
        access_type = self._required_int_option("FaultAccess")
        privilege = self._required_int_option("FaultPrivilege")
        stage_id = self._required_int_option("FaultStage")
        if cause not in VALID_LEVELS or level not in VALID_LEVELS[cause]:
            self.error(
                f"Unsupported cause/level test case: cause={cause}, level={level}"
            )
        if access_type not in ACCESS_CASES:
            self.error(f"Unsupported access type: {access_type}")
        if privilege not in PRIVILEGE_CASES:
            self.error(f"Unsupported privilege: {privilege}")
        if stage_id not in STAGE_NAMES:
            self.error(f"Unsupported stage: {stage_id}")

        code_base = (self.getPEstate("PC") + 0xFFF) & ~0xFFF
        scenario = self._scenario(
            cause, level, access_type, privilege, stage_id, code_base
        )
        ptg = PtgBackend()
        try:
            context = self._prepare_context(ptg, scenario)
            fault_pc = self._run_fault(ptg, context, scenario)
            self._assert_fault(scenario, fault_pc)
            self.notice(
                f"REAL V2 SV39 CAUSE/LEVEL: PASS cause={cause} level={level} "
                f"access={scenario['access']}"
            )
        finally:
            ptg.destroy()

    def _required_int_option(self, name):
        value, valid = self.getOption(name)
        if not valid:
            self.error(f"Required option '{name}' was not specified")
        return int(value)

    def _scenario(self, cause, level, access_type, privilege, stage_id, code_base):
        leaf_level = 0 if cause in (2, 7) else level
        page_size = 0x1000 << (9 * leaf_level)
        access, mcause = ACCESS_CASES[access_type]
        privilege_name, _, default_stage_id, mpp, entry_mpp, mpv, gva = PRIVILEGE_CASES[
            privilege
        ]
        if stage_id != default_stage_id and not (
            stage_id == PTG_STAGE_G and privilege == PTG_FAULT_PRIV_VS
        ):
            self.error(
                f"Unsupported stage/privilege pair: stage={stage_id}, privilege={privilege}"
            )
        stage = STAGE_NAMES[stage_id]
        if stage_id == PTG_STAGE_G:
            privilege_name = "G-VS"
            mcause += 8
        target_va = 0x1000000000
        return {
            "name": f"Sv39 {privilege_name}-mode cause {cause} level {level} {access}",
            "cause": cause,
            "level": level,
            "access": access,
            "access_type": access_type,
            "privilege": privilege,
            "privilege_name": privilege_name,
            "stage": stage,
            "stage_id": stage_id,
            "mpp": mpp,
            "entry_mpp": entry_mpp,
            "mpv": mpv,
            "gva": gva,
            "mcause": mcause,
            "leaf_level": leaf_level,
            "page_size": page_size,
            "va": target_va,
            "pa": 0x200000000,
            "spa": target_va if access == "execute" else 0x300000000,
            "entry": target_va if access == "execute" else code_base + 0x1000,
            "handler": code_base + 0x2000,
            "trampoline": code_base + 0x3000,
            "perm": self._mapping_permissions(
                cause, level, access_type, privilege, stage_id
            ),
            "adue": 0 if cause == 3 else 1,
            "verification": (
                PTG_FAULT_VERIFY_MUTATION_ONLY
                if cause == 2
                else PTG_FAULT_VERIFY_REQUIRE_FAULT
            ),
            "ptg_actual_cause": self._ptg_actual_cause(cause, level, stage_id),
            "fault_address": 0x200000000 if stage_id == PTG_STAGE_G else target_va,
        }

    def _mapping_permissions(self, cause, level, access_type, privilege, stage_id):
        if cause == 9 or (cause == 8 and level == 0):
            permissions = S_DATA_RWX
        elif cause == 6 or access_type == PTG_FAULT_ACCESS_EXECUTE:
            permissions = S_DATA_RWX_AD
        else:
            permissions = S_DATA_RW_AD
        if stage_id == PTG_STAGE_G or privilege in (
            PTG_FAULT_PRIV_U,
            PTG_FAULT_PRIV_VU,
        ):
            permissions |= PTE_U
        return permissions

    def _ptg_actual_cause(self, cause, level, stage_id):
        if cause == 7:
            return 5 if stage_id == PTG_STAGE_G else 4
        if cause == 8:
            return 9 if level == 0 else 2
        return cause

    def _prepare_context(self, ptg, scenario):
        if scenario["stage"] == "S":
            context = ptg.create_s_stage_context(
                sv_mode="Sv39",
                asid=0x47,
                pa_base=0x1B0000000,
                pa_limit=0x1C0000000,
            )
        else:
            context = ptg.create_two_stage_context(
                vs_mode="Sv39",
                gs_mode="Sv39x4",
                asid=0x48,
                vmid=0x28,
                gpa_base=0x98000000,
                gpa_limit=0x99000000,
                pa_base=0x1D0000000,
                pa_limit=0x1E0000000,
            )
        vm_config = ptg.create_vm_config_v2(
            target="G" if scenario["stage"] == "G" else "S_VS",
            adue=scenario["adue"],
        )
        if ptg.set_vm_config_v2(context, vm_config) != PTG_FAULT_OK:
            self.error(f"{scenario['name']} failed to set V2 VM configuration")

        if scenario["stage"] == "S":
            ptg.handle.add_mapping(
                context,
                "S",
                scenario["va"],
                scenario["pa"],
                scenario["page_size"],
                scenario["leaf_level"],
                scenario["perm"],
            )
        else:
            ptg.handle.add_mapping(
                context,
                "VS",
                scenario["va"],
                scenario["pa"],
                scenario["page_size"],
                scenario["leaf_level"],
                scenario["perm"] if scenario["stage"] == "VS" else S_DATA_RWX_AD,
            )
            ptg.handle.add_mapping(
                context,
                "G",
                scenario["pa"],
                scenario["spa"],
                scenario["page_size"],
                scenario["leaf_level"],
                scenario["perm"] if scenario["stage"] == "G" else G_RWX_UAD,
            )
        if scenario["access"] != "execute":
            if scenario["stage"] == "S":
                ptg.handle.add_mapping(
                    context,
                    "S",
                    scenario["entry"],
                    scenario["entry"],
                    0x1000,
                    0,
                    S_CODE_X_AD
                    | (
                        PTE_U
                        if scenario["privilege"]
                        in (PTG_FAULT_PRIV_U, PTG_FAULT_PRIV_VU)
                        else 0
                    ),
                )
            else:
                entry_gpa = 0x88000000
                ptg.handle.add_mapping(
                    context,
                    "VS",
                    scenario["entry"],
                    entry_gpa,
                    0x1000,
                    0,
                    S_CODE_X_AD
                    | (PTE_U if scenario["privilege"] == PTG_FAULT_PRIV_VU else 0),
                )
                ptg.handle.add_mapping(
                    context,
                    "G",
                    entry_gpa,
                    scenario["entry"],
                    0x1000,
                    0,
                    G_RWX_UAD,
                )
        if scenario["privilege"] == PTG_FAULT_PRIV_VU:
            trampoline_gpa = 0x88001000
            ptg.handle.add_mapping(
                context,
                "VS",
                scenario["trampoline"],
                trampoline_gpa,
                0x1000,
                0,
                S_CODE_X_AD,
            )
            ptg.handle.add_mapping(
                context,
                "G",
                trampoline_gpa,
                scenario["trampoline"],
                0x1000,
                0,
                G_RWX_UAD,
            )
        if not ptg.validate(context).all_ok:
            self.error(f"{scenario['name']} clean page tables failed validation")

        scenario["v2_result"] = self._inject_v2_fault(ptg, context, scenario)
        if scenario["stage"] == "S":
            ptg.load_to_force(context, "S", self.genThread)
        else:
            ptg.load_to_force(context, "VS", self.genThread)
            ptg.load_to_force(context, "G", self.genThread)
        return context

    def _inject_v2_fault(self, ptg, context, scenario):
        request = ptg.create_fault_request_v2()
        request.stage = scenario["stage_id"]
        request.scope = PTG_FAULT_SCOPE_DIRECT
        request.address_kind = PTG_FAULT_ADDRESS_STAGE_NATIVE
        request.selection_mode = PTG_FAULT_SELECTION_EXACT_ONE
        request.fault_cause = scenario["cause"]
        request.access_type = scenario["access_type"]
        request.privilege = scenario["privilege"]
        request.verification_mode = scenario["verification"]
        request.target_level = scenario["level"]
        request.has_target_address = 1
        request.target_address = scenario["fault_address"]
        request.dry_run = 1

        before = self._raw_blocks(ptg, context, scenario["stage"])
        other_stage = (
            "G"
            if scenario["stage"] == "VS"
            else "VS"
            if scenario["stage"] == "G"
            else None
        )
        before_other = (
            self._raw_blocks(ptg, context, other_stage)
            if other_stage is not None
            else ()
        )
        status, dry_results = ptg.inject_fault_v2(context, request)
        if status != PTG_FAULT_OK or len(dry_results) != 1:
            self.error(
                f"{scenario['name']} dry-run failed: status={status}, "
                f"results={len(dry_results)}"
            )
        if self._raw_blocks(ptg, context, scenario["stage"]) != before:
            self.error(f"{scenario['name']} dry-run changed page-table bytes")
        if (
            other_stage is not None
            and self._raw_blocks(ptg, context, other_stage) != before_other
        ):
            self.error(f"{scenario['name']} dry-run changed {other_stage}-stage bytes")

        result = dry_results[0]
        required_fields = (
            PTG_FAULT_VALID_REQUESTED_ADDRESS
            | PTG_FAULT_VALID_RESOLVED_ADDRESS
            | PTG_FAULT_VALID_PTE_PA
            | PTG_FAULT_VALID_OLD_PTE
            | PTG_FAULT_VALID_NEW_PTE
        )
        if scenario["verification"] == PTG_FAULT_VERIFY_REQUIRE_FAULT:
            required_fields |= (
                PTG_FAULT_VALID_EXPECTED_MCAUSE | PTG_FAULT_VALID_ACTUAL_MCAUSE
            )
        if scenario["stage"] == "G":
            required_fields |= PTG_FAULT_VALID_FAILING_GPA

        if (
            result.status != PTG_FAULT_OK
            or result.stage != scenario["stage_id"]
            or result.scope != PTG_FAULT_SCOPE_DIRECT
            or result.requested_cause != scenario["cause"]
            or result.actual_cause != scenario["ptg_actual_cause"]
            or result.requested_level != scenario["level"]
            or result.resolved_level != scenario["level"]
            or result.requested_address != scenario["fault_address"]
            or result.resolved_address != scenario["fault_address"]
            or (result.valid_fields & required_fields) != required_fields
        ):
            self.error(f"{scenario['name']} dry-run result metadata mismatch")
        if scenario["stage"] == "G" and result.failing_gpa != scenario["pa"]:
            self.error(f"{scenario['name']} failing GPA mismatch")
        if scenario["verification"] == PTG_FAULT_VERIFY_REQUIRE_FAULT and (
            result.expected_mcause != scenario["mcause"]
            or result.actual_mcause != scenario["mcause"]
        ):
            self.error(f"{scenario['name']} PTG mcause oracle mismatch")

        expected_pte = self._expected_pte(scenario, result.old_pte)
        if result.new_pte != expected_pte or result.new_pte == result.old_pte:
            self.error(
                f"{scenario['name']} mutation mismatch: old=0x{result.old_pte:016X}, "
                f"new=0x{result.new_pte:016X}, expected=0x{expected_pte:016X}"
            )
        self._assert_fault_preconditions(scenario, result.new_pte)
        if self._pte_at(before, result.pte_pa) != result.old_pte:
            self.error(f"{scenario['name']} old PTE does not match pte_pa")

        request.dry_run = 0
        status, commit_results = ptg.inject_fault_v2(context, request)
        if status != PTG_FAULT_OK or len(commit_results) != 1:
            self.error(
                f"{scenario['name']} commit failed: status={status}, "
                f"results={len(commit_results)}"
            )
        committed = commit_results[0]
        if bytes(committed) != bytes(result):
            self.error(f"{scenario['name']} dry-run and commit records differ")

        after = self._raw_blocks(ptg, context, scenario["stage"])
        if self._pte_at(after, committed.pte_pa) != committed.new_pte:
            self.error(f"{scenario['name']} new PTE does not match pte_pa")
        self._assert_only_pte_changed(scenario, before, after, committed.pte_pa)
        if (
            other_stage is not None
            and self._raw_blocks(ptg, context, other_stage) != before_other
        ):
            self.error(f"{scenario['name']} commit changed {other_stage}-stage bytes")
        return committed

    def _expected_pte(self, scenario, old_pte):
        cause = scenario["cause"]
        if cause == 2:
            reserved = PTE_RESERVED_SV39 & ~(PTE_PBMT_MASK | PTE_N)
            for bit_index in range(63, -1, -1):
                bit = 1 << bit_index
                if reserved & bit and not old_pte & bit:
                    return old_pte | bit
        if cause == 3:
            return old_pte & ~(
                PTE_D if scenario["access_type"] == PTG_FAULT_ACCESS_WRITE else PTE_A
            )
        if cause == 4:
            return old_pte | (1 << 10)
        if cause == 5:
            if scenario["stage"] == "G" or scenario["privilege"] in (
                PTG_FAULT_PRIV_U,
                PTG_FAULT_PRIV_VU,
            ):
                return old_pte & ~PTE_U
            return old_pte | PTE_U
        if cause == 6:
            if scenario["access_type"] == PTG_FAULT_ACCESS_READ:
                return old_pte & ~(PTE_R | PTE_W)
            if scenario["access_type"] == PTG_FAULT_ACCESS_WRITE:
                return old_pte & ~PTE_W
            return old_pte & ~PTE_X
        if cause == 7:
            return old_pte | PTE_R
        if cause in (8, 9):
            return old_pte & ~(PTE_R | PTE_W | PTE_X)
        self.error(f"No mutation oracle for cause {cause}")

    def _assert_fault_preconditions(self, scenario, new_pte):
        cause = scenario["cause"]
        level = scenario["level"]
        if cause == 2 and not new_pte & (PTE_RESERVED_SV39 & ~(PTE_PBMT_MASK | PTE_N)):
            self.error(f"{scenario['name']} did not set an Sv39 reserved bit")
        if cause == 4 and not new_pte & (1 << 10):
            self.error(f"{scenario['name']} superpage PPN remains aligned")
        if cause == 7:
            ppn = (new_pte >> 10) & ((1 << 44) - 1)
            if ppn & ((1 << (9 * level)) - 1) == 0:
                self.error(f"{scenario['name']} terminal pointer is not misaligned")
        if cause == 8 and level > 0 and not new_pte & (PTE_A | PTE_D | PTE_U):
            self.error(f"{scenario['name']} lacks the intended non-leaf reserved bits")
        if cause == 9 or (cause == 8 and level == 0):
            disallowed = PTE_R | PTE_W | PTE_X | PTE_A | PTE_D | PTE_PBMT_MASK | PTE_N
            if scenario["stage"] != "G" and scenario["privilege"] not in (
                PTG_FAULT_PRIV_U,
                PTG_FAULT_PRIV_VU,
            ):
                disallowed |= PTE_U
            if new_pte & disallowed:
                self.error(
                    f"{scenario['name']} level-zero non-leaf has unexpected flag bits"
                )

    def _pte_at(self, blocks, pte_pa):
        matches = []
        for base, data in blocks:
            offset = pte_pa - base
            if 0 <= offset and offset + 8 <= len(data):
                matches.append(int.from_bytes(data[offset : offset + 8], "little"))
        if len(matches) != 1:
            self.error(f"PTE PA 0x{pte_pa:X} matched {len(matches)} page-table blocks")
        return matches[0]

    def _raw_blocks(self, ptg, context, stage):
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

    def _run_fault(self, ptg, context, scenario):
        block_id = self.beginLinearBlock()
        if scenario["stage"] == "S":
            self._write_csr(CSR_SATP, ptg.handle.get_satp(context))
        else:
            self.genThread.setupPtgCSRs(
                ptg_handle=ptg.handle,
                ctx_id=context,
                vs_mode="Sv39",
                g_mode="Sv39x4",
            )
            self._write_csr(CSR_SATP, 0)
            self._write_csr(CSR_HEDELEG, 0)
            self._clear_csr_bits(CSR_VSSTATUS, MSTATUS_SUM | MSTATUS_MXR)
            self._clear_csr_bits(CSR_HSTATUS, HSTATUS_VTSR)
        self._write_csr(CSR_MEDELEG, 0)
        self._write_csr(CSR_MTVEC, scenario["handler"])
        self._write_csr(CSR_MTVAL, 0xCCCCCCCCCCCCCCCC)
        self._write_csr(CSR_MTVAL2, 0x5555555555555555)
        self._write_csr(CSR_MTINST, 0xAAAAAAAAAAAAAAAA)
        self._clear_csr_bits(
            CSR_MSTATUS,
            MSTATUS_MPP | MSTATUS_MPRV | MSTATUS_SUM | MSTATUS_MXR | MSTATUS_MPV,
        )
        if scenario["entry_mpp"]:
            self._set_csr_bits(CSR_MSTATUS, scenario["entry_mpp"])
        if scenario["mpv"]:
            self._set_csr_bits(CSR_MSTATUS, scenario["mpv"])
        mret_entry = (
            scenario["trampoline"]
            if scenario["privilege"] == PTG_FAULT_PRIV_VU
            else scenario["entry"]
        )
        self._write_csr(CSR_MEPC, mret_entry)
        self.genInstruction("MRET##RISCV", {"NoRestriction": 1})

        if scenario["privilege"] == PTG_FAULT_PRIV_VU:
            self.setPEstate("PC", scenario["trampoline"])
            self._write_csr(CSR_SEPC, scenario["entry"])
            self._clear_csr_bits(CSR_SSTATUS, SSTATUS_SPP)
            self.genInstruction("SRET##RISCV", {"NoRestriction": 1})

        self.setPEstate("PC", scenario["entry"])
        if scenario["access"] != "execute":
            self._load_gpr(1, scenario["va"])
        if scenario["access"] == "store":
            self._load_gpr(2, 0xDEADBEEF01234567)
        fault_pc = self.getPEstate("PC")
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
        for csr, register_index in zip(
            (CSR_MCAUSE, CSR_MEPC, CSR_MTVAL, CSR_MTVAL2, CSR_MTINST, CSR_MSTATUS),
            (3, 4, 5, 6, 7, 9),
        ):
            self._read_csr(csr, register_index)
        self.endLinearBlock(block_id)
        return fault_pc

    def _assert_fault(self, scenario, fault_pc):
        self._assert_gpr(3, scenario["mcause"], f"{scenario['name']} mcause")
        self._assert_gpr(4, fault_pc, f"{scenario['name']} mepc")
        self._assert_gpr(5, scenario["va"], f"{scenario['name']} mtval")
        expected_mtval2 = (
            scenario["v2_result"].failing_gpa >> 2 if scenario["stage"] == "G" else 0
        )
        self._assert_gpr(6, expected_mtval2, f"{scenario['name']} mtval2")
        self._assert_gpr(7, 0, f"{scenario['name']} mtinst")

        mstatus, valid = self.readRegister("x9")
        if (
            not valid
            or (mstatus & MSTATUS_MPV) != scenario["mpv"]
            or (mstatus & MSTATUS_GVA) != scenario["gva"]
            or (mstatus & MSTATUS_MPP) != scenario["mpp"]
        ):
            self.error(
                f"{scenario['name']} mstatus failed: mstatus=0x{mstatus:016X}, "
                f"expected MPV={int(bool(scenario['mpv']))}, "
                f"GVA={int(bool(scenario['gva']))}, and "
                f"MPP={scenario['privilege_name']}"
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
