#!/usr/bin/env python3
"""Freeze and build local Handcar inputs; installation requires M1 acceptance.

Linux/glibc, native LP64 and Python 3.12 (for the M1 auditor) are required.
Snapshots include generated instruction sources, not a regeneration recipe.
No upstream Git identity is inferred from the enclosing FORCE repository.
"""

import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
DEPENDENCY = ROOT / "handcar/dependency.json"
LOCK = "local-source-lock.json"
RECIPE = "standalone-v2-gnu20-v1"
CALLBACKS = {"update_generator_memory", "update_generator_register"}
# Optional GCC/libstdc++ transaction hooks and C SoftFloat TLS initializers.
WEAK = {
    "_ITM_RU1",
    "_ITM_RU8",
    "_ITM_addUserCommitAction",
    "_ITM_deregisterTMCloneTable",
    "_ITM_memcpyRnWt",
    "_ITM_memcpyRtWn",
    "_ITM_registerTMCloneTable",
    "_ZGTtdlPv",
    "_ZGTtnam",
    "_ZTH22softfloat_roundingMode",
    "_ZTH24softfloat_exceptionFlags",
    "__cxa_pure_virtual",
    "__gmon_start__",
}
CXXFLAGS = shlex.split(
    "-std=gnu++20 -fPIC -O2 -Wall -Wno-unused -Wno-sign-compare "
    "-Wno-strict-aliasing -DRISCV_ENABLE_MISALIGNED -DHAVE_CONFIG_H -DHAVE_INT128 "
    "-Wno-narrowing -D_GNU_SOURCE -include sys/syscall.h"
)
CFLAGS = ["-std=c99", "-fPIC", "-O2", "-DHAVE_CONFIG_H"]
ABI = {
    "headers/handcar_cosim_wrapper.h": "handcar/headers/handcar_cosim_wrapper.h",
    "force-abi/handcar_cosim_wrapper.h": "utils/handcar/handcar_cosim_wrapper.h",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".manifest-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def targets():
    return {
        name: ROOT / directory / "handcar_cosim.so"
        for name, directory in (("utils", "utils/handcar"), ("bin", "bin"))
    }


def overlap(a, b):
    return a == b or a in b.parents or b in a.parents


def no_symlinks(path):
    path = Path(os.path.abspath(path.expanduser()))
    require(not any(p.is_symlink() for p in (path, *path.parents)), f"symlink path: {path}")
    return path


def output_path(path, protected=()):
    path = no_symlinks(path)
    for other in (*protected, *[p.parent for p in targets().values()]):
        require(not overlap(path, other.resolve()), f"unsafe output overlap: {path} / {other}")
    require(not path.exists(), f"output must be new, even an empty directory is refused: {path}")
    require(path.parent.is_dir(), f"output parent must already exist: {path.parent}")
    return path


def checked_copy(source, target):
    before = sha256(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    require(sha256(target) == before == sha256(source), f"input changed during copy: {source}")
    return before


def source_files(source):
    """Select inputs by type, never caches/binaries or build scripts."""
    files = {}
    for directory in (
        "riscv",
        "fesvr",
        "disasm",
        "softfloat",
        "fdt",
        "spike_main",
        "build",
        "debug_rom",
    ):
        base = source / directory
        require(base.is_dir() and not base.is_symlink(), f"missing/linked source dir: {base}")
        for current, dirs, names in os.walk(base):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
            if directory == "build":
                dirs[:] = []
            for subdir in dirs:
                require(not (Path(current) / subdir).is_symlink(), "linked source directories")
            for name in sorted(names):
                path = Path(current) / name
                if path.suffix not in (".cc", ".c", ".h", ".hpp", ".inc", ".def"):
                    continue
                require(path.is_file(), f"missing input: {path}")
                require(source in path.resolve().parents, f"input symlink escapes source: {path}")
                files[str(path.relative_to(source))] = path
    for name in (
        "config.h",
        "config.h.in",
        "configure",
        "configure.ac",
        "aclocal.m4",
        "Makefile.in",
        "VERSION",
        "LICENSE",
    ):
        path = source / name
        if path.is_file():
            require(source in path.resolve().parents, f"input escapes source: {path}")
            files[name] = path
    for name in (
        "config.h",
        "riscv/processor.cc",
        "build/insn_list.h",
        "spike_main/spike_lib.cc",
        "debug_rom/debug_rom.h",
    ):
        require(name in files, f"missing required input: {name}")
    require(
        any(n.startswith("build/") and n.endswith(".cc") for n in files),
        "missing generated instruction sources",
    )
    for name, original in ABI.items():
        local = source / name
        files[name] = local if local.is_file() else ROOT / original
        require(files[name].is_file(), f"missing ABI header: {files[name]}")
    return dict(sorted(files.items()))


def verify_source(source):
    source = source.expanduser().resolve(strict=True)
    lock = json.loads((source / LOCK).read_text())
    require(lock["schema"] == 1 and lock["recipe"] == RECIPE, "unsupported source lock")
    require(
        lock["upstream"] == {"status": "unknown", "remote": None, "revision": None},
        "local snapshot must not claim an upstream revision",
    )
    require(lock["snapshot_sha256"] == digest_json(lock["files"]), "snapshot digest mismatch")
    actual = {}
    for path in source.rglob("*"):
        require(not path.is_symlink(), f"snapshot must be self-contained: {path}")
        if path.is_file() and path != source / LOCK:
            actual[str(path.relative_to(source))] = sha256(path)
    require(actual == lock["files"], "snapshot input hashes/file set mismatch")
    require(set(source_files(source)) == set(actual), "snapshot input selection mismatch")
    require(lock["abi_headers"] == {name: actual[name] for name in ABI}, "ABI lock mismatch")
    return lock


def snapshot(source, output):
    source = source.expanduser().resolve(strict=True)
    output = output_path(output, (source, ROOT / "handcar"))
    old = verify_source(source) if (source / LOCK).exists() else None
    files = source_files(source)
    require(
        shutil.disk_usage(output.parent).free
        > sum(p.stat().st_size for p in files.values()) + 16 * 1024**2,
        "insufficient snapshot disk space",
    )
    output.mkdir()
    hashes = {name: checked_copy(path, output / name) for name, path in files.items()}
    require(
        {name: sha256(path) for name, path in source_files(source).items()} == hashes,
        "source changed during snapshot",
    )
    if old:
        require(old["files"] == hashes, "locked source changed during snapshot")
    lock = {
        "schema": 1,
        "recipe": RECIPE,
        "created_at": time.time(),
        "source_dir": str(source),
        "upstream": {"status": "unknown", "remote": None, "revision": None},
        "provenance": "Local effective source snapshot; not source regeneration or a Git pin.",
        "files": hashes,
        "snapshot_sha256": digest_json(hashes),
        "abi_headers": {name: hashes[name] for name in ABI},
        "manager_sha256": sha256(__file__),
        "dependency_sha256": sha256(DEPENDENCY),
    }
    write_json(output / LOCK, lock)
    verify_source(output)
    return lock


def environment():
    require(os.environ.get("FORCE_SOURCED") == "True", "source setenv.bash first")
    require(
        sys.platform == "linux" and platform.libc_ver()[0] == "glibc", "Linux/glibc is required"
    )
    # Drop compiler/loader injection variables and implicit include paths.
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C", "HOME": "/nonexistent"}


def run(command, env, cwd, log=None, input_text=None):
    result = subprocess.run(
        command, cwd=cwd, env=env, input=input_text, capture_output=True, text=True, timeout=600
    )
    if log:
        log.write("$ " + shlex.join(command) + "\n" + result.stdout + result.stderr)
        log.flush()
    require(
        result.returncode == 0,
        f"tool failed ({result.returncode}): {shlex.join(command)}\n"
        + result.stdout
        + result.stderr,
    )
    return result.stdout + result.stderr


def validate_library(library, env, cwd, log=None):
    """Require successful nm and resolution of every non-host relocation."""
    nm = run(["nm", "-D", "--undefined-only", "--format=posix", str(library)], env, cwd, log)
    undefined = {}
    for line in nm.splitlines():
        fields = line.split()
        require(len(fields) >= 2 and fields[1] in ("U", "w", "v"), "unparseable nm output")
        name, kind = fields[:2]
        undefined[name] = kind
        require(
            "@" in name or name in CALLBACKS or (kind in ("w", "v") and name in WEAK),
            f"unexpected undefined symbol: {name}",
        )
    require(bool(undefined), "empty nm undefined-symbol report")
    report = run(["ldd", "-r", str(library)], env, cwd, log)
    require("not found" not in report and "=> /" in report, "missing runtime dependencies")
    for line in report.splitlines():
        if "undefined symbol:" in line:
            match = re.fullmatch(r"\s*undefined symbol: (\S+)\s+\((.+)\)", line)
            require(
                match is not None
                and match[1] in CALLBACKS
                and Path(match[2]).resolve() == library.resolve(),
                f"unresolved relocation: {line}",
            )
        else:
            require(
                re.fullmatch(
                    r"\s*(?:\S+ => /.+|/\S+|linux-vdso\.so\.\d+) " r"\(0x[0-9a-f]+\)\s*", line
                )
                is not None,
                f"unexpected ldd diagnostic: {line}",
            )
    runtime = {}
    for name in re.findall(r"(?:=>\s+|^\s*)(/\S+)\s+\(0x", report, re.M):
        runtime[name] = sha256(name)
    return {"undefined": undefined, "ldd": report, "runtime_inputs": runtime}


def build(source, output, jobs, cc, cxx):
    require(jobs > 0, "--jobs must be positive")
    source = source.expanduser().resolve(strict=True)
    output = output_path(output, (source, ROOT / "handcar"))
    env = environment()
    tools = {}
    for name, executable in (
        ("cc", cc),
        ("cxx", cxx),
        ("nm", "nm"),
        ("ldd", "ldd"),
        ("dtc", "dtc"),
    ):
        found = shutil.which(executable, path=env["PATH"])
        require(found is not None, f"missing tool: {executable}")
        tools[name] = str(Path(found).resolve())
    require(shutil.disk_usage(output.parent).free > 1024**3, "build needs at least 1 GiB free")
    if (source / LOCK).exists():
        verify_source(source)
    output.mkdir()
    manifest = {
        "schema": 1,
        "recipe": RECIPE,
        "status": "failed",
        "source_dir": str(source),
        "output_dir": str(output),
        "jobs": jobs,
        "environment": env,
        "commands": [],
        "manager_sha256": sha256(__file__),
        "dependency_sha256": sha256(DEPENDENCY),
        "started_at": time.time(),
        "build_log": "build.log",
        "toolchain": {},
    }
    log_path = output / "build.log"
    try:
        lock = snapshot(source, output / "inputs")
        src = output / "inputs"
        manifest.update(
            inputs=lock["files"],
            snapshot_sha256=lock["snapshot_sha256"],
            source_lock_sha256=sha256(src / LOCK),
        )
        for name, original in ABI.items():
            require(
                lock["abi_headers"][name] == sha256(ROOT / original),
                f"snapshot ABI differs from current FORCE: {name}",
            )
        with log_path.open("w") as log:
            for name, tool in tools.items():
                command = [tool, "--version"]
                manifest["commands"].append(command)
                manifest["toolchain"][name] = {
                    "path": tool,
                    "sha256": sha256(tool),
                    "version": run(command, env, output, log),
                }
            for name in ("cc", "cxx"):
                command = [tools[name], "-dumpmachine"]
                manifest["commands"].append(command)
                manifest["toolchain"][name]["target"] = run(command, env, output, log).strip()
            require(
                manifest["toolchain"]["cc"]["target"] == manifest["toolchain"]["cxx"]["target"],
                "C/C++ target ABI mismatch",
            )
            probe = (
                "#include <boost/asio.hpp>\n#include <sys/syscall.h>\n"
                "#include <features.h>\n#include <cstdint>\n"
                "#ifndef __GLIBC__\n#error glibc required\n#endif\n"
                "static_assert(sizeof(void*) == 8 && sizeof(long) == 8);\n"
                "static_assert(sizeof(__int128) == 16);\nint main() { return 0; }\n"
            )
            manifest["abi_probe"] = probe
            command = [
                tools["cxx"],
                *CXXFLAGS,
                "-x",
                "c++",
                "-",
                "-o",
                str(output / "abi-probe"),
                "-lpthread",
                "-ldl",
                "-lutil",
                "-static-libstdc++",
                "-static-libgcc",
            ]
            manifest["commands"].append(command)
            run(command, env, output, log, probe)
            command = [str(output / "abi-probe")]
            manifest["commands"].append(command)
            run(command, env, output, log)
            tool_inputs = {}
            for name, libraries in (
                ("cxx", ("libstdc++.a", "libgcc.a", "libgcc_eh.a", "cc1plus", "collect2")),
                ("cc", ("cc1", "as", "ld", "crtbeginS.o", "crtendS.o")),
            ):
                for library in libraries:
                    flag = (
                        "-print-prog-name="
                        if library in ("cc1plus", "cc1", "collect2", "as", "ld")
                        else "-print-file-name="
                    )
                    command = [tools[name], flag + library]
                    manifest["commands"].append(command)
                    found = run(command, env, output, log).strip()
                    path = Path(shutil.which(found, path=env["PATH"]) or found)
                    require(
                        path.is_absolute() and path.is_file(), f"missing tool input: {library}"
                    )
                    tool_inputs[str(path.resolve())] = sha256(path)
            manifest["toolchain_inputs"] = tool_inputs
            (output / "obj").mkdir()
            (output / "generated").mkdir()
            for name, original in (
                ("processor.cc", "riscv/processor.cc"),
                ("insn_list.h", "build/insn_list.h"),
            ):
                checked_copy(src / original, output / "generated" / name)
            includes = [
                output / "generated",
                src,
                *[src / d for d in ("riscv", "fesvr", "softfloat", "fdt", "disasm", "headers")],
                Path("/usr/include"),
            ]
            commands = []
            for directory, suffix, excluded in (
                ("build", ".cc", ()),
                ("disasm", ".cc", ()),
                ("softfloat", ".c", ()),
                ("fdt", ".c", ()),
                ("riscv", ".cc", ("check-opcode-overlap.t.cc", "insn_template.cc")),
                ("spike_main", ".cc", ()),
                ("fesvr", ".cc", ("elf2hex.cc",)),
            ):
                for path in sorted((src / directory).glob("*" + suffix)):
                    if path.name in excluded or (
                        directory == "spike_main" and path.name != "spike_lib.cc"
                    ):
                        continue
                    prefix = {
                        "build": "insn_",
                        "disasm": "disasm_",
                        "softfloat": "softfloat_",
                        "fdt": "fdt_",
                    }.get(directory, "")
                    obj = output / "obj" / (prefix + path.stem + ".o")
                    require(
                        not any(cmd[-1] == str(obj) for cmd in commands),
                        f"colliding object name: {obj}",
                    )
                    if directory == "riscv" and path.name == "processor.cc":
                        path = output / "generated/processor.cc"
                    flags = (
                        [*CFLAGS, "-I" + str(src / directory)]
                        if suffix == ".c"
                        else [*CXXFLAGS, *["-I" + str(p) for p in includes]]
                    )
                    commands.append(
                        [
                            tools["cc" if suffix == ".c" else "cxx"],
                            *flags,
                            "-MD",
                            "-MF",
                            str(obj.with_suffix(".d")),
                            "-c",
                            str(path),
                            "-o",
                            str(obj),
                        ]
                    )
            manifest["commands"].extend(commands)
            # Capture each command separately to keep diagnostics readable.
            with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
                futures = [executor.submit(run, cmd, env, output) for cmd in commands]
                errors = []
                for cmd, future in zip(commands, futures):
                    try:
                        log.write("$ " + shlex.join(cmd) + "\n" + future.result())
                    except Exception as error:
                        errors.append(str(error))
                        log.write(str(error) + "\n")
                require(not errors, "compile failed: " + "\n".join(errors[:3]))
            deps = {}
            for depfile in sorted((output / "obj").glob("*.d")):
                text = depfile.read_text().replace("\\\n", "")
                for value in shlex.split(text.split(":", 1)[1]):
                    path = Path(value)
                    path = (output / path).resolve() if not path.is_absolute() else path.resolve()
                    require(path.is_file(), f"missing compiler dependency: {path}")
                    if str(path) not in deps:
                        deps[str(path)] = sha256(path)
            manifest["compiler_inputs"] = deps
            library = output / "handcar_cosim.so"
            command = [
                tools["cxx"],
                "-shared",
                "-o",
                str(library),
                *[str(p) for p in sorted((output / "obj").glob("*.o"))],
                "-lpthread",
                "-ldl",
                "-lutil",
                "-static-libstdc++",
                "-static-libgcc",
                "-Wl,-t",
            ]
            manifest["commands"].append(command)
            linked = run(command, env, output, log)
            manifest["linker_inputs"] = {
                str(Path(line).resolve()): sha256(line)
                for line in linked.splitlines()
                if Path(line).is_file()
            }
            manifest["commands"].extend(
                [
                    ["nm", "-D", "--undefined-only", "--format=posix", str(library)],
                    ["ldd", "-r", str(library)],
                ]
            )
            manifest["validation"] = validate_library(library, env, output, log)
            verify_source(src)
            require(all(sha256(p) == h for p, h in deps.items()), "compiler inputs changed")
            require(all(sha256(p) == h for p, h in tool_inputs.items()), "toolchain changed")
            manifest.update(status="passed", library=str(library), library_sha256=sha256(library))
    except Exception as error:
        manifest["error"] = str(error)
        raise
    finally:
        manifest["finished_at"] = time.time()
        if log_path.exists():
            manifest["build_log_sha256"] = sha256(log_path)
        write_json(output / "build.json", manifest)
    return manifest


def acceptance(library, directory):
    """Use the trusted workspace auditor, never execute an archived runner."""
    require(sys.version_info[:2] == (3, 12), "M1 install audit requires Python 3.12")
    directory = no_symlinks(directory).resolve(strict=True)
    manifest = json.loads((directory / "manifest.json").read_text())
    require(
        manifest["schema"] == 1 and manifest["profile"] == "m1" and manifest["seeds"] is None,
        "full default M1 profile required",
    )
    runner = ROOT / "utils/regression/run_hypervisor_m1.py"
    spec = importlib.util.spec_from_file_location("handcar_m1_auditor", runner)
    auditor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auditor)
    expected = auditor.case_matrix("m1")
    require(
        len(expected) == 106
        and [{k: c[k] for k in ("id", "kind", "seed")} for c in manifest["cases"]] == expected,
        "incomplete 106-case M1 matrix",
    )
    for key in ("handcar", "ptg", "friscv", "config"):
        path = no_symlinks(directory / manifest[key])
        require(directory / "inputs" in path.parents, "acceptance input escapes archive")
    for case in manifest["cases"]:
        require(case["id"] in {c["id"] for c in expected}, "unsafe case path")
    archived = directory / manifest["handcar"]
    require(
        sha256(library) == sha256(archived) == manifest["inputs"][manifest["handcar"]]["sha256"],
        "M1 library hash mismatch",
    )
    # audit_run writes reports; reject symlinks before it touches those paths.
    for path in directory.rglob("*"):
        require(not path.is_symlink(), f"symlink in acceptance evidence: {path}")
    result = auditor.audit_run(directory)
    require(
        result["passed"] is True
        and len(result["cases"]) == 106
        and all(c["passed"] is True for c in result["cases"]),
        "M1 re-audit did not pass 106/106",
    )
    return {
        "directory": str(directory),
        "manifest_sha256": sha256(directory / "manifest.json"),
        "results_sha256": sha256(directory / "results.json"),
        "auditor_sha256": sha256(runner),
        "library_sha256": sha256(library),
        "passed": 106,
    }


def atomic_replace(source, target, expected_hash, new_hash, mode):
    no_symlinks(target)
    require(target.is_file() and sha256(target) == expected_hash, f"target changed: {target}")
    fd, temporary = tempfile.mkstemp(prefix=".handcar-", dir=target.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream, source.open("rb") as original:
            shutil.copyfileobj(original, stream)
            stream.flush()
            os.fsync(stream.fileno())
        require(sha256(temporary) == new_hash, "replacement hash mismatch")
        os.chmod(temporary, mode)
        no_symlinks(target)
        require(sha256(target) == expected_hash, f"target changed before replacement: {target}")
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def install(library, acceptance_dir, backup_root, yes, target):
    require(yes, "installation requires --yes")
    env = environment()
    library = no_symlinks(library).resolve(strict=True)
    installed_hash = sha256(library)
    evidence = acceptance(library, acceptance_dir)
    validate_library(library, env, library.parent)
    require(sha256(library) == installed_hash == evidence["library_sha256"], "library changed")
    selected = [targets()["utils"]] if target == "utils" else list(targets().values())
    for path in selected:
        no_symlinks(path)
        require(path.is_file() and path != library, f"invalid installation target: {path}")
        require(
            shutil.disk_usage(path.parent).free > library.stat().st_size + 16 * 1024**2,
            f"insufficient installation disk space: {path.parent}",
        )
    backup_root = no_symlinks(backup_root)
    for path in (
        ROOT / "handcar",
        library.parent,
        acceptance_dir.resolve(),
        *[p.parent for p in targets().values()],
    ):
        require(not overlap(backup_root, path), f"unsafe backup root: {backup_root}")
    require(backup_root.is_dir(), "backup root must already exist")
    require(
        shutil.disk_usage(backup_root).free
        > sum(p.stat().st_size for p in selected) + 16 * 1024**2,
        "insufficient backup space",
    )
    backup = Path(tempfile.mkdtemp(prefix="handcar-install-", dir=backup_root))
    receipt = {
        "schema": 1,
        "state": "prepared",
        "created_at": time.time(),
        "library_sha256": installed_hash,
        "acceptance": evidence,
        "targets": [],
    }
    for index, path in enumerate(selected):
        saved = backup / f"{index}.original.so"
        original_hash = checked_copy(path, saved)
        with saved.open("rb") as stream:
            os.fsync(stream.fileno())
        receipt["targets"].append(
            {
                "target": str(path),
                "backup": saved.name,
                "original_sha256": original_hash,
                "installed_sha256": installed_hash,
                "mode": stat.S_IMODE(path.stat().st_mode),
                "state": "pending",
            }
        )
    receipt_path = backup / "receipt.json"
    write_json(receipt_path, receipt)
    try:
        for entry in receipt["targets"]:
            atomic_replace(
                library,
                Path(entry["target"]),
                entry["original_sha256"],
                installed_hash,
                entry["mode"],
            )
            entry["state"] = "installed"
            write_json(receipt_path, receipt)
        receipt["state"] = "installed"
    except Exception as error:
        receipt["error"] = str(error)
        raise ValueError(f"installation incomplete; rollback receipt: {receipt_path}: {error}")
    finally:
        write_json(receipt_path, receipt)
    return {"receipt": str(receipt_path), "state": receipt["state"]}


def rollback(receipt_path, yes):
    require(yes, "rollback requires --yes")
    receipt_path = no_symlinks(receipt_path).resolve(strict=True)
    receipt = json.loads(receipt_path.read_text())
    require(
        receipt["schema"] == 1 and receipt["state"] in ("prepared", "installed"),
        "invalid/already rolled back receipt",
    )
    entries = receipt["targets"]
    allowed = {str(p) for p in targets().values()}
    require(
        1 <= len(entries) <= 2 and len({e["target"] for e in entries}) == len(entries),
        "invalid receipt targets",
    )
    pending = []
    for entry in entries:
        require(entry["target"] in allowed, "receipt target not an installation path")
        path = no_symlinks(Path(entry["target"]))
        backup = no_symlinks(receipt_path.parent / entry["backup"])
        require(backup.parent == receipt_path.parent, "backup path escapes receipt directory")
        require(sha256(backup) == entry["original_sha256"], "rollback backup hash mismatch")
        require(entry["installed_sha256"] == receipt["library_sha256"], "receipt hash mismatch")
        current = sha256(path)
        if entry["state"] in ("pending", "rolled_back") and current == entry["original_sha256"]:
            continue
        require(
            current == entry["installed_sha256"],
            f"refusing rollback of subsequently modified target: {path}",
        )
        pending.append(entry)
    for entry in pending:
        atomic_replace(
            receipt_path.parent / entry["backup"],
            Path(entry["target"]),
            entry["installed_sha256"],
            entry["original_sha256"],
            entry["mode"],
        )
        entry["state"] = "rolled_back"
        write_json(receipt_path, receipt)
    receipt["state"] = "rolled_back"
    write_json(receipt_path, receipt)
    return {"receipt": str(receipt_path), "state": receipt["state"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("snapshot", "verify-source", "inspect", "build"):
        command = commands.add_parser(name)
        command.add_argument("--source-dir", type=Path, required=True)
        if name in ("snapshot", "build"):
            command.add_argument("--output-dir", type=Path, required=True)
        if name == "build":
            command.add_argument("--jobs", type=int, default=1)
            command.add_argument("--cc", default="gcc")
            command.add_argument("--cxx", default="g++")
    command = commands.add_parser("install")
    command.add_argument("--library", type=Path, required=True)
    command.add_argument("--acceptance-dir", type=Path, required=True)
    command.add_argument("--backup-root", type=Path, required=True)
    command.add_argument("--target", choices=("utils", "both"), default="utils")
    command.add_argument("--yes", action="store_true")
    command = commands.add_parser("rollback")
    command.add_argument("--receipt", type=Path, required=True)
    command.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command in ("verify-source", "inspect"):
            result = verify_source(args.source_dir)
        elif args.command == "snapshot":
            result = snapshot(args.source_dir, args.output_dir)
        elif args.command == "build":
            result = build(args.source_dir, args.output_dir, args.jobs, args.cc, args.cxx)
        elif args.command == "install":
            result = install(
                args.library, args.acceptance_dir, args.backup_root, args.yes, args.target
            )
        else:
            result = rollback(args.receipt, args.yes)
        print(
            json.dumps(
                {
                    k: v
                    for k, v in result.items()
                    if k
                    not in (
                        "files",
                        "inputs",
                        "compiler_inputs",
                        "commands",
                        "linker_inputs",
                        "toolchain_inputs",
                        "validation",
                        "toolchain",
                        "abi_probe",
                    )
                },
                indent=2,
            )
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Handcar management failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
