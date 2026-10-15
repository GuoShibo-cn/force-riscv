"""Native FPIX exit/ISA checks plus positive and incomplete-image replay controls."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import xml.etree.ElementTree as ET

from ptg_replay_audit import audit_replay


def tiny_elf(code):
    # One allocated executable PROGBITS section; no host-side architectural setup.
    ident = b"\x7fELF\x02\x01\x01" + bytes(9)
    header = struct.pack("<16sHHIQQQIHHHHHH", ident, 2, 243, 1, 0x80000000,
                         0, 64 + len(code), 0, 64, 0, 0, 64, 2, 0)
    section = struct.pack("<IIQQQQIIQQ", 0, 1, 6, 0x80000000, 64, len(code), 0, 0, 2, 0)
    return header + code + bytes(64) + section


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fpix-bin", required=True, type=Path)
    parser.add_argument("--handcar-so", required=True, type=Path)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--generation-trace", required=True, type=Path)
    parser.add_argument("--missing-image-elf", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    args.output_dir.mkdir(parents=True, exist_ok=False)
    report = {"cases": [], "inputs": {}, "passed": False}
    for key in ("fpix_bin", "handcar_so", "elf", "generation_trace", "missing_image_elf"):
        path = getattr(args, key).resolve()
        report["inputs"][key] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    tests = (
        ("jal-self", struct.pack("<I", 0x6F), True, 0, None),
        ("compressed-self", struct.pack("<H", 0xA001), True, 0, None),
        ("illegal-stationary", bytes(4), True, 1, None),
        ("missing-h", struct.pack("<II", 0x20501073, 0x6F), False, 1, None),
        ("h-enabled", struct.pack("<II", 0x20501073, 0x6F), True, 0, None),
        ("complete-image", args.elf.read_bytes(), True, 0, True),
        ("missing-page-tables", args.missing_image_elf.read_bytes(), True, 0, False),
    )
    try:
        for name, payload, with_h, expected_rc, expected_audit in tests:
            directory = args.output_dir / name
            directory.mkdir()
            # Exercise long absolute file paths, which exposed the empty-string transform bug.
            image = directory / (("x" * 160) + ".ELF")
            image.write_bytes(tiny_elf(payload) if expected_audit is None else payload)
            tree = ET.parse(root / "fpix/config/riscv_rv64_hypervisor.config")
            tree.find("simulator_shared_object").set("file", str(args.handcar_so.resolve()))
            if not with_h:
                tree.find("simulator_config_string").set("value", "--isa=RV64IMAFDCV_zfh")
            config = directory / "fpix.config"
            tree.write(config)
            command = [str(args.fpix_bin.resolve()), "--cfg", str(config.resolve()),
                       "--core_num", "1", "-i", "3000", str(image.resolve())]
            with (directory / "console.log").open("w") as log:
                result = subprocess.run(command, cwd=directory, timeout=30,
                                        env=dict(os.environ, FPIX_PATH=str(root / "fpix")),
                                        stdout=log, stderr=subprocess.STDOUT)
            item = {"name": name, "command": command, "rc": result.returncode}
            report["cases"].append(item)
            if result.returncode != expected_rc:
                raise AssertionError(f"{name}: rc={result.returncode}, expected {expected_rc}")
            trace = (directory / "fpix_sim.log").read_text()
            if expected_rc:
                if "stationary PC" not in trace or "exit status (SUCCESS)" in trace:
                    raise AssertionError(f"{name}: termination failure was not recorded")
            if expected_audit is not None:
                try:
                    item["audit"] = audit_replay(args.generation_trace.read_text(), trace)
                    accepted = True
                except ValueError as error:
                    item["audit_error"] = str(error)
                    accepted = False
                if accepted != expected_audit:
                    raise AssertionError(f"{name}: wrong semantic acceptance")
        report["passed"] = True
    finally:
        (args.output_dir / "checks.json").write_text(json.dumps(report, indent=2) + "\n")
    print("PASS: 7 native exit/ISA/image-replay checks")


if __name__ == "__main__":
    main()
