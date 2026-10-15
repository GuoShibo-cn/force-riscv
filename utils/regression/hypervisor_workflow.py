#!/usr/bin/env python3.12
"""Compose existing Hypervisor checks without building or installing dependencies.

quick: tool unit tests, M1 preflight and 3 smoke cases (NOT full acceptance).
m1: M1 preflight and the default 106-case matrix.
full: quick checks, the 106-case matrix, and Fault V2's default three seeds
(990 generation tasks and 990 standalone FPIX ISS tasks).
Tool tests may build small temporary fixtures, never the selected libraries.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
UNIT_TESTS = (
    ("handcar/tools", "test_manage.py"),
    ("handcar/tools", "test_upstream.py"),
    ("utils/regression/tests", "test_hypervisor_m1.py"),
    ("utils/regression/tests", "test_ptg_fault_v2_runner.py"),
    ("utils/regression/tests", "test_ptg_replay_audit.py"),
    ("utils/regression/tests", "test_hypervisor_workflow.py"),
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--friscv", type=Path, default=ROOT / "bin/friscv")
    parser.add_argument("--fpix-bin", type=Path, default=ROOT / "fpix/bin/fpix_riscv")
    parser.add_argument("--profile", choices=("quick", "m1", "full"), default="quick")
    parser.add_argument(
        "--handcar-so", type=Path, required=True, help="explicit candidate library"
    )
    parser.add_argument(
        "--ptg-lib", type=Path, required=True, help="explicit libptg.so; no fallback"
    )
    parser.add_argument("--artifact-root", type=Path, default=ROOT / "output/hypervisor_workflow")
    parser.add_argument("--jobs", type=int, default=8, help="M1 case concurrency (default: 8)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=120,
        help="seconds per M1 case and per tool/preflight stage; no regression-wide deadline",
    )
    parser.add_argument("--preflight-only", action="store_true", help="only run M1 preflight")
    parser.add_argument(
        "--m1-config", type=Path, default=ROOT / "config/riscv_rv64_handcar.config"
    )
    parser.add_argument(
        "--generator-config",
        type=Path,
        default=ROOT / "config/riscv_rv64_twostage_handcar.config",
    )
    parser.add_argument("--fpix-config", type=Path, default=ROOT / "fpix/config/riscv_rv64_hypervisor.config")
    args = parser.parse_args(argv)
    if args.jobs < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--jobs and --timeout must be positive and finite")
    return args


def stage_plan(args, run):
    common = ["--handcar-so", str(args.handcar_so), "--ptg-lib", str(args.ptg_lib),
              "--friscv", str(args.friscv.resolve())]
    m1 = [sys.executable, "-u", str(ROOT / "utils/regression/run_hypervisor_m1.py")]
    m1 += common + [
        "--config",
        str(args.m1_config),
        "--jobs",
        str(args.jobs),
        "--timeout",
        str(args.timeout),
    ]
    stages = []
    if not args.preflight_only and args.profile in ("quick", "full"):
        for directory, filename in UNIT_TESTS:
            stages.append(
                (
                    Path(filename).stem,
                    [
                        sys.executable,
                        "-u",
                        "-m",
                        "unittest",
                        "discover",
                        "-s",
                        str(ROOT / directory),
                        "-p",
                        filename,
                        "-v",
                    ],
                    args.timeout,
                )
            )
    stages.append(("preflight", m1 + ["--preflight"], args.timeout))
    if not args.preflight_only:
        if args.profile in ("quick", "full"):
            stages.append(
                (
                    "smoke",
                    m1 + ["--profile", "smoke", "--artifact-root", str(run / "smoke")],
                    None,
                )
            )
        if args.profile in ("m1", "full"):
            stages.append(
                ("m1", m1 + ["--profile", "m1", "--artifact-root", str(run / "m1")], None)
            )
        if args.profile == "full":
            stages.append(
                (
                    "fault_v2",
                    [sys.executable, "-u", str(ROOT / "utils/regression/run_ptg_fault_v2.py")]
                    + common
                    + [
                        "--generator-config",
                        str(args.generator_config),
                        "--fpix-bin",
                        str(args.fpix_bin.resolve()),
                        "--fpix-config",
                        str(args.fpix_config),
                        "--artifact-root",
                        str(run / "fault_v2"),
                    ],
                    None,
                )
            )
            stages.append((
                "ptg_context_contracts",
                [sys.executable, "-u", str(ROOT / "tests/riscv/ptg_vm_context_test.py"), "-v"],
                args.timeout,
            ))
            stages.append((
                "ptg_context",
                [sys.executable, "-u", str(ROOT / "utils/regression/run_ptg_context.py")]
                + common + ["--fpix-bin", str(args.fpix_bin.resolve()),
                            "--config", str(args.m1_config),
                            "--fpix-config", str(args.fpix_config),
                            "--artifact-root", str(run / "contexts")],
                None,
            ))
            stages.append((
                "ptg_cpp_mapper",
                [sys.executable, "-u", str(ROOT / "utils/regression/run_ptg_context.py")]
                + common + ["--scenario", "mapper", "--fpix-bin", str(args.fpix_bin.resolve()),
                            "--config", str(args.m1_config),
                            "--fpix-config", str(args.fpix_config),
                            "--artifact-root", str(run / "cpp_mapper")],
                None,
            ))
    return [
        {
            "name": name,
            "command": command,
            "timeout": timeout,
            "cwd": str(ROOT),
            "log": str(run / "logs" / (name + ".log")),
            "status": "pending",
            "rc": None,
            "duration": 0,
            "run_directories": [],
        }
        for name, command, timeout in stages
    ]


def stop_process_tree(process):
    """Stop only this child's group and observed descendant session leaders on Linux."""
    if process.returncode is not None:
        return
    identities = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            identities[int(entry.name)] = (int(fields[1]), int(fields[2]), fields[19])
        except (OSError, ValueError, IndexError):
            continue
    owned = {process.pid}
    while True:
        children = {pid for pid, (parent, _, _) in identities.items() if parent in owned}
        if children <= owned:
            break
        owned.update(children)
    groups = {
        pid: identities[pid] for pid in owned if pid in identities and identities[pid][1] == pid
    }
    # M1 starts each case in a separate session. Never signal unrelated groups,
    # and verify start times again to avoid targeting a recycled descendant PID.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid, identity in groups.items():
            try:
                fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                if int(fields[2]) == pid and fields[19] == identity[2]:
                    os.killpg(pid, sig)
            except (OSError, ValueError, IndexError):
                continue
        if sig == signal.SIGTERM:
            time.sleep(0.2)
    process.wait()


