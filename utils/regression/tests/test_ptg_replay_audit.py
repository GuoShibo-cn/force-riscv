"""Replay must reach the asserted scenario; exit status alone is insufficient."""

import unittest

from ptg_replay_audit import audit_replay


def traces():
    header = (
        "# HANDCAR trace v2: PC(VA)=instruction address; "
        "NextPC(VA)=after step; Trap=take_trap event\n"
    )
    def block(index, pc, next_pc, op, extra=""):
        return (
            f"Cpu 0 {index} ----\n"
            f"Cpu 0 PC(VA) 0x{pc:016x} op: 0x{op:016x} : fixture\n"
            f"Cpu 0 NextPC(VA) 0x{next_pc:016x}\n"
            f"Cpu 0 Reg W PC val 0x{next_pc:016x} mask 0xffffffffffffffff\n{extra}"
        )
    trap = (
        "Cpu 0 Trap trap_load_page_fault cause=0xd epc=0x1000 tval=0x4000 "
        "tval2=0x0 tinst=0x0 target=0x2000 from_priv=1 from_v=0 to_priv=3 to_v=0\n"
    )
    def body(offset):
        return (
            block(1 + offset, 0x1000, 0x2000, 0xB103, trap)
            + block(2 + offset, 0x2000, 0x2004, 0x342021F3,
                    "Cpu 0 Reg W x3 val 0x000000000000000d mask 0xffffffffffffffff\n")
            + block(3 + offset, 0x2004, 0x2004, 0x6F)
            + f"Cpu 0 executed {3 + offset} instructions.\n"
            + f"Executed {3 + offset} instructions, exit status (SUCCESS)\n"
        )
    return header + body(0), header + block(1, 0x50000000, 0x1000, 0x67) + body(1)


class ReplayTests(unittest.TestCase):
    def test_successful_access_mode_still_rejects_any_trap(self):
        generated, replay = traces()
        with self.assertRaisesRegex(ValueError, "unexpected trap"):
            audit_replay(generated, replay, require_traps=False)
        generated = "\n".join(s for s in generated.splitlines() if " Trap " not in s) + "\n"
        replay = "\n".join(s for s in replay.splitlines() if " Trap " not in s) + "\n"
        self.assertEqual(audit_replay(generated, replay, require_traps=False)["traps"], 0)
        with self.assertRaisesRegex(ValueError, "no actual trap"):
            audit_replay(generated, replay)

    def test_startup_and_complete_scenario(self):
        result = audit_replay(*traces(), entry=0x50000000)
        self.assertEqual(result, {"startup_steps": 1, "scenario_steps": 3, "traps": 1})

    def test_success_cannot_override_wrong_execution(self):
        generated, replay = traces()
        mutations = (
            replay.replace("cause=0xd", "cause=0x1"),
            replay.replace("epc=0x1000", "epc=0x0"),
            replay.replace("tval2=0x0", "tval2=0x100"),
            replay.replace("val 0x000000000000000d", "val 0x0000000000000001"),
            replay.replace("op: 0x000000000000b103", "op: 0x0000000000000000"),
            replay.replace("Cpu 0 3 ----", "Cpu 0 Reg W x2 val 0x0000000000000001 "
                           "mask 0xffffffffffffffff\nCpu 0 3 ----"),
            "\n".join(line for line in replay.splitlines() if " Trap " not in line) + "\n",
            generated,  # No startup: a copied generation trace is not ELF replay.
        )
        for altered in mutations:
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                audit_replay(generated, altered)

    def test_wrong_elf_entry_and_truncated_log(self):
        generated, replay = traces()
        with self.assertRaisesRegex(ValueError, "ELF entry"):
            audit_replay(generated, replay, entry=0)
        with self.assertRaises(ValueError):
            audit_replay(generated, replay[:-1])

    def test_early_trap_success_footer_is_rejected(self):
        generated, replay = traces()
        startup_trap = (
            "Cpu 0 Trap trap_illegal_instruction cause=0x2 epc=0x50000000 tval=0x0 "
            "tval2=0x0 tinst=0x0 target=0x1000 from_priv=3 from_v=0 to_priv=3 to_v=0\n"
        )
        replay = replay.replace("Cpu 0 2 ----", startup_trap + "Cpu 0 2 ----")
        with self.assertRaisesRegex(ValueError, "startup"):
            audit_replay(generated, replay)
