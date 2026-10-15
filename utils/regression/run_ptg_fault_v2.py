#!/usr/bin/env python3
"""Run the PTG Fault Injection V2 ctypes and Handcar regression matrix."""

import argparse
import copy
import hashlib
import json
import os
import pprint
import re
import runpy
import shlex
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from ptg_replay_audit import audit_case


EXPECTED_TASKS = 330
DEFAULT_SEEDS = ("0x15c0ffee", "0x5eed1234", "0xc001d00d")


def _seed_value(value):
    try:
        seed = int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError("seed must be an integer") from error
    if not 0 <= seed <= 0xFFFFFFFFFFFFFFFF:
        raise argparse.ArgumentTypeError("seed must fit in 64 bits")
    return hex(seed)


def _parse_args(argv=None):
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--friscv", type=Path, default=repo_root / "bin/friscv")
    parser.add_argument("--fpix-bin", type=Path, default=repo_root / "fpix/bin/fpix_riscv")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=repo_root / "output" / "ptg_fault_v2",
        help="parent of a unique run directory containing configs, logs and manifest.json",
    )
    parser.add_argument(
        "--handcar-so",
        type=Path,
        default=repo_root / "utils/handcar/handcar_cosim.so",
        help="Handcar library for BOTH generation and standalone ISS (default: installed library)",
    )
    parser.add_argument(
        "--generator-config",
        type=Path,
        default=repo_root / "config/riscv_rv64_twostage.config",
        help="base FORCE XML; only simulator_shared_object is replaced in the run copy",
    )
    parser.add_argument(
        "--fpix-config",
        type=Path,
        default=repo_root / "fpix/config/riscv_rv64_hypervisor.config",
        help="base standalone FPIX XML; other settings, including ISA, are preserved",
    )
    parser.add_argument(
        "--ptg-lib",
        type=Path,
        help="libptg.so path; defaults to PTG_LIB_PATH or a known build location",
    )
    parser.add_argument(
        "--seed",
        action="append",
        type=_seed_value,
        help="deterministic FORCE seed; repeat to run multiple seeds (default: {})".format(
            ", ".join(DEFAULT_SEEDS)
        ),
    )
    return parser.parse_args(argv)


def _resolve_ptg_lib(repo_root, requested_path):
    candidates = []
    if requested_path is not None:
        candidates.append(requested_path)
    elif os.environ.get("PTG_LIB_PATH"):
        candidates.append(Path(os.environ["PTG_LIB_PATH"]))
    else:
        candidates.extend(
            (
                repo_root / "3rd_party" / "page_table_generator" / "build" / "libptg.so",
                repo_root.parent / "page_table_generator" / "build" / "libptg.so",
            )
        )

    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_file():
            return resolved

    searched = ", ".join(str(path) for path in candidates) or "no path supplied"
    raise FileNotFoundError("Unable to locate libptg.so; checked: " + searched)


def _regression_env(repo_root, ptg_lib):
    env = os.environ.copy()
    env["FORCE_PATH"] = str(repo_root)
    env["FPIX_PATH"] = str(repo_root / "fpix")
    env["PTG_LIB_PATH"] = str(ptg_lib)
    interpreter_dir = str(Path(sys.executable).parent)
    existing_path = env.get("PATH")
    path_values = [interpreter_dir]
    if existing_path:
        path_values.extend(
            path for path in existing_path.split(os.pathsep) if path != interpreter_dir
        )
    env["PATH"] = os.pathsep.join(path_values)
    force_paths = (
        repo_root / "3rd_party" / "py",
        repo_root / "utils",
        repo_root / "utils" / "builder",
        repo_root / "utils" / "builder" / "test_builder",
        repo_root / "utils" / "builder" / "shared",
        repo_root / "utils" / "regression",
    )
    existing = env.get("PYTHONPATH")
    values = [str(path) for path in force_paths]
    if existing:
        values.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(values)
    return env


def _check_regression_prerequisites(repo_root, handcar_so, friscv=None, fpix=None):
    required_paths = (
        friscv or repo_root / "bin" / "friscv",
        repo_root / "bin" / "SimApiHANDCAR.so",
        fpix or repo_root / "fpix" / "bin" / "fpix_riscv",
        handcar_so,
        repo_root / "utils" / "regression" / "seedgen" / "bin" / "seedgen.so",
    )
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        raise RuntimeError(
            "Missing regression prerequisites: "
            + ", ".join(missing)
            + ". See docs/HYPERVISOR_WORKFLOW_GUIDE.md for targeted FORCE/seedgen builds. "
            "Do not run root make tests: it deletes output/."
        )
    for executable in (required_paths[0], required_paths[2]):
        if not os.access(str(executable), os.X_OK):
            raise RuntimeError("Regression binary is not executable: " + str(executable))


