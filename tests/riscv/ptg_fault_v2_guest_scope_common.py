"""Validate V2 guest-implicit and guest-explicit faults through Handcar."""

import ctypes

from base.Sequence import Sequence
from riscv.Utils import LoadGPR64
from riscv.paging.PtgBackend import (
    PTG_FAULT_ACCESS_EXECUTE,
    PTG_FAULT_ACCESS_READ,
    PTG_FAULT_ACCESS_WRITE,
    PTG_FAULT_ADDRESS_GPA,
    PTG_FAULT_ADDRESS_GVA,
    PTG_FAULT_OK,
    PTG_FAULT_PRIV_VS,
    PTG_FAULT_SCOPE_GUEST_EXPLICIT,
    PTG_FAULT_SCOPE_GUEST_IMPLICIT,
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
    PtgBackend,
    PtgPlacement,
)


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

IMPLICIT_SCOPE_SPEC = {
    "name": "guest-implicit",
    "scope": PTG_FAULT_SCOPE_GUEST_IMPLICIT,
    "gva_base": 0x43000000,
    "gpa_base": 0x86400000,
    "pt_gpa_base": 0x98000000,
    "isolated_pt_gpa_base": 0x400000000,
    "pt_pa_base": 0x170000000,
    "asid": 0x44,
    "vmid": 0x24,
}

EXPLICIT_SCOPE_SPEC = {
    "name": "guest-explicit",
    "scope": PTG_FAULT_SCOPE_GUEST_EXPLICIT,
    "gva_base": 0x44000000,
    "gpa_base": 0x86A00000,
    "pt_gpa_base": 0x2000000000,
    "pt_pa_base": 0x180000000,
    "asid": 0x45,
    "vmid": 0x25,
}


