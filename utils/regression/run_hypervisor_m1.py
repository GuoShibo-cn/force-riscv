#!/usr/bin/env python3
"""Isolated, evidence-based M1 acceptance for the three existing PTG templates.

Generation requires Linux/glibc and sourced FORCE Python 3.12. Audit-only
uses archived inputs; absolute XML dependencies must also remain unchanged.
SHA-256 detects stale/replaced artifacts, not an adversary who rewrites
both evidence and manifests. Only single-hart, non-speculative traces from
the three current templates are supported; unknown trace syntax fails closed.
"""

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = {
    "access": "ptg_hypervisor_access_matrix_force.py",
    "fault": "ptg_hypervisor_fault_matrix_force.py",
    "two_stage": "ptg_two_stage_fixed_force.py",
}
FIXED_SEEDS = (1, 0xDEADBEEF, 0x123456789)
FULL = (1 << 64) - 1
MSTATUS_MASK = (1 << 39) | (1 << 38) | 0x1800
MSTATUS_EXPECTED = (1 << 38) | 0x1800
FAULT_REGS = (
    (3, 4, 5, 6, 7, 9),
    (10, 11, 12, 13, 14, 15),
    (16, 17, 18, 19, 20, 21),
    (22, 23, 24, 25, 26, 27),
)
FAULT_SENTINELS = (0x1111222233334444, 0x5555666677778888, 0x9999AAAABBBBCCCC, 0xDDDDEEEEFFFF0001)
TWO_VALUES = (
    0xDEADBEEFCAFE1234,
    0x0123456789ABCDEF,
    0xA5B6C7D8E9FA0B1C,
    0xFEDCBA9876543210,
    0x0F1E2D3C4B5A6978,
)
TWO_ADDRESSES = (
    (0x80200000, 0xA0200000),
    (0x40123450, 0x100123450),
    (0x20000FFC, 0x140000FFC),
    (0x21000678, 0x142000678),
    (0x21201230, 0x144000230),
)
TWO_LABELS = (
    "",
    "1 GiB ",
    "cross-page HLV.D ",
    "VS 4 KiB/G 2 MiB HLV.D ",
    "VS 2 MiB/G 4 KiB HLV.D ",
)
BAD_LOG = re.compile(r"\b(?:FAIL(?:ED|URE)?|ERROR|FATAL)\b|Traceback \(most recent", re.I)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def seed_value(text):
    try:
        value = int(text, 16 if text.lower().startswith("0x") else 10)
        require(0 <= value <= FULL, "seed must fit unsigned 64 bits")
        return value
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def case_matrix(profile, seeds=None):
    return [
        {"id": f"{kind}-seed-{seed:x}", "kind": kind, "seed": seed}
        for kind in TEMPLATES
        for seed in (
            list(dict.fromkeys(seeds))
            if seeds
            else (
                [1]
                if profile == "smoke"
                else (range(1, 101) if kind == "two_stage" else FIXED_SEEDS)
            )
        )
    ]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--friscv", type=Path, default=ROOT / "bin/friscv")
    parser.add_argument(
        "--handcar-so", type=Path, help="required explicit Handcar .so; no fallback"
    )
    parser.add_argument("--ptg-lib", type=Path, help="required explicit libptg.so; no fallback")
    parser.add_argument("--config", type=Path, default=ROOT / "config/riscv_rv64.config")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=ROOT / "output/hypervisor_m1",
        help="parent of a new unique run directory; never reuse case outputs",
    )
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument(
        "--seed",
        type=seed_value,
        action="append",
        help="repeatable; REPLACES default seeds for ALL three templates",
    )
    parser.add_argument(
        "--profile",
        choices=("smoke", "m1"),
        default="smoke",
        help="smoke: 3 x seed 1; m1: access/fault 1,0xdeadbeef,0x123456789 "
        "and two_stage 1..100 (106 cases)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120,
        help="seconds per case; kills the entire process group (default 120)",
    )
    parser.add_argument(
        "--preflight", action="store_true", help="check environment only; do not run"
    )
    parser.add_argument(
        "--audit-only",
        type=Path,
        metavar="RUN_DIR",
        help="re-audit a runner-produced manifest; no generation or library loading",
    )
    args = parser.parse_args(argv)
    if args.jobs < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--jobs and --timeout must be positive and finite")
    if args.audit_only:
        if args.preflight or args.seed:
            parser.error("--audit-only cannot be combined with --preflight or --seed")
    elif args.handcar_so is None or args.ptg_lib is None:
        parser.error("generation/preflight requires explicit --handcar-so and --ptg-lib")
    return args


