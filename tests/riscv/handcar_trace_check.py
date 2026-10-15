"""Cross-check instruction PCs/opcodes and actual trap records in v2 traces.

This is a trace-integrity check, not an ELF replay or scenario-semantic oracle.
FORCE can overwrite instructions while generating, so final-image differences
are reported as failures rather than silently interpreted as correct traces.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re


def check(trace_path, assembly_path):
    text = trace_path.read_text()
    lines = text.splitlines()
    if not lines or not lines[0].startswith("# HANDCAR trace v2:"):
        raise ValueError("requires a v2 instruction-PC trace")
    image = {}
    for line in assembly_path.read_text().splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{16}):([0-9a-fA-F]+)\s+.*", line)
        if match:
            image[int(match[1], 16)] = int(match[2], 16)
    if not image:
        raise ValueError("empty assembly image")
    steps, traps, checked, unavailable = [], [], 0, 0
    for line in lines:
        pc = re.fullmatch(r"Cpu 0 PC\(VA\) 0x([0-9a-f]+) op: 0x([0-9a-f]+) : (.+)", line)
        next_pc = re.fullmatch(r"Cpu 0 NextPC\(VA\) 0x([0-9a-f]+)", line)
        trap = re.fullmatch(
            r"Cpu 0 Trap (\S+) cause=0x([0-9a-f]+) epc=0x([0-9a-f]+) "
            r"tval=0x([0-9a-f]+) tval2=0x([0-9a-f]+) tinst=0x([0-9a-f]+) "
            r"target=0x([0-9a-f]+) from_priv=\d from_v=\d to_priv=\d to_v=\d", line,
        )
        if pc:
            steps.append({"pc": int(pc[1], 16), "opcode": int(pc[2], 16), "dis": pc[3]})
        elif next_pc:
            steps[-1]["next_pc"] = int(next_pc[1], 16)
        elif trap:
            event = {"name": trap[1], **dict(zip(
                ("cause", "epc", "tval", "tval2", "tinst", "target"),
                (int(trap[i], 16) for i in range(2, 8)),
            ))}
            step = steps[-1]
            if event["epc"] != step["pc"] or event["target"] != step["next_pc"]:
                raise ValueError("trap EPC/target does not match instruction/next PC")
            step["trap"] = event
            traps.append(event)
    if not steps:
        raise ValueError("empty trace")
    for step in steps:
        if "next_pc" not in step:
            raise ValueError("missing next PC")
        if step["dis"] == "?":
            if "trap" not in step:
                raise ValueError("unavailable instruction without a trap event")
            unavailable += 1
            continue
        if image.get(step["pc"]) != step["opcode"]:
            raise ValueError(f"instruction/image mismatch at {step['pc']:#x}: {step}")
        checked += 1
    footer = f"Executed {len(steps)} instructions, exit status (SUCCESS)"
    if lines[-1] != footer:
        raise ValueError("missing/inconsistent trace footer")
    return {
        "trace": str(trace_path), "assembly": str(assembly_path),
        "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        "assembly_sha256": hashlib.sha256(assembly_path.read_bytes()).hexdigest(),
        "steps": len(steps), "image_matches": checked,
        "unavailable_with_trap": unavailable, "traps": traps, "passed": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("assembly", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.trace, args.assembly), indent=2))
