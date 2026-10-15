#!/usr/bin/env python3
"""Pinned upstream preparation and out-of-tree native builds; never install.

Source setenv.bash before invoking. Output must not exist and its parent must
exist. Paths containing shell/make metacharacters or symlink parents are refused.
Failed output is retained for diagnosis and cannot be reused. No source commits,
index updates, installed-library writes, ignored drivers or frozen-source builds.
The lock and this program are trusted inputs, not a signature/security sandbox.
Do not concurrently modify inputs, output directories or the host toolchain.
"""

import argparse
import hashlib
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

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "handcar/upstream.lock.json"
OFFICIAL = "https://github.com/riscv-software-src/riscv-isa-sim.git"
PIN = "4ffd6ba860f4190ceac2716fa3c2cf139e85538f"
CALLBACKS = {"update_generator_memory", "update_generator_register"}
WEAK = {
    "handcar_trace_trap",
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
ABI_HEADERS = ("headers/handcar_cosim_wrapper.h", "force-abi/handcar_cosim_wrapper.h")
TESTS = ("handcar/tests/upstream_mmu_checks.cc", "handcar/tests/upstream_abi_checks.cc")
LOADER = "utils/handcar/SimLoader.h"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="ascii") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True)
        stream.write("\n")


def safe_path(value):
    path = Path(os.path.abspath(value))
    require(re.fullmatch(r"/[A-Za-z0-9_./+\-]+", str(path)), "unsafe path: " + str(path))
    require(".." not in Path(value).parts, "parent traversal is not allowed")
    for item in (path, *path.parents):
        require(not item.is_symlink(), "symlink path: " + str(item))
    return path


def inside(path, parent):
    return path == parent or parent in path.parents


def new_output(value, protected=()):
    path = safe_path(value)
    require(path.parent.is_dir(), "output parent must exist")
    require(not path.exists(), "output must be new: " + str(path))
    for parent in (*protected, ROOT / "handcar", ROOT / "bin", ROOT / "utils/handcar"):
        require(
            not inside(path, parent) and not inside(parent, path), "output overlaps input/install"
        )
    path.mkdir(mode=0o700)
    return path


def git_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_TERMINAL_PROMPT="0",
        GIT_NO_REPLACE_OBJECTS="1",
        LC_ALL="C",
    )
    return env