def run_stage(stage, env):
    started = time.monotonic()
    stage.update(status="running", started_at=time.time())
    try:
        with Path(stage["log"]).open("wb") as log:
            process = subprocess.Popen(
                stage["command"],
                cwd=stage["cwd"],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                stage["rc"] = process.wait(timeout=stage["timeout"])
                stage["status"] = "passed" if stage["rc"] == 0 else "failed"
            except (KeyboardInterrupt, subprocess.TimeoutExpired) as error:
                # Ignore repeated Ctrl-C only while cleaning up this owned tree.
                previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
                try:
                    stop_process_tree(process)
                finally:
                    signal.signal(signal.SIGINT, previous)
                stage["process_rc"] = process.returncode
                stage["status"] = (
                    "interrupted" if isinstance(error, KeyboardInterrupt) else "timeout"
                )
                stage["rc"] = 130 if isinstance(error, KeyboardInterrupt) else 124
    except OSError as error:
        stage.update(status="failed", rc=2, error=str(error))
    finally:
        stage.update(duration=time.monotonic() - started, finished_at=time.time())
        # Preserve runner evidence as-is; only extract its exact directory announcement.
        if Path(stage["log"]).is_file():
            with Path(stage["log"]).open(encoding="utf-8", errors="replace") as log:
                for line in log:
                    match = re.fullmatch(r"(?:Artifacts|Run directory): (/[^\r\n]+)\r?\n?", line)
                    if match and match[1] not in stage["run_directories"]:
                        stage["run_directories"].append(match[1])
    return stage["rc"]


def file_record(path):
    record = {"path": str(path), "sha256": None}
    try:
        with path.open("rb") as stream:
            record["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as error:
        record["error"] = str(error)
    return record


def main(argv=None):
    args = parse_args(argv)
    for name in (
        "friscv",
        "fpix_bin",
        "handcar_so",
        "ptg_lib",
        "artifact_root",
        "m1_config",
        "generator_config",
        "fpix_config",
    ):
        setattr(args, name, getattr(args, name).expanduser().resolve())
    try:
        args.artifact_root.mkdir(parents=True, exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix=args.profile + "-", dir=args.artifact_root))
        (run / "logs").mkdir()
    except OSError as error:
        print(f"Workflow setup error: {error}", file=sys.stderr)
        return 2
    started = time.monotonic()
    libraries = {"handcar_so": args.handcar_so, "ptg_lib": args.ptg_lib}
    configs = {"m1": args.m1_config}
    if args.profile == "full" and not args.preflight_only:
        configs.update(generator=args.generator_config, fpix=args.fpix_config)
    report = {
        "schema": 1,
        "run_dir": str(run),
        "profile": args.profile,
        "preflight_only": args.preflight_only,
        "started_at": time.time(),
        "python": {"executable": sys.executable, "version": sys.version},
        "jobs": args.jobs,
        "timeout": args.timeout,
        "status": "running",
        "rc": None,
        "libraries_before": {},
        "libraries_after": {},
        "input_configs": {},
        "commands": stage_plan(args, run),
        "errors": [],
    }

    def save():
        temporary = run / "workflow.json.tmp"
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(run / "workflow.json")

    print(f"Workflow directory: {run}", flush=True)
    save()
    try:
        report["libraries_before"] = {name: file_record(path) for name, path in libraries.items()}
        report["input_configs"] = {name: file_record(path) for name, path in configs.items()}
        if sys.version_info[:2] != (3, 12):
            raise ValueError("run with Python 3.12")
        if os.environ.get("FORCE_SOURCED") != "True":
            raise ValueError("source setenv.bash from the repo root first")
        if sys.platform != "linux":
            raise ValueError("Linux is required by the existing acceptance runners")
        for record in (*report["libraries_before"].values(), *report["input_configs"].values()):
            if "error" in record:
                raise ValueError(record["error"])
        if args.profile in ("quick", "full") and not args.preflight_only:
            for directory, filename in UNIT_TESTS:
                if not (ROOT / directory / filename).is_file():
                    raise ValueError(f"Missing required unit test: {directory}/{filename}")
        env = os.environ.copy()
        env.update(
            PTG_LIB_PATH=str(args.ptg_lib),
            FORCE_PATH=str(ROOT),
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONUNBUFFERED="1",
        )
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        for stage in report["commands"]:
            stage["status"] = "running"
            save()
            print(f"Stage: {stage['name']} (log: {stage['log']})", flush=True)
            rc = run_stage(stage, env)
            save()
            if rc != 0:
                report.update(status=stage["status"], rc=rc if rc > 0 else 128 - rc)
                break
        else:
            report.update(status="passed", rc=0)
    except KeyboardInterrupt:
        report.update(status="interrupted", rc=130)
    except (OSError, ValueError) as error:
        report.update(status="failed", rc=2)
        report["errors"].append(str(error))
    finally:
        report["libraries_after"] = {name: file_record(path) for name, path in libraries.items()}
        for name, before in report["libraries_before"].items():
            if before != report["libraries_after"][name]:
                report["errors"].append(f"Library changed during workflow: {name}")
                if report["rc"] == 0:
                    report.update(status="failed", rc=1)
        for stage in report["commands"]:
            if stage["status"] == "pending":
                stage["status"] = "skipped"
            elif stage["status"] == "running":
                stage.update(status=report["status"], rc=report["rc"])
        report.update(duration=time.monotonic() - started, finished_at=time.time())
        save()
    for error in report["errors"]:
        print(error, file=sys.stderr)
    scope = "preflight-only" if args.preflight_only else args.profile
    print(f"{scope}: {report['status']} (rc={report['rc']}): {run / 'workflow.json'}", flush=True)
    return report["rc"]


if __name__ == "__main__":
    sys.exit(main())
