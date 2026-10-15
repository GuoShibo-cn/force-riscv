"""Require independent ELF execution to reproduce the asserted generation scenario.

The generation trace is a reference from templates with architectural assertions;
matching it does not provide a second independent ISA implementation.
"""

import hashlib
from pathlib import Path
import struct

from run_hypervisor_m1 import parse_trace, require


def audit_replay(generation, replay, entry=None, require_traps=True):
    expected, _ = parse_trace(generation)
    actual, _ = parse_trace(replay)
    require(all("pc" in b for b in expected + actual), "replay audit requires trace v2")
    if entry is not None:
        require(actual[0]["pc"] == entry, "replay does not start at ELF entry")
    starts = [i for i, b in enumerate(actual) if b["pc"] == expected[0]["pc"]]
    require(len(starts) == 1, "scenario entry missing or repeated in ELF execution")
    start = starts[0]
    require(start > 0, "missing ELF startup before the generated scenario")
    require(not any(b["exceptions"] for b in actual[:start]), "unexpected trap during ELF startup")
    scenario = actual[start:]
    require(len(scenario) == len(expected), "scenario truncated or contains unexpected steps")
    trap_count = 0
    for ref, observed in zip(expected, scenario):
        where = f"scenario PC {ref['pc']:#x}"
        for key in ("pc", "post_pc", "opcode", "traps", "memory"):
            require(ref[key] == observed[key], f"{where}: replay {key} mismatch")
        if ref["traps"]:
            require(ref["writes"] == observed["writes"], f"{where}: fault register side effects")
        values = dict(observed["before"], **observed["writes"])
        for reg, value in ref["writes"].items():
            require(values.get(reg) == value, f"{where}: replay {reg} mismatch")
        trap_count += len(ref["traps"])
    if require_traps:
        require(trap_count > 0, "fault scenario has no actual trap events")
    else:
        require(trap_count == 0, "unexpected trap in successful-access scenario")
    require(
        scenario[-1]["pc"] == scenario[-1]["post_pc"] and not scenario[-1]["exceptions"],
        "missing non-trapping terminal self-loop",
    )
    return {"startup_steps": start, "scenario_steps": len(scenario), "traps": trap_count}


def audit_case(directory, require_traps=True):
    directory = Path(directory)
    generated = directory / "sim.log"
    replayed = directory / "fpix_sim.log"
    elfs = list(directory.glob("*.Default.ELF"))
    require(len(elfs) == 1, "expected exactly one ELF per task")
    image = elfs[0].read_bytes()
    require(len(image) >= 64 and image[:6] == b"\x7fELF\x02\x01", "expected ELF64 little endian")
    require(struct.unpack_from("<H", image, 18)[0] == 243, "expected RISC-V ELF")
    entry = struct.unpack_from("<Q", image, 24)[0]
    result = audit_replay(generated.read_text(), replayed.read_text(), entry, require_traps)
    result["files"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (generated, replayed, elfs[0])
    }
    result["directory"] = str(directory)
    return result
