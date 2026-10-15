#!/usr/bin/env python3.12
"""Run the reserved-pool FORCE template with explicit libraries and isolated seed directories."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from run_hypervisor_m1 import ROOT, derive_config, environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handcar-so", required=True, type=Path)
    parser.add_argument("--ptg-lib", required=True, type=Path)
    parser.add_argument("--friscv", type=Path, default=ROOT / "bin/friscv")
    parser.add_argument("--config", type=Path, default=ROOT / "config/riscv_rv64_handcar.config")
    parser.add_argument("--artifact-root", type=Path, default=ROOT / "output/ptg_pool_contract")
    args = parser.parse_args()
    if os.environ.get("FORCE_SOURCED") != "True" or sys.version_info[:2] != (3, 12):
        parser.error("source setenv.bash and use Python 3.12")
    handcar, ptg = args.handcar_so.resolve(strict=True), args.ptg_lib.resolve(strict=True)
    template = ROOT / "tests/riscv/ptg_reserved_pool_force.py"
    friscv = args.friscv.resolve(strict=True)
    source_config = args.config.resolve(strict=True)
    inputs = [handcar, ptg, template, ROOT / "py/riscv/paging/PtgBackend.py", friscv, source_config,
              Path(__file__).resolve(), ROOT / "utils/regression/run_hypervisor_m1.py"]

    def hashes():
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}

    args.artifact_root.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="force-pool-", dir=args.artifact_root)).resolve()
    config = run / "generator.config"
    config.write_bytes(derive_config(
        source_config.read_bytes(), handcar
    ))
    inputs.append(config)
    report = {"inputs_before": hashes(), "cases": [], "passed": False,
              "started_at": time.time()}
    for seed in (1, 0xDEADBEEF, 0x123456789):
        case = run / "seed-{:x}".format(seed)
        case.mkdir()
        command = [str(friscv), "--cfg", str(config), "-t", str(template),
                   "-s", str(seed)]
        with (case / "command.log").open("wb") as log:
            try:
                process = subprocess.run(command, cwd=case, env=environment(ROOT, ptg),
                                         stdout=log, stderr=subprocess.STDOUT, timeout=120)
                rc = process.returncode
            except subprocess.TimeoutExpired:
                rc = 124
        text = (case / "command.log").read_text(errors="replace")
        libraries = [entry.strip() for entry in re.findall(r"calling init:\s*([^\n]+)", text)]
        elf = list(case.glob("*.ELF"))
        passed = (rc == 0 and len(elf) == 1 and elf[0].stat().st_size > 0
                  and "PTG OWNED POOL: existing reservation and neighbor preserved; reuse rejected"
                  in text and str(handcar) in libraries and str(ptg) in libraries)
        report["cases"].append({
            "seed": seed, "command": command, "cwd": str(case), "return_code": rc,
            "passed": passed, "loaded_libraries": libraries,
        })
        if not passed:
            break
    report["inputs_after"] = hashes()
    report["finished_at"] = time.time()
    report["passed"] = (len(report["cases"]) == 3 and all(c["passed"] for c in report["cases"])
                        and report["inputs_before"] == report["inputs_after"])
    (run / "pool-contract.json").write_text(json.dumps(report, indent=2) + "\n")
    print("{}: {}".format("PASS" if report["passed"] else "FAIL", run / "pool-contract.json"))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
