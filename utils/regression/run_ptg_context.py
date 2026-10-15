#!/usr/bin/env python3.12
"""Managed PTG context switching: generation, independent ELF replay and semantic audit."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from ptg_replay_audit import audit_case
from run_hypervisor_m1 import ROOT, derive_config, environment, parse_trace, require


def audit_switches(directory):
    blocks, _ = parse_trace((directory / "fpix_sim.log").read_text())
    reference, _ = parse_trace((directory / "sim.log").read_text())
    start = next(i for i, block in enumerate(blocks) if block["pc"] == reference[0]["pc"])
    blocks = blocks[start:]
    loads = [b for b in blocks if b["mnemonic"] == "hlv.d"]
    stores = [b for b in blocks if b["mnemonic"] == "hsv.d"]
    require(len(loads) == 132 and len(stores) == 64, "wrong guest access count")
    # Explicit independent value oracle for the A/B/A persistence scenario.
    values = [0x1111222233334444, 0xAAAABBBBCCCCDDDD]
    operations = [b for b in blocks if b["mnemonic"] in ("hlv.d", "hsv.d")]
    pos = 0
    spas = {}
    for switch in range(64):
        index = switch % 2
        value = 0x5566000000000000 | (index << 32) | switch
        before, store, alias = operations[pos:pos + 3]
        pos += 3
        for block, direction, va, expected in (
            (before, "R", 0x40000000, values[index]),
            (store, "W", 0x40000000, value),
            (alias, "R", 0x40010000, value),
        ):
            require(len(block["memory"]) == 1, "missing guest memory event")
            event = block["memory"][0]
            require((event[0], event[2], event[4], event[5]) ==
                    (direction, va, 8, expected.to_bytes(8, "little").hex()),
                    "context data isolation/persistence mismatch")
            spas.setdefault(index, event[3])
            require(event[3] == spas[index], "context payload SPA changed")
        values[index] = value
        if switch < 2:
            for slot in (1, 2):
                block = operations[pos]
                pos += 1
                event = block["memory"][0]
                expected = 0x1020304050607080 + index * 0x100 + slot
                require(event[2] == 0x40000000 + slot * 0x200000 + 0x1238
                        and event[5] == expected.to_bytes(8, "little").hex(),
                        "mixed-page payload mismatch")
    require(spas[0] != spas[1], "two VMs unexpectedly share payload SPA")
    require(sum(b["mnemonic"] == "hfence.gvma" for b in blocks) == 65, "missing G fences")
    require(sum(b["mnemonic"] == "hfence.vvma" for b in blocks) == 129, "missing VS fences")
    controls = [b for b in blocks if b["opcode"] in (0x22000073, 0x62000073)
                or (b["opcode"] & 0x7F == 0x73 and (b["opcode"] >> 12) & 7 in (1, 2)
                    and b["opcode"] >> 20 in (0x280, 0x680, 0x600))]
    require(len(controls) == 64 * 7 + 4, "missing context activation/deactivation controls")
    require([b["opcode"] for b in controls[-4:]] ==
            [0x28001073, 0x22000073, 0x68001073, 0x62000073], "wrong deactivation sequence")
    for switch in range(64):
        control = controls[switch * 7:(switch + 1) * 7]
        expected_ops = (0x28001073, 0x22000073, 0x68001073, 0x62000073,
                        0x28001073, 0x22000073, 0x60002073)
        require([b["opcode"] & ~(31 << 15) for b in control] == list(expected_ops),
                "wrong CSR/fence activation order")
        def value(block):
            return block["before"].get("x" + str((block["opcode"] >> 15) & 31))
        vsatp, hgatp = value(control[4]), value(control[2])
        require(value(control[0]) == 0 and value(control[6]) == 0x100,
                "wrong VS disable or HSTATUS.SPVP mask")
        require(vsatp is not None and hgatp is not None and vsatp >> 60 == hgatp >> 60 == 8
                and (vsatp >> 44) & 0xFFFF == 0x11 + switch % 2
                and (hgatp >> 44) & 0x3FFF == 1 + switch % 2,
                "wrong mode/ASID/VMID in architectural CSR sequence")
    return {"switches": 64, "guest_loads": len(loads), "guest_stores": len(stores), "spas": spas}


def audit_mapper(directory):
    blocks, _ = parse_trace((directory / "fpix_sim.log").read_text())
    reference, _ = parse_trace((directory / "sim.log").read_text())
    start = next(i for i, b in enumerate(blocks) if b["pc"] == reference[0]["pc"])
    vmid, stores, loads = None, 0, 0
    values, pages = {}, {}
    for block in blocks[start:]:
        opcode = block["opcode"]
        if opcode & 0xFFF07FFF == 0x68001073:
            vmid = (block["before"].get("x" + str((opcode >> 15) & 31), 0) >> 44) & 0x3FFF
        if block["mnemonic"] not in ("hlv.d", "hsv.d"):
            continue
        require(vmid in (1, 2) and len(block["memory"]) == 1, "bad generated guest access")
        direction, bank, va, pa, size, data = block["memory"][0]
        normalized = va - 0x10000 if 0x40010000 <= va < 0x40014000 else va
        require(0x40000000 <= normalized < 0x40004000 and size == 8 and va % 8 == 0,
                "genVA returned a forbidden or unaligned range")
        page, word = (normalized - 0x40000000) // 0x1000, (normalized & 0xFFF) // 8
        key = vmid, page, word
        pages.setdefault((vmid, page), pa - (va & 0xFFF))
        require(pages[vmid, page] == pa - (va & 0xFFF), "PA mapping changed")
        if direction == "W":
            expected = 0x2200000000000000 | (vmid << 48) | (stores << 16) | word
            require(vmid == 1 + stores % 2, "wrong VM during generated store")
            values[key] = expected
            stores += 1
        else:
            expected = values.get(key, 0x1000000000000000 | (vmid << 48) | (page << 32) | word)
            loads += 1
        require(data == expected.to_bytes(8, "little").hex(), "generated address data mismatch")
    require((loads, stores) == (65, 32), "wrong C++ mapper scenario length")
    require(len(set(pages.values())) == len(pages), "cross-context payload alias")
    text = (directory / "generation.log").read_text()
    require(len(re.findall(r"PTG_DATA_ADDRESS genVA vmid=", text)) == 32,
            "missing native genVA path evidence")
    require(len(re.findall(r"PTG_DATA_ADDRESS genVAforPA vmid=", text)) == 32,
            "missing native reverse-selection evidence")
    return {"generated_va": 32, "generated_reverse_va": 32, "loads": loads, "stores": stores}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--friscv", required=True, type=Path)
    parser.add_argument("--fpix-bin", required=True, type=Path)
    parser.add_argument("--handcar-so", required=True, type=Path)
    parser.add_argument("--ptg-lib", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--scenario", choices=("contexts", "mapper"), default="contexts")
    parser.add_argument("--fpix-config", type=Path,
                        default=ROOT / "fpix/config/riscv_rv64_hypervisor.config")
    parser.add_argument("--artifact-root", type=Path, default=ROOT / "output/ptg_context")
    args = parser.parse_args()
    require(os.environ.get("FORCE_SOURCED") == "True", "source setenv.bash first")
    args.artifact_root.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="contexts-", dir=args.artifact_root)).resolve()
    print("Run directory: " + str(run))
    generator_config = run / "generator.config"
    generator_config.write_bytes(derive_config(args.config.read_bytes(), args.handcar_so.resolve()))
    tree = ET.parse(args.fpix_config)
    tree.find("simulator_shared_object").set("file", str(args.handcar_so.resolve()))
    fpix_config = run / "fpix.config"
    tree.write(fpix_config)
    template = ROOT / "tests/riscv" / (
        "ptg_cpp_mapper_force.py" if args.scenario == "mapper" else "ptg_vm_context_fence_force.py"
    )
    inputs = [args.friscv, args.fpix_bin, args.handcar_so, args.ptg_lib, generator_config,
              fpix_config, template, ROOT / "py/riscv/paging/PtgVmContext.py",
              ROOT / "py/riscv/paging/PtgBackend.py", ROOT / "py/riscv/GenThreadRISCV.py",
              Path(__file__), ROOT / "utils/regression/ptg_replay_audit.py"]
    def hashes():
        return {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    report = {"passed": False, "scenario": args.scenario, "inputs_before": hashes(), "cases": []}
    env = environment(ROOT, args.ptg_lib.resolve())
    env["FPIX_PATH"] = str(ROOT / "fpix")
    try:
        for seed in (1, 0xDEADBEEF, 0x123456789):
            directory = run / f"seed-{seed:x}"
            directory.mkdir()
            item = {"seed": seed, "directory": str(directory), "commands": []}
            report["cases"].append(item)
            elf = directory / (template.stem + ".Default.ELF")
            commands = (
                ("generation.log", [str(args.friscv.resolve()), "-t", str(template),
                                    "--cfg", str(generator_config), "-s", str(seed)]),
                ("replay.log", [str(args.fpix_bin.resolve()), "--cfg", str(fpix_config),
                                "--core_num", "1", "-i", "100000", str(elf)]),
            )
            for filename, command in commands:
                with (directory / filename).open("w") as log:
                    rc = subprocess.run(command, cwd=directory, env=env, timeout=120,
                                        stdout=log, stderr=subprocess.STDOUT).returncode
                item["commands"].append({"command": command, "rc": rc})
                require(rc == 0, filename + " failed")
                text = (directory / filename).read_text(errors="replace")
                loaded = [p.strip() for p in re.findall(r"calling init:\s*([^\n]+)", text)]
                require(str(args.handcar_so.resolve()) in loaded, "wrong Handcar library")
                if filename == "generation.log":
                    require(str(args.ptg_lib.resolve()) in loaded, "wrong PTG library")
                    marker = ("PTG CPP MAPPER: automatic VA/PA aliases, isolation and fail-closed checks PASS"
                              if args.scenario == "mapper" else
                              "PTG MANAGED CONTEXT: 64 switches, aliases, mixed ranges and stores PASS")
                    require(marker in text, "missing managed-context assertions")
                else:
                    first_step = text.find("[STEPDBG] before pc=")
                    require(first_step >= 0, "missing standalone step diagnostic")
                    require("[WRITE_SIM_MEM]" not in text[first_step:],
                            "host memory rewrite occurred during standalone execution")
            item["replay_audit"] = audit_case(directory, require_traps=False)
            if args.scenario == "mapper":
                item["mapper_audit"] = audit_mapper(directory)
            else:
                item["switch_audit"] = audit_switches(directory)
        report["inputs_after"] = hashes()
        require(report["inputs_before"] == report["inputs_after"], "inputs changed during run")
        report["passed"] = True
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
    finally:
        (run / "contexts.json").write_text(json.dumps(report, indent=2) + "\n")
    print(("PASS: " if report["passed"] else "FAIL: ") + str(run / "contexts.json"))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
