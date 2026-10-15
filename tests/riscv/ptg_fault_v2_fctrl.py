#
# Copyright (C) [2026] Futurewei Technologies, Inc.
#
# FORCE-RISCV is licensed under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance
#  with the License. You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES
# OF ANY KIND, EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the License for the specific language governing permissions and
# limitations under the License.
#

_generator = {"--cfg": "config/riscv_rv64_twostage.config"}
_options = {"max-instr": 100000, "timeout": 600}


def _cause_level_item(
    cause, level, access, access_name, privilege, privilege_name, stage
):
    privilege_suffix = "" if privilege_name == "s" else "_" + privilege_name
    return {
        "fname": "ptg_fault_v2_sv39_cause_levels_force.py",
        "options": {
            "max-instr": 100000,
            "timeout": 600,
            "suffix": "cause{}_l{}_{}{}".format(
                cause, level, access_name, privilege_suffix
            ),
        },
        "generator": {
            "--cfg": "config/riscv_rv64_twostage.config",
            "--options": (
                '"FaultCause={},FaultLevel={},FaultAccess={},FaultPrivilege={},FaultStage={}"'.format(
                    cause, level, access, privilege, stage
                )
            ),
        },
    }


def _guest_implicit_level_item(vs_level, g_level, access, access_name):
    return {
        "fname": "ptg_fault_v2_guest_scope_trap_force.py",
        "options": {
            "max-instr": 100000,
            "timeout": 600,
            "suffix": "gimpl_v{}_g{}_{}".format(vs_level, g_level, access_name),
        },
        "generator": {
            "--cfg": "config/riscv_rv64_twostage.config",
            "--options": (
                '"GuestVsWalkLevel={},GuestGTargetLevel={},GuestFaultAccess={}"'.format(
                    vs_level, g_level, access
                )
            ),
        },
    }


def _guest_explicit_item(address_kind, address_name, g_level):
    return {
        "fname": "ptg_fault_v2_guest_explicit_trap_force.py",
        "options": {
            "max-instr": 100000,
            "timeout": 600,
            "suffix": "gexp_{}_g{}".format(address_name, g_level),
        },
        "generator": {
            "--cfg": "config/riscv_rv64_twostage.config",
            "--options": (
                '"GuestExplicitAddressKind={},GuestGTargetLevel={}"'.format(
                    address_kind, g_level
                )
            ),
        },
    }


control_items = [
    {
        "fname": "ptg_fault_v2_s_stage_trap_force.py",
        "options": _options,
        "generator": _generator,
    },
    {
        "fname": "ptg_vs_fault_matrix_force.py",
        "options": _options,
        "generator": _generator,
    },
    {
        "fname": "ptg_fault_v2_instruction_trap_force.py",
        "options": _options,
        "generator": _generator,
    },
]

for address_kind, address_name in ((1, "gva"), (2, "gpa")):
    for g_level in range(3):
        control_items.append(_guest_explicit_item(address_kind, address_name, g_level))

for vs_level in range(3):
    for g_level in range(3):
        accesses = (
            ((2, "execute"),)
            if vs_level == 2
            else ((0, "load"), (1, "store"), (2, "execute"))
        )
        for access, access_name in accesses:
            control_items.append(
                _guest_implicit_level_item(vs_level, g_level, access, access_name)
            )

for cause, levels in (
    (2, (0, 1, 2)),
    (3, (0, 1, 2)),
    (4, (1, 2)),
    (5, (0, 1, 2)),
    (6, (0, 1, 2)),
    (7, (1, 2)),
    (8, (0, 1, 2)),
    (9, (0,)),
):
    for level in levels:
        for privilege, privilege_name, stage in (
            (0, "s", 0),
            (1, "u", 0),
            (2, "vs", 1),
            (3, "vu", 1),
            (2, "g_vs", 2),
        ):
            for access, access_name in ((0, "load"), (1, "store"), (2, "execute")):
                control_items.append(
                    _cause_level_item(
                        cause,
                        level,
                        access,
                        access_name,
                        privilege,
                        privilege_name,
                        stage,
                    )
                )