class GuestScopeSequence(Sequence):
    scope_spec = None
    implicit_matrix_case = None
    explicit_address_kind = PTG_FAULT_ADDRESS_GVA
    explicit_g_target_level = 0

    def generate(self, **kargs):
        code_base = (self.getPEstate("PC") + 0xFFF) & ~0xFFF
        if self.scope_spec is None:
            self.error("Guest scope sequence requires a scope specification")
        self._run_scope(code_base, self.scope_spec)
        self.notice(f"REAL V2 {self.scope_spec['name'].upper()} FAULT MATRIX: PASS")

    def _run_scope(self, code_base, scope_spec):
        scenarios = self._scenarios(code_base, scope_spec)
        ptg = PtgBackend()
        try:
            context = self._prepare_context(ptg, scenarios, scope_spec)
            fault_pcs = self._run_matrix(ptg, context, scenarios)
            for scenario, fault_pc in zip(scenarios, fault_pcs):
                self._assert_fault(scenario, fault_pc)
        finally:
            ptg.destroy()

    def _scenarios(self, code_base, scope_spec):
        entries = (code_base + 0x1000, code_base + 0x2000, code_base + 0x201000)
        handlers = (code_base + 0x3000, code_base + 0x4000, code_base + 0x202000)
        scope_name = scope_spec["name"]
        scope = scope_spec["scope"]
        accesses = (
            ("load", PTG_FAULT_ACCESS_READ, 21),
            ("store", PTG_FAULT_ACCESS_WRITE, 23),
            ("execute", PTG_FAULT_ACCESS_EXECUTE, 20),
        )
        registers = (
            (3, 4, 5, 6, 7, 9),
            (10, 11, 12, 13, 14, 15),
            (16, 17, 18, 19, 20, 21),
        )
        scenarios = []
        for index, (access, access_type, cause) in enumerate(accesses):
            gva = (
                entries[index]
                if access == "execute"
                else scope_spec["gva_base"] + index * 0x400000
            )
            scenarios.append(
                {
                    "name": f"{scope_name} {access} guest-page-fault",
                    "scope": scope,
                    "access": access,
                    "access_type": access_type,
                    "cause": cause,
                    "gva": gva,
                    "gpa": scope_spec["gpa_base"] + index * 0x200000,
                    "spa": scope_spec["pt_pa_base"] + 0x1000000 + index * 0x200000,
                    "guest_entry": entries[index],
                    "handler": handlers[index],
                    "result_registers": registers[index],
                }
            )
        if self.implicit_matrix_case is not None:
            vs_walk_level, g_target_level, selected_access = self.implicit_matrix_case
            if vs_walk_level not in (0, 1, 2) or g_target_level not in (0, 1, 2):
                self.error(
                    "Guest-implicit VS walk and G target levels must be 0, 1, or 2"
                )
            if selected_access not in (
                PTG_FAULT_ACCESS_READ,
                PTG_FAULT_ACCESS_WRITE,
                PTG_FAULT_ACCESS_EXECUTE,
            ):
                self.error(f"Unsupported guest-implicit access: {selected_access}")
            if vs_walk_level == 2 and selected_access != PTG_FAULT_ACCESS_EXECUTE:
                self.error(
                    "VS root guest-implicit load/store is shadowed by the earlier "
                    "guest instruction-fetch walk"
                )
            scenarios = [
                scenario
                for scenario in scenarios
                if scenario["access_type"] == selected_access
            ]
        else:
            vs_walk_level = 0
            g_target_level = (
                self.explicit_g_target_level
                if scope == PTG_FAULT_SCOPE_GUEST_EXPLICIT
                else 0
            )
        if scope == PTG_FAULT_SCOPE_GUEST_EXPLICIT and g_target_level not in (0, 1, 2):
            self.error("Guest-explicit G target level must be 0, 1, or 2")
        if (
            scope == PTG_FAULT_SCOPE_GUEST_EXPLICIT
            and self.explicit_address_kind
            not in (
                PTG_FAULT_ADDRESS_GVA,
                PTG_FAULT_ADDRESS_GPA,
            )
        ):
            self.error(
                f"Unsupported guest-explicit address kind: {self.explicit_address_kind}"
            )
        for index, scenario in enumerate(scenarios):
            if scope == PTG_FAULT_SCOPE_GUEST_EXPLICIT and g_target_level == 2:
                scenario["gpa"] = scope_spec["gpa_base"] + index * 0x40000000
            scenario["vs_walk_level"] = vs_walk_level
            scenario["g_target_level"] = g_target_level
            scenario["address_kind"] = (
                self.explicit_address_kind
                if scope == PTG_FAULT_SCOPE_GUEST_EXPLICIT
                else PTG_FAULT_ADDRESS_GVA
            )
            if scope == PTG_FAULT_SCOPE_GUEST_EXPLICIT:
                address_name = (
                    "gva"
                    if scenario["address_kind"] == PTG_FAULT_ADDRESS_GVA
                    else "gpa"
                )
                scenario["name"] = (
                    f"{scope_name} {address_name} {scenario['access']} guest-page-fault"
                )
        return tuple(scenarios)

    def _prepare_context(self, ptg, scenarios, scope_spec):
        isolated_implicit = (
            scope_spec["scope"] == PTG_FAULT_SCOPE_GUEST_IMPLICIT
            and self.implicit_matrix_case is not None
        )
        gpa_base = (
            scope_spec["isolated_pt_gpa_base"]
            if isolated_implicit
            else scope_spec["pt_gpa_base"]
        )
        context = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Sv39x4",
            asid=scope_spec["asid"],
            vmid=scope_spec["vmid"],
            gpa_base=gpa_base,
            gpa_limit=gpa_base + (0x1000 if isolated_implicit else 0x1000000),
            pa_base=scope_spec["pt_pa_base"],
            pa_limit=scope_spec["pt_pa_base"] + 0x10000000,
            pa_placement=PtgPlacement(levels=((
                2, scope_spec["pt_pa_base"] + 0x10000, scope_spec["pt_pa_base"] + 0x14000
            ),)),
            gpa_placement=PtgPlacement(levels=((2, gpa_base, gpa_base + 0x1000),)),
        )
        mask = (1 << 44) - 1
        if ((ptg.handle.get_hgatp(context) & mask) << 12 != scope_spec["pt_pa_base"] + 0x10000
                or (ptg.handle.get_vsatp(context) & mask) << 12 != gpa_base):
            self.error("Guest-scope placement root window mismatch")
        if isolated_implicit:
            for index in range(1, 5):
                node_base = gpa_base + index * 0x40000000
                ptg.handle.register_gpa_region(
                    scope_spec["vmid"], node_base, node_base + 0x1000
                )
        for index, scenario in enumerate(scenarios):
            if scenario["access"] != "execute":
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
                code_gpa = (
                    scope_spec["gpa_base"] + 0x1000000000 + index * 0x1000
                    if scenario["scope"] == PTG_FAULT_SCOPE_GUEST_EXPLICIT
                    and scenario["g_target_level"] == 2
                    else scope_spec["gpa_base"] + 0x1000000 + index * 0x1000
                )
            else:
                code_gpa = scenario["gpa"]

            ptg.handle.add_mapping(
                context,
                "VS",
                scenario["guest_entry"],
                code_gpa,
                0x1000,
                0,
                VS_CODE_X_AD,
            )
            ptg.handle.add_mapping(
                context,
                "G",
                code_gpa,
                scenario["guest_entry"],
                0x1000,
                0,
                G_RWX_UAD,
            )

        if not ptg.validate(context).all_ok:
            self.error(
                f"{scope_spec['name']} page tables failed clean-state validation"
            )

        # Capture while G backing is healthy. Guest-implicit faults make later capture invalid.
        with ptg.capture_export_layout(context, "VS") as vs_layout:
            with ptg.capture_export_layout(context, "G") as g_layout:
                for scenario in scenarios:
                    scenario["v2_result"] = self._inject_v2_fault(ptg, context, scenario)
                ptg.load_export_layouts((vs_layout, g_layout), self.genThread)
        self.notice("PTG STRICT EXPORT V1: frozen guest-fault VS/G snapshots loaded")
        return context

    def _inject_v2_fault(self, ptg, context, scenario):
        request = self._fault_request(ptg, scenario, scenario["address_kind"])

        before_vs = self._raw_blocks(ptg, context, "VS")
        before_g = self._raw_blocks(ptg, context, "G")
        expected_failing_gpa = None
        if scenario["scope"] == PTG_FAULT_SCOPE_GUEST_IMPLICIT:
            expected_failing_gpa = self._walk_pte_pa(
                before_vs,
                (ptg.handle.get_vsatp(context) & ((1 << 44) - 1)) << 12,
                scenario["gva"],
                scenario["vs_walk_level"],
                9,
            )
        expected_pte_pa = self._walk_pte_pa(
            before_g,
            (ptg.handle.get_hgatp(context) & ((1 << 44) - 1)) << 12,
            expected_failing_gpa
            if expected_failing_gpa is not None
            else scenario["gpa"],
            scenario["g_target_level"],
            11,
        )
        status, dry_results = ptg.inject_fault_v2(context, request)
        if status != PTG_FAULT_OK or len(dry_results) != 1:
            self.error(
                f"{scenario['name']} V2 dry-run failed: status={status}, "
                f"results={len(dry_results)}"
            )
        if (
            self._raw_blocks(ptg, context, "VS") != before_vs
            or self._raw_blocks(ptg, context, "G") != before_g
        ):
            self.error(f"{scenario['name']} V2 dry-run changed page-table bytes")

        result = dry_results[0]
        if scenario["scope"] == PTG_FAULT_SCOPE_GUEST_EXPLICIT:
            companion_kind = (
                PTG_FAULT_ADDRESS_GPA
                if scenario["address_kind"] == PTG_FAULT_ADDRESS_GVA
                else PTG_FAULT_ADDRESS_GVA
            )
            companion_request = self._fault_request(ptg, scenario, companion_kind)
            companion_status, companion_results = ptg.inject_fault_v2(
                context, companion_request
            )
            if companion_status != PTG_FAULT_OK or len(companion_results) != 1:
                self.error(f"{scenario['name']} companion V2 dry-run failed")
            if (
                self._raw_blocks(ptg, context, "VS") != before_vs
                or self._raw_blocks(ptg, context, "G") != before_g
            ):
                self.error(
                    f"{scenario['name']} companion dry-run changed page-table bytes"
                )
            self._assert_explicit_parity(scenario, result, companion_results[0])

        required_fields = (
            PTG_FAULT_VALID_REQUESTED_ADDRESS
            | PTG_FAULT_VALID_RESOLVED_ADDRESS
            | PTG_FAULT_VALID_FAILING_GPA
            | PTG_FAULT_VALID_PTE_PA
            | PTG_FAULT_VALID_OLD_PTE
            | PTG_FAULT_VALID_NEW_PTE
            | PTG_FAULT_VALID_EXPECTED_MCAUSE
            | PTG_FAULT_VALID_ACTUAL_MCAUSE
        )
        expected_requested = (
            scenario["gpa"]
            if scenario["address_kind"] == PTG_FAULT_ADDRESS_GPA
            else scenario["gva"]
        )
        expected_resolved = (
            scenario["gva"]
            if scenario["scope"] == PTG_FAULT_SCOPE_GUEST_IMPLICIT
            else scenario["gpa"]
        )
        if (
            result.status != PTG_FAULT_OK
            or result.stage != PTG_STAGE_G
            or result.scope != scenario["scope"]
            or result.requested_cause != 1
            or result.actual_cause != 1
            or result.requested_level != scenario["g_target_level"]
            or result.resolved_level != scenario["g_target_level"]
            or result.requested_address != expected_requested
            or result.resolved_address != expected_resolved
            or (result.valid_fields & required_fields) != required_fields
            or result.expected_mcause != scenario["cause"]
            or result.actual_mcause != scenario["cause"]
            or result.pte_pa != expected_pte_pa
            or (result.old_pte & 1) == 0
            or (result.new_pte & 1) != 0
        ):
            self.error(f"{scenario['name']} V2 dry-run result metadata mismatch")
        if scenario["scope"] == PTG_FAULT_SCOPE_GUEST_EXPLICIT:
            if result.failing_gpa != scenario["gpa"]:
                self.error(f"{scenario['name']} explicit failing GPA mismatch")
        elif result.failing_gpa == scenario["gpa"]:
            self.error(f"{scenario['name']} implicit fault resolved to final data GPA")
        elif result.failing_gpa != expected_failing_gpa:
            self.error(f"{scenario['name']} implicit failing GPA mismatch")
        if self._pte_at(before_g, result.pte_pa) != result.old_pte:
            self.error(f"{scenario['name']} old G-stage PTE mismatch")

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

        after_vs = self._raw_blocks(ptg, context, "VS")
        after_g = self._raw_blocks(ptg, context, "G")
        if after_vs != before_vs:
            self.error(f"{scenario['name']} V2 commit unexpectedly changed VS-stage")
        if after_g == before_g:
            self.error(f"{scenario['name']} V2 commit did not change G-stage")
        if self._pte_at(after_g, committed.pte_pa) != committed.new_pte:
            self.error(f"{scenario['name']} new G-stage PTE mismatch")
        self._assert_only_pte_changed(scenario, before_g, after_g, committed.pte_pa)

        self.notice(
            f"V2_GUEST_RESULT name={scenario['name']} pte_pa=0x{committed.pte_pa:X} "
            f"old=0x{committed.old_pte:X} new=0x{committed.new_pte:X} "
            f"mcause={committed.actual_mcause} failing_gpa=0x{committed.failing_gpa:X}"
        )
        return committed

    def _fault_request(self, ptg, scenario, address_kind):
        request = ptg.create_fault_request_v2()
        request.stage = PTG_STAGE_G
        request.scope = scenario["scope"]
        request.address_kind = address_kind
        request.selection_mode = PTG_FAULT_SELECTION_EXACT_ONE
        request.fault_cause = 1
        request.access_type = scenario["access_type"]
        request.privilege = PTG_FAULT_PRIV_VS
        request.verification_mode = PTG_FAULT_VERIFY_REQUIRE_FAULT
        request.target_level = scenario["g_target_level"]
        if scenario["scope"] == PTG_FAULT_SCOPE_GUEST_IMPLICIT:
            request.vs_walk_level = scenario["vs_walk_level"]
        request.has_target_address = 1
        request.target_address = (
            scenario["gpa"]
            if address_kind == PTG_FAULT_ADDRESS_GPA
            else scenario["gva"]
        )
        request.dry_run = 1
        return request

    def _assert_explicit_parity(self, scenario, selected, companion):
        selected_expected = (
            scenario["gpa"]
            if scenario["address_kind"] == PTG_FAULT_ADDRESS_GPA
            else scenario["gva"]
        )
        companion_expected = (
            scenario["gva"]
            if scenario["address_kind"] == PTG_FAULT_ADDRESS_GPA
            else scenario["gpa"]
        )
        if (
            selected.requested_address != selected_expected
            or companion.requested_address != companion_expected
        ):
            self.error(f"{scenario['name']} parity requested-address mismatch")
        for field_name, _ in type(selected)._fields_:
            if field_name != "requested_address" and getattr(
                selected, field_name
            ) != getattr(companion, field_name):
                self.error(
                    f"{scenario['name']} GVA/GPA parity mismatch in {field_name}"
                )
        selected_name = (
            "gpa" if scenario["address_kind"] == PTG_FAULT_ADDRESS_GPA else "gva"
        )
        self.notice(
            f"V2_GUEST_PARITY name={scenario['name']} selected={selected_name} "
            f"resolved=0x{selected.resolved_address:X} pte_pa=0x{selected.pte_pa:X}"
        )

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

    def _pte_at(self, blocks, pte_pa):
        matches = []
        for base, data in blocks:
            offset = pte_pa - base
            if 0 <= offset <= len(data) - 8:
                matches.append(int.from_bytes(data[offset : offset + 8], "little"))
        if len(matches) != 1:
            self.error(f"PTE PA 0x{pte_pa:X} matched {len(matches)} page-table blocks")
        return matches[0]

    def _assert_only_pte_changed(self, scenario, before, after, pte_pa):
        before_by_base = dict(before)
        after_by_base = dict(after)
        if before_by_base.keys() != after_by_base.keys():
            self.error(f"{scenario['name']} changed the G-stage block set")

        changed = []
        for base, old_data in before_by_base.items():
            new_data = after_by_base[base]
            if len(old_data) != len(new_data):
                self.error(f"{scenario['name']} changed a G-stage block size")
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
        self._clear_csr_bits(CSR_HSTATUS, HSTATUS_VTSR)
        self._prepare_mret(scenarios[0])

        fault_pcs = []
        for index, scenario in enumerate(scenarios):
            self.setPEstate("PC", scenario["guest_entry"])
            if scenario["access"] != "execute":
                self._load_gpr(1, scenario["gva"])
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
        self._assert_gpr(
            registers[3],
            scenario["v2_result"].failing_gpa >> 2,
            f"{scenario['name']} mtval2",
        )
        expected_mtinst = (
            0x3000 if scenario["scope"] == PTG_FAULT_SCOPE_GUEST_IMPLICIT else 0
        )
        self._assert_gpr(registers[4], expected_mtinst, f"{scenario['name']} mtinst")

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