def config_dependencies(config, root=ROOT):
    """Resolve paths against FORCE_PATH, as Config::LookUpFile does."""
    pending, visited, dependencies = [config.resolve()], set(), {}
    while pending:
        path = pending.pop(0)
        require(path not in visited, f"duplicate/cyclic config import: {path}")
        visited.add(path)
        tree = ET.parse(path)
        for element in tree.iter():
            if "file" not in element.attrib or element.tag == "simulator_shared_object":
                continue
            reference = Path(element.attrib["file"])
            require(
                reference.is_absolute() or ".." not in reference.parts,
                "parent traversal in XML dependencies is unsupported",
            )
            dependency = reference if reference.is_absolute() else root / reference
            dependency = dependency.resolve()
            require(dependency.is_file(), f"missing XML dependency: {dependency}")
            dependencies.setdefault(dependency, set()).add(reference)
            if element.tag == "import_file":
                pending.append(dependency)
    return dependencies


def derive_config(source, handcar):
    """Preserve bytes except simulator_shared_object's file attribute."""
    tree = ET.fromstring(source)
    nodes = list(tree.iter("simulator_shared_object"))
    require(
        len(nodes) == 1 and "file" in nodes[0].attrib,
        "top-level config must contain exactly one simulator_shared_object file",
    )
    pattern = rb'(<simulator_shared_object\b[^>]*?\bfile\s*=\s*)([\'"])(.*?)(\2)'
    replacement = escape(str(handcar), {'"': "&quot;", "'": "&apos;"}).encode()
    derived, count = re.subn(pattern, lambda m: m[1] + m[2] + replacement + m[4], source)
    require(count == 1, "ambiguous simulator_shared_object XML")
    return derived


def environment(force_path, ptg):
    env = os.environ.copy()
    for key in ("LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH", "LD_DEBUG_OUTPUT", "PYTHONHOME"):
        env.pop(key, None)
    env.update(
        {
            "PATH": os.pathsep.join(
                (str(Path(sys.executable).parent), "/usr/local/bin", "/usr/bin", "/bin")
            ),
            "PYTHONPATH": os.pathsep.join(
                str(force_path / p)
                for p in (
                    "py",
                    "3rd_party/py",
                    "utils",
                    "utils/builder",
                    "utils/builder/test_builder",
                    "utils/builder/shared",
                    "utils/regression",
                )
            ),
            "FORCE_PATH": str(force_path),
            "PTG_LIB_PATH": str(ptg),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "LC_ALL": "C",
            "LD_DEBUG": "libs",
        }
    )
    return env


def probe_diagnostic(stderr):
    """Keep Python errors visible when LD_DEBUG emits a long shutdown trace afterward."""
    text = stderr.decode(errors="replace")
    messages = [line for line in text.splitlines()
                if line.strip() and not re.match(r"^\s*\d+:", line)]
    return ("\n".join(messages) or text)[-3000:]


def preflight(args):
    require(sys.version_info[:2] == (3, 12), "run with Python 3.12")
    require(
        os.environ.get("FORCE_SOURCED") == "True", "source setenv.bash from the repo root first"
    )
    require(sys.platform == "linux", "Linux/glibc loader evidence is required")
    paths = {
        "handcar": args.handcar_so.expanduser().resolve(),
        "ptg": args.ptg_lib.expanduser().resolve(),
        "friscv": args.friscv.expanduser().resolve(),
        "config": args.config.expanduser().resolve(),
    }
    for name, path in paths.items():
        require(path.is_file(), f"missing {name}: {path}")
        if name != "config":
            with path.open("rb") as stream:
                require(stream.read(4) == b"\x7fELF", f"not an ELF binary: {path}")
    require(os.access(paths["friscv"], os.X_OK), "friscv is not executable")
    dependencies = config_dependencies(paths["config"])
    derive_config(paths["config"].read_bytes(), paths["handcar"])
    for template in TEMPLATES.values():
        require((ROOT / "tests/riscv" / template).is_file(), f"missing template: {template}")
    probe = subprocess.run(
        [str(paths["friscv"]), "--help"],
        env=environment(ROOT, paths["ptg"]),
        capture_output=True,
        timeout=15,
    )
    require(
        probe.returncode == 0 and b"calling init:" in probe.stderr,
        "friscv/glibc loader preflight failed: " + probe_diagnostic(probe.stderr),
    )
    # Generator callbacks resolve inside friscv; do not step Handcar here.
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import ctypes, os, sys; "
            "from riscv.paging.PtgBackend import PtgHandle; "
            "lib = ctypes.CDLL(sys.argv[1], mode=os.RTLD_LAZY); "
            "[getattr(lib, name) for name in ('initialize_simulator', 'step_simulator', "
            "'read_simulator_register', 'write_simulator_register', 'terminate_simulator')]; "
            "ptg = PtgHandle(); ptg._require_mapping_v1(); "
            "ptg._require_placement_v1(); ptg.destroy()",
            str(paths["handcar"]),
        ],
        env=environment(ROOT, paths["ptg"]),
        capture_output=True,
        timeout=15,
    )
    require(
        probe.returncode == 0,
        "Handcar symbols/PTG ctypes preflight failed: "
        + probe_diagnostic(probe.stderr),
    )
    return paths, dependencies