def _file_record(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest(), "size": path.stat().st_size}


def _source_record(path):
    # This describes the checkout at run time, not the library's build provenance.
    record = {"location": str(path)}
    for name, arguments in (
        ("root", ["rev-parse", "--show-toplevel"]),
        ("head", ["rev-parse", "HEAD"]),
        ("status", ["status", "--porcelain=v1", "--untracked-files=normal"]),
    ):
        command = ["git", "-C", str(path)] + arguments
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
        )
        record[name] = {
            "command": command,
            "return_code": result.returncode,
            "stdout": result.stdout.rstrip(),
            "stderr": result.stderr.rstrip(),
        }
    record["dirty"] = (
        bool(record["status"]["stdout"]) if record["status"]["return_code"] == 0 else None
    )
    return record


def _prepare_run(repo_root, run_root, generator_config, fpix_config, handcar_so, friscv=None, fpix=None):
    configs = {}
    for name, source in (("generator", generator_config), ("fpix", fpix_config)):
        tree = ET.parse(str(source))
        if name == "fpix":
            isa_node = tree.find("./simulator_config_string")
            isa_options = re.findall(r"--isa=([^\s]+)", isa_node.get("value", "") if isa_node is not None else "")
            if len(isa_options) != 1 or "h" not in isa_options[0].lower().split("_")[0]:
                raise RuntimeError("Hypervisor ELF replay requires an explicit H-enabled FPIX ISA")
        nodes = tree.findall("./simulator_shared_object")
        if len(nodes) != 1:
            raise RuntimeError("Expected one simulator_shared_object in " + str(source))
        nodes[0].set("file", str(handcar_so))
        destination = run_root / (name + ".config")
        tree.write(str(destination), encoding="utf-8", xml_declaration=True)
        configs[name] = destination

    original = repo_root / "tests/riscv/ptg_fault_v2_fctrl.py"
    items = copy.deepcopy(runpy.run_path(str(original))["control_items"])
    if len(items) != EXPECTED_TASKS:
        raise RuntimeError("PTG matrix must contain exactly {} tasks".format(EXPECTED_TASKS))
    for item in items:
        item["fname"] = str((original.parent / item["fname"]).resolve())
        item["generator"]["--cfg"] = str(configs["generator"])
    control = run_root / "ptg_fault_v2_fctrl.py"
    control.write_text("control_items = " + pprint.pformat(items) + "\n", encoding="utf-8")

    workflow_source = repo_root / "utils/regression/config/_riscv_rv64_fcfg.py"
    workflow = runpy.run_path(str(workflow_source))
    sequence = copy.deepcopy(workflow["sequence_app_opts"])
    for name, options in sequence:
        if name == "force":
            options["path"] = str(friscv or repo_root / "bin/friscv")
        elif name == "fpix_riscv":
            options.update(
                {
                    "fpix_path": str(fpix or repo_root / "fpix/bin/fpix_riscv"),
                    "cfg": str(configs["fpix"]),
                    # FpixInit validates this even though FpixExecutor ignores it.
                    "iss_so_path": str(handcar_so),
                }
            )
    workflow_path = run_root / "ptg_fault_v2_fcfg.py"
    workflow_path.write_text(
        "master_config = {}\nsequence_app_opts = {}\nsingle_run_app_opts = {}\n".format(
            repr(workflow["master_config"]),
            pprint.pformat(sequence),
            pprint.pformat(workflow["single_run_app_opts"]),
        ),
        encoding="utf-8",
    )
    return control, workflow_path, configs


def _check_loaded_libraries(loader_root, handcar_so, repo_root, friscv=None, fpix=None):
    programs = {
        str(friscv or repo_root / "bin/friscv"): "generation",
        str(fpix or repo_root / "fpix/bin/fpix_riscv"): "standalone_iss",
    }
    evidence = {"generation": [], "standalone_iss": [], "errors": []}
    for log in sorted(loader_root.glob("trace.*")):
        text = log.read_text(encoding="utf-8", errors="replace")
        program = re.search(r"initialize program:\s*([^\n]+)", text)
        if program is None or program.group(1).strip() not in programs:
            continue
        stage = programs[program.group(1).strip()]
        initialized = re.findall(r"calling init:\s*([^\n]+)", text)
        initialized = [path.strip() for path in initialized]
        loaded = str(handcar_so) in initialized
        evidence[stage].append(
            {"log": _file_record(log), "selected_loaded": loaded, "initialized": initialized}
        )
        if not loaded:
            evidence["errors"].append("Selected Handcar was not initialized: " + str(log))
        for path in initialized:
            if Path(path).name == "handcar_cosim.so" and Path(path).resolve() != handcar_so:
                evidence["errors"].append("Unexpected installed Handcar loaded: " + path)
    for stage in ("generation", "standalone_iss"):
        if len(evidence[stage]) != EXPECTED_TASKS:
            evidence["errors"].append(
                "Expected {} {} loader records, found {}".format(
                    EXPECTED_TASKS, stage, len(evidence[stage])
                )
            )
    return evidence