def git(args, cwd, env=None):
    command = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.autocrlf=false",
        *map(str, args),
    ]
    result = subprocess.run(
        command, cwd=cwd, env=env or git_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    require(
        result.returncode == 0,
        "git failed: {}\n{}".format(" ".join(command), result.stderr.decode(errors="replace")),
    )
    return result.stdout.decode()


def load_lock():
    lock = json.loads(LOCK.read_text())
    require(lock["schema_version"] == 1, "unsupported lock schema")
    require(lock["upstream"] == {"url": OFFICIAL, "commit": PIN}, "upstream pin/url mismatch")
    require(set(lock["tests"]) == set(TESTS), "locked test set mismatch")
    require(set(lock["consumer_headers"]) == {LOADER}, "locked consumer header set mismatch")
    require(
        lock["patch"]["path"] == "handcar/patches/spike-4ffd6ba-handcar.patch",
        "unexpected patch path",
    )
    inputs = {
        lock["patch"]["path"]: lock["patch"]["sha256"],
        **lock["tests"],
        **lock["consumer_headers"],
    }
    for name, digest in inputs.items():
        path = safe_path(ROOT / name)
        require(re.fullmatch(r"[0-9a-f]{64}", digest), "invalid SHA256: " + name)
        require(path.is_file() and sha256(path) == digest, "input hash mismatch: " + name)
    return lock


def expected_tree(source, lock):
    # A private index/object store prevents validation from writing to the source.
    with tempfile.TemporaryDirectory(prefix="handcar-tree-") as temporary:
        repo = Path(temporary)
        git(["init", "--bare", "--template=", repo], repo)
        env = git_env()
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(source / ".git/objects")
        git(["read-tree", lock["upstream"]["commit"]], repo, env)
        patch = ROOT / lock["patch"]["path"]
        git(["apply", "--cached", "--check", patch], repo, env)
        git(["apply", "--cached", patch], repo, env)
        tree = git(["write-tree"], repo, env).strip()
        entries = {}
        for entry in git(["ls-tree", "-rz", tree], repo, env).split("\0"):
            if not entry:
                continue
            metadata, name = entry.split("\t")
            mode, kind, oid = metadata.split()
            require(
                kind == "blob" and mode in {"100644", "100755", "120000"},
                "unsupported source entry: " + name,
            )
            require(
                not Path(name).is_absolute() and ".." not in Path(name).parts, "unsafe tree entry"
            )
            entries[name] = (mode, oid)
        return tree, entries


def check_source(prepared, lock, check_manifest=True):
    prepared = safe_path(prepared)
    source = safe_path(prepared / "source")
    require(
        (source / ".git").is_dir() and not (source / ".git").is_symlink(),
        "prepared source must have an independent .git directory",
    )
    require(
        not (source / ".git/objects/info/alternates").exists(), "source object alternates refused"
    )
    require(
        (source / ".git/HEAD").read_text().strip() == lock["upstream"]["commit"],
        "source HEAD must be detached at pin",
    )
    require(
        git(["rev-parse", "HEAD"], source).strip() == lock["upstream"]["commit"],
        "source commit mismatch",
    )
    original = {}
    for entry in git(["ls-tree", "-rz", lock["upstream"]["commit"]], source).split("\0"):
        if entry:
            metadata, name = entry.split("\t")
            mode, _, oid = metadata.split()
            original[name] = (mode, oid, "0")
    staged = {}
    for entry in git(["ls-files", "--stage", "-z"], source).split("\0"):
        if entry:
            metadata, name = entry.split("\t")
            staged[name] = tuple(metadata.split())
    require(staged == original, "source index differs from pinned commit")
    tree, entries = expected_tree(source, lock)
    actual = set()
    directories = set()
    for directory, dirs, files in os.walk(source, followlinks=False):
        if Path(directory) == source:
            dirs.remove(".git")
        for name in dirs:
            path = Path(directory) / name
            require(not path.is_symlink(), "source directory symlink: " + str(path))
            directories.add(str(path.relative_to(source)))
        actual.update(str((Path(directory) / name).relative_to(source)) for name in files)
    wanted_dirs = {
        str(parent) for name in entries for parent in Path(name).parents if str(parent) != "."
    }
    require(
        actual == set(entries) and directories == wanted_dirs,
        "source file set differs from locked tree",
    )
    hashes = {}
    for name, (mode, oid) in entries.items():
        path = source / name
        if mode == "120000":
            require(
                path.is_symlink() and inside(path.resolve(strict=True), source),
                "unsafe source symlink: " + name,
            )
            data = os.readlink(path).encode()
        else:
            require(stat.S_ISREG(path.lstat().st_mode), "not a regular source file: " + name)
            require(
                bool(path.stat().st_mode & 0o111) == (mode == "100755"),
                "source mode mismatch: " + name,
            )
            data = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(blob == oid, "source content differs from locked tree: " + name)
        hashes[name] = {"mode": mode, "sha256": hashlib.sha256(data).hexdigest()}
    identity = {
        "schema_version": 1,
        "upstream": lock["upstream"],
        "patch": lock["patch"],
        "lock_sha256": sha256(LOCK),
        "tree": tree,
        "source_files": hashes,
    }
    if check_manifest:
        saved = json.loads((prepared / "source.json").read_text())
        require(saved["identity"] == identity, "source manifest mismatch")
    return identity


def prepare(output_dir, mirror=None):
    lock = load_lock()
    if mirror is not None:
        mirror = safe_path(mirror)
        require(mirror.is_dir(), "mirror must be a local clone")
        # Development forks use upstream for official history and origin for publishing.
        remotes = git(["remote"], mirror).splitlines()
        official_remote = "upstream" if "upstream" in remotes else "origin"
        require(
            git(["remote", "get-url", official_remote], mirror).strip() == OFFICIAL,
            "mirror official remote is not the official URL",
        )
        require(
            git(["rev-parse", PIN + "^{commit}"], mirror).strip() == PIN,
            "mirror does not contain pinned commit",
        )
    output = new_output(output_dir, (mirror,) if mirror else ())
    commands = []
    try:

        def run(args, cwd=output):
            commands.append({"argv": ["git", *map(str, args)], "cwd": str(cwd)})
            result = git(args, cwd)
            with (output / "prepare.log").open("a") as log:
                log.write("$ " + " ".join(shlex.quote(str(x)) for x in args) + "\n" + result)
            return result

        source = output / "source"
        run(
            [
                "clone",
                "--no-checkout",
                "--no-hardlinks",
                "--template=",
                "--",
                mirror or OFFICIAL,
                source,
            ]
        )
        run(["checkout", "--detach", PIN], source)
        require(run(["rev-parse", "HEAD"], source).strip() == PIN, "checkout pin mismatch")
        patch = ROOT / lock["patch"]["path"]
        run(["apply", "--check", patch], source)
        run(["apply", patch], source)
        identity = check_source(output, lock, check_manifest=False)
        require(load_lock() == lock, "lock changed during prepare")
        write_json(
            output / "source.json",
            {
                "identity": identity,
                "mirror": str(mirror) if mirror else None,
                "commands": commands,
                "prepare_log_sha256": sha256(output / "prepare.log"),
            },
        )
    except Exception as error:
        write_json(output / "failure.json", {"error": str(error), "commands": commands})
        raise
    return output


def audit_symbols(nm_text, ldd_text):
    seen = set()
    for line in nm_text.splitlines():
        fields = line.split()
        require(len(fields) >= 2, "invalid nm output")
        symbol, kind = fields[:2]
        require(kind in {"U", "w", "v"}, "unexpected nm symbol kind: " + line)
        require(
            "@" in symbol or symbol in CALLBACKS or (kind in {"w", "v"} and symbol in WEAK),
            "unexpected undefined symbol: " + line,
        )
        if symbol in CALLBACKS:
            seen.add(symbol)
    require(seen == CALLBACKS, "missing expected callback imports")
    require(
        "not found" not in ldd_text and "statically linked" not in ldd_text,
        "invalid shared-library dependencies",
    )
    require(
        "libc.so" in ldd_text and "libstdc++.so" not in ldd_text,
        "expected native glibc and static libstdc++",
    )
    unresolved = set(re.findall(r"undefined symbol:\s*(\S+)", ldd_text))
    require(unresolved == CALLBACKS, "ldd unresolved symbols are not exactly FORCE callbacks")


def build(source_dir, output_dir, jobs, asan=False):
    require(jobs > 0, "jobs must be positive")
    require(
        sys.platform.startswith("linux") and platform.libc_ver()[0] == "glibc",
        "only native Linux glibc builds are supported",
    )
    lock = load_lock()
    prepared = safe_path(source_dir)
    before = check_source(prepared, lock)
    output = new_output(output_dir, (prepared,))
    source = prepared / "source"
    manifest = {
        "schema_version": 1,
        "status": "failed",
        "source_identity": before,
        "source_dir": str(prepared),
        "jobs": jobs,
        "asan": asan,
        "asan_scope": "wrapper+ABI caller only" if asan else "disabled",
        "host": platform.platform(),
        "commands": [],
        "tools": {},
    }
    # Do not inherit MAKEFLAGS, compiler flags, preload hooks or include overrides.
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(output),
        "TMPDIR": str(output),
        "LC_ALL": "C",
        "CONFIG_SITE": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    manifest["environment"] = env.copy()
    log_path = output / "build.log"
    try:
        with log_path.open("x") as log:

            def run(command, expected=0, capture=False, extra_env=None):
                command = list(map(str, command))
                record = {
                    "argv": command,
                    "cwd": str(output),
                    "expected_exit": expected,
                    "environment_overrides": extra_env or {},
                }
                manifest["commands"].append(record)
                log.write("$ " + " ".join(shlex.quote(x) for x in command) + "\n")
                log.flush()
                result = subprocess.run(
                    command,
                    cwd=output,
                    env={**env, **(extra_env or {})},
                    stdout=subprocess.PIPE if capture else log,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                )
                record["exit_code"] = result.returncode
                if capture:
                    log.write(result.stdout)
                    log.flush()
                require(
                    result.returncode == expected,
                    "command failed ({}): {}; see {}".format(result.returncode, command, log_path),
                )
                return result.stdout

            for name in (
                "gcc",
                "g++",
                "make",
                "ar",
                "ranlib",
                "ld",
                "as",
                "nm",
                "ldd",
                "dtc",
                "sh",
            ):
                path = shutil.which(name, path=env["PATH"])
                require(path, "missing native build tool: " + name)
                version = run([path, "--version"], capture=True) if name != "sh" else "POSIX shell"
                manifest["tools"][name] = {
                    "path": path,
                    "sha256": sha256(path),
                    "version": version,
                }
            cxx = manifest["tools"]["g++"]["path"]
            cc = manifest["tools"]["gcc"]["path"]
            manifest["compiler_target"] = run([cxx, "-dumpmachine"], capture=True).strip()
            manifest["compiler_configuration"] = run([cxx, "-v"], capture=True)
            compiler_inputs = {}
            for name in (
                "cc1plus",
                "collect2",
                "libstdc++.a",
                "libgcc.a",
                "libgcc_eh.a",
                "libasan.so",
            ):
                if name == "libasan.so" and not asan:
                    continue
                # GCC installs executables under libexec, outside its library search path.
                query = (
                    "-print-prog-name=" if name in {"cc1plus", "collect2"} else "-print-file-name="
                )
                path = Path(run([cxx, query + name], capture=True).strip())
                require(path.is_absolute() and path.is_file(), "missing compiler input: " + name)
                compiler_inputs[str(path.resolve())] = sha256(path)
            manifest["compiler_input_sha256"] = compiler_inputs
            inputs = {
                "handcar/upstream.lock.json": sha256(LOCK),
                "handcar/tools/upstream.py": sha256(Path(__file__)),
                "handcar/tools/test_upstream.py": sha256(ROOT / "handcar/tools/test_upstream.py"),
                lock["patch"]["path"]: lock["patch"]["sha256"],
                **lock["tests"],
                **lock["consumer_headers"],
            }
            manifest["input_sha256"] = inputs
            manifest["source_manifest_sha256"] = sha256(prepared / "source.json")
            for name in (*TESTS, LOADER):
                target = output / "inputs" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
                require(sha256(target) == inputs[name], "copied input changed: " + name)
            for name in ABI_HEADERS:
                target = output / "abi" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, target)
            run(
                [
                    source / "configure",
                    "--prefix=" + str(output / "unused-prefix"),
                    "CC=" + cc,
                    "CXX=" + cxx,
                    "CXXFLAGS=-O2 -g0 -fPIC",
                    "CFLAGS=-O2 -g0 -fPIC",
                ]
            )
            libraries = ["libriscv.a", "libdisasm.a", "libfesvr.a", "libsoftfloat.a", "libfdt.a"]
            # Upstream's version script otherwise inspects the build directory's repository.
            version = "project_ver=" + PIN + "-handcar-" + lock["patch"]["sha256"][:12]
            run(["make", "-j" + str(jobs), version, *libraries])
            includes = [
                output,
                source,
                *[source / d for d in ("riscv", "fesvr", "softfloat", "fdt", "disasm", "headers")],
            ]
            common = ["-std=gnu++20", "-O2", "-g0", "-UNDEBUG"]
            wrapper = ["-fPIC", "-DHAVE_CONFIG_H", *["-I" + str(p) for p in includes]]
            archives = [
                "-Wl,--whole-archive",
                *libraries,
                "-Wl,--no-whole-archive",
                "-lpthread",
                "-ldl",
                "-lutil",
                "-static-libstdc++",
                "-static-libgcc",
            ]
            run(
                [
                    cxx,
                    *common,
                    *wrapper,
                    "-MD",
                    "-c",
                    source / "spike_main/spike_lib.cc",
                    "-o",
                    "spike_lib.o",
                ]
            )
            run([cxx, "-shared", "-o", "handcar_cosim.so", "spike_lib.o", *archives])
            mmu, abi = [output / "inputs" / name for name in TESTS]
            run(
                [
                    cxx,
                    *common,
                    *wrapper,
                    "-MD",
                    "-MF",
                    "mmu_checks.d",
                    mmu,
                    "-L.",
                    "-Wl,-rpath,$ORIGIN",
                    "-Wl,--export-dynamic",
                    "-l:handcar_cosim.so",
                    "-o",
                    "mmu_checks",
                ]
            )
            run([output / "mmu_checks"])
            run(
                [
                    cxx,
                    *common,
                    "-MD",
                    "-MF",
                    "abi_checks.d",
                    abi,
                    "-Wl,--export-dynamic",
                    "-ldl",
                    "-o",
                    "abi_checks",
                ]
            )
            run([output / "abi_checks", output / "handcar_cosim.so"])
            for option in ("-p2", "--hartids=0,1", "--hartids=1"):
                run([output / "abi_checks", output / "handcar_cosim.so", option], expected=1)
            nm_text = run(
                ["nm", "-D", "--undefined-only", "--format=posix", "handcar_cosim.so"],
                capture=True,
            )
            ldd_text = run(["ldd", "-r", "handcar_cosim.so"], capture=True)
            (output / "nm.txt").write_text(nm_text)
            (output / "ldd.txt").write_text(ldd_text)
            audit_symbols(nm_text, ldd_text)
            runtime_files = set(re.findall(r"(?:=>\s+|^\s*)(/[^\s()]+)", ldd_text, re.MULTILINE))
            manifest["runtime_dependency_sha256"] = {
                name: sha256(name) for name in sorted(runtime_files)
            }
            if asan:
                flags = ["-fsanitize=address", "-fno-omit-frame-pointer", "-g", "-O1"]
                run(
                    [
                        cxx,
                        *common,
                        *flags,
                        *wrapper,
                        "-c",
                        source / "spike_main/spike_lib.cc",
                        "-o",
                        "spike_lib_asan.o",
                    ]
                )
                run(
                    [
                        cxx,
                        "-shared",
                        *flags,
                        "-o",
                        "handcar_cosim_asan.so",
                        "spike_lib_asan.o",
                        *archives[:-2],
                    ]
                )
                run(
                    [
                        cxx,
                        *common,
                        *flags,
                        abi,
                        "-Wl,--export-dynamic",
                        "-ldl",
                        "-o",
                        "abi_checks_asan",
                    ]
                )
                run(
                    [output / "abi_checks_asan", output / "handcar_cosim_asan.so"],
                    extra_env={
                        "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1:strict_string_checks=1"
                    },
                )
            # Include generated translation units, configuration, archives and ABI exports.
            manifest["artifact_sha256"] = {
                str(p.relative_to(output)): sha256(p)
                for p in sorted(output.rglob("*"))
                if p.is_file() and p != log_path
            }
            dependencies = set()
            for depfile in output.glob("*.d"):
                text = depfile.read_text().replace("\\\n", " ")
                for rule in text.splitlines():
                    if ":" in rule:
                        dependencies.update(shlex.split(rule.split(":", 1)[1]))
            manifest["dependency_sha256"] = {
                str((output / name).resolve()): sha256(output / name)
                for name in sorted(dependencies)
                if (output / name).is_file()
            }
            require(load_lock() == lock, "lock changed during build")
            require(
                all(sha256(ROOT / name) == digest for name, digest in inputs.items()),
                "effective input changed during build",
            )
            require(
                all(sha256(name) == digest for name, digest in compiler_inputs.items()),
                "compiler input changed during build",
            )
            require(
                all(sha256(tool["path"]) == tool["sha256"] for tool in manifest["tools"].values()),
                "build tool changed during build",
            )
            require(check_source(prepared, lock) == before, "source changed during build")
            require(
                sha256(prepared / "source.json") == manifest["source_manifest_sha256"],
                "source manifest changed during build",
            )
            manifest["source_unchanged"] = True
            manifest["library_sha256"] = sha256(output / "handcar_cosim.so")
            manifest["status"] = "passed"
    except Exception as error:
        manifest["error"] = str(error)
        raise
    finally:
        if "source_unchanged" not in manifest:
            try:
                manifest["source_unchanged"] = check_source(prepared, lock) == before
            except Exception as error:
                manifest["source_unchanged"] = False
                manifest["source_check_error"] = str(error)
        manifest["log_sha256"] = sha256(log_path) if log_path.is_file() else None
        write_json(output / "build.json", manifest)
    return output / "handcar_cosim.so"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action")
    commands.required = True
    prep = commands.add_parser(
        "prepare", help="clone pinned official objects and apply locked patch"
    )
    prep.add_argument("--output-dir", required=True)
    prep.add_argument("--mirror", help="optional local official clone; never modified")
    compile_parser = commands.add_parser(
        "build", help="regenerate with official configure/make; never install"
    )
    compile_parser.add_argument(
        "--source-dir", required=True, help="prepare output containing source.json"
    )
    compile_parser.add_argument("--output-dir", required=True)
    compile_parser.add_argument("--jobs", type=int, default=8)
    compile_parser.add_argument(
        "--asan",
        action="store_true",
        help="also instrument wrapper and ABI caller, not upstream archives",
    )
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            print(prepare(args.output_dir, args.mirror))
        else:
            print(build(args.source_dir, args.output_dir, args.jobs, args.asan))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, "upstream: {}\n".format(error))


if __name__ == "__main__":
    main()