def prepare_run(args, paths, dependencies):
    parent = args.artifact_root.expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="m1-", dir=parent))
    inputs = run / "inputs"
    inputs.mkdir()
    manifest = {
        "schema": 1,
        "run_id": run.name,
        "run_dir": str(run),
        "created_at": time.time(),
        "profile": args.profile,
        "seeds": args.seed,
        "python": {"executable": sys.executable, "version": sys.version},
        "jobs": args.jobs,
        "timeout": args.timeout,
        "inputs": {},
        "cases": case_matrix(args.profile, args.seed),
    }

    def archive(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        before = sha256(source)
        shutil.copy2(source, target)
        require(
            sha256(target) == before == sha256(source), f"input changed while copying: {source}"
        )
        manifest["inputs"][str(target.relative_to(run))] = {
            "source": str(source),
            "sha256": before,
        }

    for path, references in sorted(dependencies.items()):
        for reference in sorted(references):
            target = (
                inputs / "external" / sha256(path)
                if reference.is_absolute()
                else inputs / "force" / reference
            )
            archive(path, target)
            # Keep absolute XML paths; bind both snapshot and live file.
            if reference.is_absolute():
                manifest["inputs"][str(target.relative_to(run))]["live_absolute"] = str(path)
    for directory in (ROOT / "py", ROOT / "3rd_party/py"):
        for path in sorted(directory.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive(path, inputs / "force" / path.relative_to(ROOT))
    for kind, template in TEMPLATES.items():
        archive(ROOT / "tests/riscv" / template, inputs / "templates" / template)
    archive(Path(__file__).resolve(), inputs / "runner.py")
    for name in ("handcar", "ptg", "friscv"):
        archive(paths[name], inputs / "bin" / name / paths[name].name)
        manifest[name] = str((inputs / "bin" / name / paths[name].name).relative_to(run))
    archive(paths["config"], inputs / "source.config")
    derived = inputs / "derived.config"
    derived.write_bytes(derive_config(paths["config"].read_bytes(), run / manifest["handcar"]))
    manifest["inputs"][str(derived.relative_to(run))] = {
        "source": str(paths["config"]),
        "sha256": sha256(derived),
    }
    manifest["config"] = str(derived.relative_to(run))
    env = environment(inputs / "force", run / manifest["ptg"])
    manifest["environment"] = {
        key: env[key]
        for key in (
            "PATH",
            "PYTHONPATH",
            "FORCE_PATH",
            "PTG_LIB_PATH",
            "LD_DEBUG",
            "PYTHONNOUSERSITE",
            "PYTHONDONTWRITEBYTECODE",
            "PYTHONHASHSEED",
            "LC_ALL",
        )
    }
    for case in manifest["cases"]:
        case["template"] = "inputs/templates/" + TEMPLATES[case["kind"]]
        case["command"] = [
            str(run / manifest["friscv"]),
            "-s",
            hex(case["seed"]),
            "-t",
            str(run / case["template"]),
            "--cfg",
            str(derived),
        ]
        case["binding"] = digest_json(
            {
                "run_id": manifest["run_id"],
                "case": case.copy(),
                "inputs": manifest["inputs"],
                "env": manifest["environment"],
            }
        )
    write_json(run / "manifest.json", manifest)
    return run, manifest, env


def parse_trace(text):
    lines = text.splitlines()
    require(lines and text.endswith("\n"), "missing or truncated sim.log")
    trace_v2 = lines[0] == (
        "# HANDCAR trace v2: PC(VA)=instruction address; "
        "NextPC(VA)=after step; Trap=take_trap event"
    )
    if trace_v2:
        lines = lines[1:]
    footer = re.fullmatch(r"Executed (\d+) instructions, exit status \(SUCCESS\)", lines[-1])
    require(footer is not None, "missing successful sim.log footer")
    count = int(footer[1])
    require(
        len(lines) >= 2 and lines[-2] == f"Cpu 0 executed {count} instructions.",
        "missing CPU summary",
    )
    blocks, state = [], {"x0": 0}
    for line in lines[:-2]:
        header = re.fullmatch(r"Cpu 0 (\d+) ----", line)
        if header:
            require(int(header[1]) == len(blocks) + 1, "non-contiguous instruction sequence")
            blocks.append(
                {
                    "index": int(header[1]),
                    "before": state.copy(),
                    "writes": {},
                    "memory": [],
                    "exceptions": [],
                    "traps": [],
                }
            )
            continue
        require(bool(blocks), "trace data outside instruction block")
        block = blocks[-1]
        pc = re.fullmatch(r"Cpu 0 PC\(VA\) 0x([0-9a-f]+) op: 0x([0-9a-f]+) : (.+)", line)
        next_pc = re.fullmatch(r"Cpu 0 NextPC\(VA\) 0x([0-9a-f]+)", line)
        trap = re.fullmatch(
            r"Cpu 0 Trap (\S+) cause=0x([0-9a-f]+) epc=0x([0-9a-f]+) "
            r"tval=0x([0-9a-f]+) tval2=0x([0-9a-f]+) tinst=0x([0-9a-f]+) "
            r"target=0x([0-9a-f]+) from_priv=([0-3]) from_v=([01]) "
            r"to_priv=([0-3]) to_v=([01])", line,
        )
        reg = re.fullmatch(r"Cpu 0 Reg W (\w+) val 0x([0-9a-f]+) mask 0x([0-9a-f]+)", line)
        mem = re.fullmatch(
            r"Cpu 0 Mem ([RW]) bank (\d+) VA 0x([0-9a-f]+) PA 0x([0-9a-f]+) "
            r"size (\d+) bytes 0x([0-9a-f]+)",
            line,
        )
        if pc:
            require("opcode" not in block, "duplicate PC record")
            block["pc" if trace_v2 else "post_pc"] = int(pc[1], 16)
            block.update(
                opcode=int(pc[2], 16),
                mnemonic=pc[3].split()[0],
                disassembly=pc[3],
            )
        elif next_pc:
            require(trace_v2 and "post_pc" not in block, "unexpected/duplicate next PC")
            block["post_pc"] = int(next_pc[1], 16)
        elif trap:
            require(trace_v2, "trap record requires trace v2")
            block["exceptions"].append(line)
            block["traps"].append(dict(zip(
                ("cause", "epc", "tval", "tval2", "tinst", "target"),
                (int(trap[i], 16) for i in range(2, 8)),
            )))
        elif reg:
            require(int(reg[3], 16) == FULL, "partial register mask unsupported")
            require(reg[1] not in block["writes"], "duplicate register write")
            block["writes"][reg[1]] = int(reg[2], 16)
            state[reg[1]] = int(reg[2], 16)
        elif mem:
            data = bytes.fromhex(mem[6])
            require(len(data) == int(mem[5]), "truncated memory bytes")
            block["memory"].append(
                (mem[1], int(mem[2]), int(mem[3], 16), int(mem[4], 16), int(mem[5]), data.hex())
            )
        elif line.startswith("Excpt ID "):
            block["exceptions"].append(line)
        else:
            raise ValueError(f"unsupported/malformed trace line: {line[:200]}")
    require(len(blocks) == count and count > 0, "trace instruction count mismatch")
    for block in blocks:
        require("opcode" in block and (not trace_v2 or "pc" in block), "missing instruction PC")
        require(
            "post_pc" in block and block["writes"].get("PC") == block["post_pc"],
            f"incomplete instruction block {block['index']}",
        )
    require(
        blocks[-1]["opcode"] == 0x6F and not blocks[-1]["memory"], "missing terminal self-loop"
    )
    return blocks, state


def memory_event(direction, va, pa, value, size=8):
    return (direction, 0, va, pa, size, value.to_bytes(size, "little").hex())


def check_read(block, register, value, final):
    name = f"x{register}"
    require(
        block["writes"].get(name, block["before"].get(name)) == value,
        f"instruction {block['index']} {name} sentinel/CSR mismatch",
    )
    require(final.get(name) == value, f"final {name} mismatch")


def audit_semantics(kind, sim, command_log):
    require(not BAD_LOG.search(command_log + "\n" + sim), "FAIL/ERROR in logs")
    blocks, final = parse_trace(sim)
    evidence = []
    hblocks = [b for b in blocks if b["mnemonic"] in ("hlv.d", "hsv.d", "hlvx.wu")]
    if kind in ("access", "two_stage"):
        require(not any(b["exceptions"] for b in blocks), "unexpected exception")
        if kind == "two_stage":
            require(len(hblocks) == 5, "expected five two-stage HLV instructions")
            for index, (block, value, addresses, label) in enumerate(
                zip(hblocks, TWO_VALUES, TWO_ADDRESSES, TWO_LABELS)
            ):
                rd, (va, pa) = index + 2, addresses
                require(block["opcode"] == 0x6C00C073 | rd << 7, "wrong HLV opcode/operands")
                require(block["before"].get("x1") == va, "wrong HLV source VA")
                expected = (
                    [
                        memory_event("R", va, pa, value & 0xFFFFFFFF, 4),
                        memory_event("R", va + 4, pa + 4, value >> 32, 4),
                    ]
                    if index == 2
                    else [memory_event("R", va, pa, value)]
                )
                require(block["memory"] == expected, f"two-stage trajectory {index} mismatch")
                check_read(block, rd, value, final)
                require(
                    command_log.splitlines().count(
                        f"[notice]Front-end: SUCCESS: {label}x{rd} = 0x{value:016X}"
                    )
                    == 1,
                    f"missing/duplicate success marker for x{rd}",
                )
                evidence.append({"instruction": block["index"], "memory": expected, "rd": rd})
            require(
                sum(len(b["memory"]) for b in blocks) == 6, "expected exactly six VA/PA events"
            )
        else:
            require(
                command_log.splitlines().count("[notice]Front-end: HYPERVISOR ACCESS MATRIX: PASS")
                == 1,
                "missing/duplicate access PASS",
            )
            operations = [
                b for b in blocks if b["mnemonic"] in ("hlv.d", "hsv.d", "hlvx.wu", "ld")
            ]
            specs = (
                (0x6C00C173, 2, 0x1122334455667788, 0x40200000, 0x110200000, "R", 8),
                (0x6E30C073, None, 0x8877665544332211, 0x40300000, 0x110300000, "W", 8),
                (0x6C00C273, 4, 0x8877665544332211, 0x40300000, 0x110300000, "R", 8),
                (0x33383, 7, 0x8877665544332211, 0x110300000, 0x110300000, "R", 8),
                (0x6830C2F3, 5, 0xA1B2C3D4, 0x40400000, 0x110400000, "R", 4),
            )
            require(len(operations) == len(specs), "wrong access operation count")
            for block, (op, rd, value, va, pa, direction, size) in zip(operations, specs):
                require(block["opcode"] == op, "wrong access opcode/operands")
                require(
                    block["before"].get("x6" if op == 0x33383 else "x1") == va,
                    "wrong access source VA",
                )
                require(
                    block["memory"] == [memory_event(direction, va, pa, value, size)],
                    "access VA/PA/data mismatch",
                )
                if rd is not None:
                    check_read(block, rd, value, final)
                else:
                    require(
                        block["before"].get("x3") == value and final.get("x3") == value,
                        "HSV source value mismatch",
                    )
                evidence.append({"instruction": block["index"], "memory": block["memory"]})
            reads = [b for b in blocks if b["opcode"] == 0x64502373]
            require(
                len(reads) == 1 and reads[0]["index"] > operations[-1]["index"],
                "missing hvip CSR read",
            )
            check_read(reads[0], 6, 4, final)
            require(sum(len(b["memory"]) for b in blocks) == 5, "unexpected access memory event")
        for block in hblocks:
            previous = blocks[block["index"] - 2]
            require(block["post_pc"] == previous["post_pc"] + 4, "successful H access trapped")
    elif kind == "fault":
        require(
            command_log.splitlines().count(
                "[notice]Front-end: HLV/HSV INVALID VS/G PTE FAULT MATRIX: PASS"
            )
            == 1,
            "missing/duplicate fault PASS",
        )
        require(len(hblocks) == 4, "expected four fault instructions")
        csrs = (0x342, 0x341, 0x343, 0x34B, 0x34A, 0x300)
        for i, block in enumerate(hblocks):
            cause = (13, 15, 21, 23)[i]
            gva, gpa, spa = (
                0x43000000 + i * 0x200000,
                0x86000000 + i * 0x200000,
                0x132000000 + i * 0x200000,
            )
            sentinel, side_rd = FAULT_SENTINELS[i], (28, 30, 29, 31)[i]
            start_index = block["index"] - 1
            # Old archives label POST-PC as PC(VA); v2 records the instruction PC explicitly.
            fault_pc = block.get("pc", blocks[start_index - 1]["post_pc"])
            require(
                block["opcode"] == (0x6C00C173 if i % 2 == 0 else 0x6E20C073),
                f"fault {i}: wrong opcode",
            )
            require(block["before"].get("x1") == gva, f"fault {i}: source GVA mismatch")
            require(
                block["before"].get("x2") == (sentinel if i % 2 == 0 else 0xDEADBEEF01234567),
                f"fault {i}: source/sentinel not prepared",
            )
            mtvec_writes = [b for b in blocks[:start_index] if b["opcode"] == 0x30541073]
            require(bool(mtvec_writes), f"fault {i}: missing mtvec setup")
            target = mtvec_writes[-1]["before"].get("x8")
            require(
                target is not None and block["post_pc"] == target and target != fault_pc,
                f"fault {i}: trap target PC mismatch",
            )
            code_base = (blocks[0]["post_pc"] - 4 + 0xFFF) & ~0xFFF
            entry = code_base + (i + 1) * 0x1000
            require(
                target == code_base + (i + 5) * 0x1000 and entry <= fault_pc < entry + 0x1000,
                f"fault {i}: template entry/handler address mismatch",
            )
            returns = [b for b in blocks[:start_index] if b["opcode"] == 0x30200073]
            require(
                returns and returns[-1]["post_pc"] == entry,
                f"fault {i}: missing MRET to scenario entry",
            )
            require(
                not block["memory"] and set(block["writes"]) == {"PC"},
                f"fault {i}: faulting instruction has side effects",
            )
            expected = (cause, fault_pc, gva, gpa >> 2 if i >= 2 else 0, 0)
            if "pc" in block:
                require(block["traps"] == [dict(zip(
                    ("cause", "epc", "tval", "tval2", "tinst", "target"),
                    expected + (target,),
                ))], f"fault {i}: missing/mismatched actual trap event")
            captures = blocks[start_index + 1 : start_index + 7]
            require(len(captures) == 6, f"fault {i}: truncated CSR capture")
            for j, (capture, csr, rd) in enumerate(zip(captures, csrs, FAULT_REGS[i])):
                require(
                    capture["opcode"] == (csr << 20 | rd << 7 | 0x2073),
                    f"fault {i}: wrong CSR capture order/operands",
                )
                require(
                    capture["post_pc"] == target + 4 * (j + 1), f"fault {i}: handler PC mismatch"
                )
                value = capture["writes"].get(f"x{rd}", capture["before"].get(f"x{rd}"))
                if j == 5:
                    require(
                        value is not None and value & MSTATUS_MASK == MSTATUS_EXPECTED,
                        f"fault {i}: mstatus mask mismatch",
                    )
                else:
                    require(value == expected[j], f"fault {i}: CSR {csr:x} mismatch")
                check_read(capture, rd, value, final)
            end = hblocks[i + 1]["index"] - 1 if i < 3 else len(blocks)
            side_ops = [
                b for b in blocks[start_index + 7 : end] if (b["opcode"] >> 7) & 31 == side_rd
            ]
            require(len(side_ops) == 1, f"fault {i}: missing/duplicate no-side-effects readback")
            side = side_ops[0]
            check_read(side, side_rd, sentinel, final)
            if i % 2 == 0:
                require(
                    side["opcode"] == (side_rd << 7 | 0x10013)
                    and side["before"].get("x2") == sentinel
                    and not side["memory"],
                    f"fault {i}: load destination changed",
                )
            else:
                require(
                    side["opcode"] == (side_rd << 7 | 0xB003)
                    and side["before"].get("x1") == spa
                    and side["memory"] == [memory_event("R", spa, spa, sentinel)],
                    f"fault {i}: store memory sentinel changed",
                )
            name = (
                f"{'HLV' if i % 2 == 0 else 'HSV'}.D {'VS' if i < 2 else 'G'}-stage invalid leaf"
            )
            records = re.findall(
                r"(?m)^\[notice\]Front-end: V2_RESULT name="
                + re.escape(name)
                + r" pte_pa=0x([0-9A-F]+) old=0x([0-9A-F]+) new=0x([0-9A-F]+)"
                r" mcause=(\d+) failing_gpa=0x([0-9A-F]+)$",
                command_log,
            )
            require(len(records) == 1, f"fault {i}: missing/duplicate V2 result")
            pte, old, new, actual, failing = records[0]
            require(
                int(pte, 16) % 8 == 0
                and int(old, 16) & 1
                and int(new, 16) == int(old, 16) & ~1
                and int(actual) == cause
                and (i < 2 or int(failing, 16) == gpa),
                f"fault {i}: V2 metadata mismatch",
            )
            evidence.append(
                {
                    "cause": cause,
                    "fault_pc": fault_pc,
                    "trap_target": target,
                    "csr_registers": FAULT_REGS[i],
                    "sentinel_register": side_rd,
                }
            )
        require(
            sum(len(b["memory"]) for b in blocks) == 2, "unexpected fault matrix memory effects"
        )
    else:
        raise ValueError(f"unknown template kind: {kind}")
    return {"instruction_count": len(blocks), "final_registers": final, "evidence": evidence}


def run_case(run, manifest, case, env):
    directory = run / case["id"]
    directory.mkdir(exist_ok=False)
    record = {
        "id": case["id"],
        "binding": case["binding"],
        "manifest_sha256": sha256(run / "manifest.json"),
        "return_code": None,
        "timeout": False,
        "started_at": time.time(),
        "command": case["command"],
        "cwd": str(directory),
        "files": {},
    }
    with (directory / "command.log").open("wb") as log:
        try:
            process = subprocess.Popen(
                case["command"],
                cwd=directory,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                record["return_code"] = process.wait(timeout=manifest["timeout"])
            except subprocess.TimeoutExpired:
                record["timeout"] = True
                os.killpg(process.pid, signal.SIGKILL)
                record["return_code"] = process.wait()
        except OSError as error:
            record["launch_error"] = str(error)
    record["finished_at"] = time.time()
    stem = Path(TEMPLATES[case["kind"]]).stem + ".Default"
    for name in ("command.log", "sim.log", stem + ".ELF", stem + ".S"):
        path = directory / name
        record["files"][name] = {
            "exists": path.is_file(),
            "size": path.stat().st_size if path.is_file() else 0,
            "sha256": sha256(path) if path.is_file() else None,
        }
    log = (directory / "command.log").read_text(errors="replace")
    record["loaded_libraries"] = sorted(set(re.findall(r"calling init:\s*(/[^\r\n]+)", log)))
    record["library_evidence"] = {
        name: {
            "path": str(run / manifest[name]),
            "sha256": sha256(run / manifest[name]),
            "loaded": str(run / manifest[name]) in record["loaded_libraries"],
        }
        for name in ("handcar", "ptg")
    }
    sim = (
        (directory / "sim.log").read_text(errors="replace")
        if (directory / "sim.log").is_file()
        else ""
    )
    counts = re.findall(r"(?m)^Executed (\d+) instructions, exit status \(([^\n]*)\)$", sim)
    record["reported_instruction_count"] = int(counts[0][0]) if len(counts) == 1 else None
    record["reported_exit_status"] = counts[0][1] if len(counts) == 1 else None
    write_json(directory / "execution.json", record)
    return {"id": case["id"], "execution_sha256": sha256(directory / "execution.json")}


def audit_case(run, manifest, case, receipt):
    result = {
        "id": case["id"],
        "kind": case["kind"],
        "seed": case["seed"],
        "passed": False,
        "failures": [],
        "failure_log": str(run / case["id"] / "command.log"),
    }
    try:
        directory = run / case["id"]
        require(
            sha256(directory / "execution.json") == receipt["execution_sha256"],
            "execution receipt hash mismatch",
        )
        record = json.loads((directory / "execution.json").read_text())
        result.update(
            {
                key: record[key]
                for key in (
                    "return_code",
                    "timeout",
                    "loaded_libraries",
                    "files",
                    "library_evidence",
                    "reported_instruction_count",
                    "reported_exit_status",
                )
            }
        )
        require(
            record["manifest_sha256"] == sha256(run / "manifest.json")
            and record["binding"] == case["binding"]
            and record["id"] == case["id"],
            "case/input/manifest hash binding mismatch",
        )
        require(
            record["command"] == case["command"] and record["cwd"] == str(directory),
            "execution command/cwd mismatch",
        )
        require(not record["timeout"], "case timed out")
        require(record["return_code"] == 0, f"friscv return code {record['return_code']}")
        stem = Path(TEMPLATES[case["kind"]]).stem + ".Default"
        expected_files = {"command.log", "sim.log", stem + ".ELF", stem + ".S"}
        require(set(record["files"]) == expected_files, "missing expected output metadata")
        for name, info in record["files"].items():
            path = directory / name
            require(
                info["exists"] and info["size"] > 0 and path.is_file(), f"missing/empty {name}"
            )
            require(
                path.stat().st_size == info["size"] and sha256(path) == info["sha256"],
                f"artifact hash mismatch: {name}",
            )
        with (directory / (stem + ".ELF")).open("rb") as stream:
            require(stream.read(4) == b"\x7fELF", "invalid ELF output")
        log = (directory / "command.log").read_text(errors="strict")
        loaded = sorted(set(re.findall(r"calling init:\s*(/[^\r\n]+)", log)))
        require(loaded == record["loaded_libraries"], "loader evidence mismatch")
        for name in ("handcar", "ptg"):
            require(str(run / manifest[name]) in loaded, f"wrong/missing actual {name} library")
            require(
                record["library_evidence"][name]
                == {
                    "path": str(run / manifest[name]),
                    "sha256": sha256(run / manifest[name]),
                    "loaded": True,
                },
                f"{name} loaded hash binding mismatch",
            )
        dlls = re.findall(r"Simulator DLL: '([^']+)'", log)
        require(dlls == [str(run / manifest["handcar"])], "wrong Simulator DLL path")
        require(
            re.findall(r"Initial seed = (0x[0-9a-fA-F]+)", log) == [hex(case["seed"])],
            "seed/log binding mismatch",
        )
        require(
            f'Generating using test template "{run / case["template"]}"' in log
            and f"Loading config file: {run / manifest['config']} ..." in log,
            "template/config log binding mismatch",
        )
        result.update(audit_semantics(case["kind"], (directory / "sim.log").read_text(), log))
        result["passed"] = True
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        result["failures"].append(str(error))
    return result


def audit_run(run, requested=None):
    run = run.expanduser().resolve()
    results = {
        "schema": 1,
        "passed": False,
        "audited_at": time.time(),
        "failures": [],
        "cases": [],
        "auditor_sha256": sha256(__file__),
    }
    try:
        manifest = json.loads((run / "manifest.json").read_text())
        receipts = json.loads((run / "receipts.json").read_text())
        require(
            manifest["schema"] == 1 and manifest["run_dir"] == str(run),
            "unsupported manifest or relocated run (absolute paths are bound)",
        )
        require(
            receipts["manifest_sha256"] == sha256(run / "manifest.json"), "manifest hash mismatch"
        )
        expected = case_matrix(manifest["profile"], manifest["seeds"])
        require(
            [{k: c[k] for k in ("id", "kind", "seed")} for c in manifest["cases"]] == expected,
            "incomplete/duplicate profile case matrix",
        )
        require(
            [r["id"] for r in receipts["cases"]] == [c["id"] for c in expected],
            "missing/duplicate execution receipts",
        )
        for case in manifest["cases"]:
            unbound = {key: value for key, value in case.items() if key != "binding"}
            require(
                case["binding"]
                == digest_json(
                    {
                        "run_id": manifest["run_id"],
                        "case": unbound,
                        "inputs": manifest["inputs"],
                        "env": manifest["environment"],
                    }
                ),
                "case binding digest mismatch",
            )
        for name, info in manifest["inputs"].items():
            path = run / name
            require(path.resolve().is_relative_to(run / "inputs"), "input path escapes archive")
            require(sha256(path) == info["sha256"], f"input hash mismatch: {name}")
            if "live_absolute" in info:
                require(
                    sha256(info["live_absolute"]) == info["sha256"],
                    f"absolute XML dependency changed: {info['live_absolute']}",
                )
        require(
            (run / manifest["config"]).read_bytes()
            == derive_config(
                (run / "inputs/source.config").read_bytes(), run / manifest["handcar"]
            ),
            "derived config changed beyond simulator_shared_object",
        )
        if requested:
            for name, path in (("handcar", requested.handcar_so), ("ptg", requested.ptg_lib)):
                if path:
                    require(
                        sha256(path.expanduser().resolve()) == sha256(run / manifest[name]),
                        f"requested {name} hash differs from archived run",
                    )
        for case, receipt in zip(manifest["cases"], receipts["cases"]):
            results["cases"].append(audit_case(run, manifest, case, receipt))
        results["passed"] = bool(results["cases"]) and all(c["passed"] for c in results["cases"])
    except (OSError, ValueError, KeyError, TypeError, IndexError, ET.ParseError) as error:
        results["failures"].append(str(error))
    write_json(run / "results.json", results)
    passed = sum(c["passed"] for c in results["cases"])
    summary = [
        "# Hypervisor M1 Acceptance",
        "",
        f"Status: {'PASS' if results['passed'] else 'FAIL'}",
        f"Cases: {passed}/{len(results['cases'])}",
        "",
        "Evidence is generation-time Handcar, not standalone ELF replay. Instruction counts",
        "are recorded for trace integrity, not a fixed semantic acceptance threshold.",
        "",
        "| Case | Status | Instructions | RC | Timeout | Failure |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case in results["cases"]:
        summary.append(
            f"| {case['id']} | {'PASS' if case['passed'] else 'FAIL'} | "
            f"{case.get('instruction_count', case.get('reported_instruction_count', ''))} | "
            f"{case.get('return_code', '')} | "
            f"{case.get('timeout', '')} | {'; '.join(case['failures'])} |"
        )
    summary.extend(
        ["", *results["failures"], "", "See each case's command.log, sim.log and execution.json."]
    )
    (run / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return results


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.audit_only:
            run = args.audit_only.resolve()
            results = audit_run(run, args)
        else:
            paths, dependencies = preflight(args)
            if args.preflight:
                print(
                    json.dumps(
                        {
                            "preflight": "PASS",
                            "python": sys.executable,
                            "inputs": {
                                k: {"path": str(p), "sha256": sha256(p)} for k, p in paths.items()
                            },
                            "xml_dependencies": len(dependencies),
                        },
                        indent=2,
                    )
                )
                return 0
            run, manifest, env = prepare_run(args, paths, dependencies)
            print(f"Artifacts: {run}", flush=True)
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
                receipts = list(
                    executor.map(lambda c: run_case(run, manifest, c, env), manifest["cases"])
                )
            write_json(
                run / "receipts.json",
                {"manifest_sha256": sha256(run / "manifest.json"), "cases": receipts},
            )
            results = audit_run(run)
        print(f"{'PASS' if results['passed'] else 'FAIL'}: {run / 'summary.md'}")
        return 0 if results["passed"] else 1
    except (OSError, ValueError, subprocess.SubprocessError, ET.ParseError) as error:
        print(f"Preflight/runner error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