def _run_logged(command, cwd, env, log_path):
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            log_file.write(line)
        return process.wait()


def _check_summary(summary_path, started_at):
    if not summary_path.is_file() or summary_path.stat().st_mtime < started_at:
        raise RuntimeError("master_run did not produce a current summary: " + str(summary_path))

    summary = summary_path.read_text(encoding="utf-8")
    expected_counts = {
        "Generate": EXPECTED_TASKS,
        "Generate Fails": 0,
        "ISS Sim": EXPECTED_TASKS,
        "ISS Sim Fails": 0,
        "Total Tasks": EXPECTED_TASKS,
        "Task Fails": 0,
    }
    for label, expected in expected_counts.items():
        match = re.search(r"^{}\s*:\s*(\d+)\s*$".format(re.escape(label)), summary, re.MULTILINE)
        if match is None:
            raise RuntimeError("Unable to parse '{}' from {}".format(label, summary_path))
        actual = int(match.group(1))
        if actual != expected:
            raise RuntimeError(
                "Expected {} {} entries, summary reports {}".format(expected, label, actual)
            )
    return expected_counts


def main(argv=None):
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    artifact_root = args.artifact_root.expanduser().resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="run_", dir=str(artifact_root)))
    seeds = []
    for seed in args.seed or DEFAULT_SEEDS:
        if seed not in seeds:
            seeds.append(seed)

    manifest = {
        "argv": list(sys.argv if argv is None else [str(Path(__file__).resolve())] + argv),
        "run_root": str(run_root),
        "started_at": time.time(),
        "seeds": seeds,
        "tasks_per_seed": EXPECTED_TASKS,
        "commands": [],
        "results": [],
        "failures": [],
        "return_code": 2,
    }
    manifest_path = run_root / "manifest.json"

    def save_manifest():
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def execute(command, env, log_path):
        record = {
            "argv": command,
            "shell_command": " ".join(shlex.quote(part) for part in command),
            "cwd": str(repo_root),
            "log": str(log_path),
            "started_at": time.time(),
            "return_code": None,
            "loader_debug": env.get("LD_DEBUG"),
            "loader_output": env.get("LD_DEBUG_OUTPUT"),
        }
        manifest["commands"].append(record)
        save_manifest()
        record["return_code"] = _run_logged(command, repo_root, env, log_path)
        record["finished_at"] = time.time()
        save_manifest()
        return record["return_code"]

    print("Run directory: {}".format(run_root))
    try:
        # Existing regression executors build unquoted command strings.
        for path in (run_root, repo_root):
            if re.search(r"[\s'\"%]", str(path)):
                raise RuntimeError(
                    "Regression command paths cannot contain whitespace/quotes/%: " + str(path)
                )
        ptg_lib = _resolve_ptg_lib(repo_root, args.ptg_lib)
        handcar_so = args.handcar_so.expanduser().resolve()
        generator_config = args.generator_config.expanduser().resolve()
        fpix_config = args.fpix_config.expanduser().resolve()
        friscv = args.friscv.expanduser().resolve()
        fpix = args.fpix_bin.expanduser().resolve()
        for executable in (friscv, fpix):
            if re.search(r"[\s'\"%]", str(executable)):
                raise RuntimeError("Regression executable path is not shell-safe: " + str(executable))
        _check_regression_prerequisites(repo_root, handcar_so, friscv, fpix)
        manifest["sources"] = {
            "force": _source_record(repo_root),
            "ptg_library_checkout": _source_record(ptg_lib.parent),
            "handcar_library_checkout": _source_record(handcar_so.parent),
        }
        manifest["source_note"] = (
            "Checkout state observed at run time, not proof of build provenance."
        )
        inputs = {
            "ptg_lib": ptg_lib,
            "handcar_so": handcar_so,
            "generator_config": generator_config,
            "fpix_config": fpix_config,
            "force": friscv,
            "fpix": fpix,
            "replay_auditor": repo_root / "utils/regression/ptg_replay_audit.py",
            "trace_parser": repo_root / "utils/regression/run_hypervisor_m1.py",
            "fpix_executor": repo_root / "utils/regression/applications/fpix_riscv/FpixExecutor.py",
            "sim_api": repo_root / "bin/SimApiHANDCAR.so",
            "seedgen": repo_root / "utils/regression/seedgen/bin/seedgen.so",
            "runner": Path(__file__).resolve(),
            "ctypes_test": repo_root / "tests/riscv/ptg_fault_v2_ctypes_test.py",
            "control": repo_root / "tests/riscv/ptg_fault_v2_fctrl.py",
            "workflow": repo_root / "utils/regression/config/_riscv_rv64_fcfg.py",
        }
        api_node = ET.parse(generator_config).find("./simulator_api_module")
        if api_node is not None:
            api_path = Path(api_node.get("file"))
            inputs["sim_api"] = api_path if api_path.is_absolute() else repo_root / api_path
        manifest["inputs"] = {name: _file_record(path) for name, path in inputs.items()}
        control, workflow, configs = _prepare_run(
            repo_root, run_root, generator_config, fpix_config, handcar_so, friscv, fpix
        )
        manifest["generated"] = {
            name: _file_record(path)
            for name, path in dict(configs, control=control, workflow=workflow).items()
        }
        env = _regression_env(repo_root, ptg_lib)
        manifest["environment"] = {
            key: env.get(key)
            for key in (
                "PATH",
                "PYTHONPATH",
                "PTG_LIB_PATH",
                "LD_LIBRARY_PATH",
                "LD_PRELOAD",
                "PYTHONHOME",
                "FORCE_PATH",
                "FPIX_PATH",
                "ISS_SO_PATH",
            )
        }
        print("PTG library: {}\nHandcar library (both stages): {}".format(ptg_lib, handcar_so))
        if (
            execute(
                [sys.executable, "tests/riscv/ptg_fault_v2_ctypes_test.py"],
                env,
                run_root / "ctypes.log",
            )
            != 0
        ):
            manifest["failures"].append("PTG Fault V2 ctypes/ABI preflight failed")
            manifest["return_code"] = 1
            return 1

        for seed in seeds:
            seed_root = run_root / "seed_{}".format(seed[2:])
            loader_root = seed_root / "loader"
            loader_root.mkdir(parents=True)
            seed_env = env.copy()
            # glibc records library initialization during dlopen, not just config intent.
            seed_env.update({"LD_DEBUG": "libs", "LD_DEBUG_OUTPUT": str(loader_root / "trace")})
            master_command = [
                sys.executable,
                "utils/regression/master_run.py",
                "-f",
                str(control),
                "-c",
                str(workflow),
                "--target-dir",
                str(seed_root),
                "--seed",
                seed,
                "-k",
                "all",
            ]
            started_at = time.time()
            return_code = execute(master_command, seed_env, seed_root / "master_run.log")
            summary_path = seed_root / "output/regression/regression_summary.log"
            result = {"seed": seed, "return_code": return_code, "summary_path": str(summary_path)}
            manifest["results"].append(result)
            if return_code != 0:
                manifest["failures"].append("{}: master_run exited {}".format(seed, return_code))
            if summary_path.is_file():
                result["summary"] = _file_record(summary_path)
                result["summary_text"] = summary_path.read_text(encoding="utf-8")
            try:
                result["counts"] = _check_summary(summary_path, started_at)
            except RuntimeError as error:
                manifest["failures"].append("{}: {}".format(seed, error))
            result["load_evidence"] = _check_loaded_libraries(loader_root, handcar_so, repo_root, friscv, fpix)
            manifest["failures"].extend(
                "{}: {}".format(seed, error) for error in result["load_evidence"]["errors"]
            )
            result["replay_audits"] = []
            cases = sorted((seed_root / "output/regression").glob("*/00000"))
            if len(cases) != EXPECTED_TASKS:
                manifest["failures"].append(f"{seed}: expected {EXPECTED_TASKS} task directories")
            for case in cases:
                try:
                    result["replay_audits"].append(audit_case(case))
                except (OSError, ValueError) as error:
                    manifest["failures"].append(f"{seed}: {case.parent.name}: {error}")
            save_manifest()

        manifest["inputs_after"] = {name: _file_record(path) for name, path in inputs.items()}
        for name, before in manifest["inputs"].items():
            if before != manifest["inputs_after"][name]:
                manifest["failures"].append("Input changed during run: " + name)
        manifest["return_code"] = 1 if manifest["failures"] else 0
        if not manifest["failures"]:
            print(
                "PTG Fault Injection V2 regression: PASS ({} seeds, {} tasks)".format(
                    len(seeds), len(seeds) * EXPECTED_TASKS
                )
            )
        return manifest["return_code"]
    except (OSError, RuntimeError, ValueError, ET.ParseError) as error:
        manifest["failures"].append(str(error))
        return manifest["return_code"]
    finally:
        manifest["finished_at"] = time.time()
        save_manifest()
        for failure in manifest["failures"]:
            print("ERROR: {}".format(failure), file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
