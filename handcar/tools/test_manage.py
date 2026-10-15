"""Safety tests use temporary targets, never workspace installations."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("manage", Path(__file__).with_name("manage.py"))
manage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manage)


class ManageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="handcar-manager-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "force"
        self.root.mkdir()
        self.source = self.base / "source"
        self.source.mkdir()
        self.patch = mock.patch.object(manage, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
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
            (self.source / directory).mkdir()
        for name in (
            "config.h",
            "riscv/processor.cc",
            "build/insn_list.h",
            "build/add.cc",
            "spike_main/spike_lib.cc",
            "softfloat/a.c",
            "fdt/a.c",
            "fesvr/a.cc",
            "disasm/a.cc",
            "debug_rom/debug_rom.h",
        ):
            (self.source / name).write_text("/* fixture */\n")
        for relative in manage.ABI.values():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("/* ABI */\n")
        for path in manage.targets().values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original " + path.parent.name.encode())

    def snapshot(self):
        output = self.base / "snapshot"
        lock = manage.snapshot(self.source, output)
        return output, lock

    def test_snapshot_self_contained_and_excludes_cache(self):
        for name in (
            "build/a.o",
            "build/a.a",
            "build/a.so",
            "build/config.log",
            "build/spike",
            "build_v2.sh",
        ):
            (self.source / name).write_bytes(b"not input")
        output, lock = self.snapshot()
        self.assertEqual(lock["upstream"], {"status": "unknown", "remote": None, "revision": None})
        self.assertEqual(manage.verify_source(output), lock)
        self.assertEqual(set(lock["abi_headers"]), set(manage.ABI))
        self.assertFalse((output / "build/a.o").exists())
        self.assertFalse((output / "build_v2.sh").exists())
        self.assertTrue((output / "headers/handcar_cosim_wrapper.h").is_file())
        # A relocated snapshot needs neither the source nor ABI symlinks.
        moved = self.base / "moved"
        output.rename(moved)
        self.assertEqual(manage.verify_source(moved)["snapshot_sha256"], lock["snapshot_sha256"])

    def test_resnapshot_same_digest(self):
        output, lock = self.snapshot()
        second = manage.snapshot(output, self.base / "second")
        self.assertEqual(lock["snapshot_sha256"], second["snapshot_sha256"])

    def test_output_existing_even_empty_refused(self):
        output = self.base / "existing"
        output.mkdir()
        with self.assertRaisesRegex(ValueError, "must be new"):
            manage.snapshot(self.source, output)
        (output / "precious").write_bytes(b"keep")
        with self.assertRaises(ValueError):
            manage.snapshot(self.source, output)
        self.assertEqual((output / "precious").read_bytes(), b"keep")

    def test_output_source_and_install_overlap_refused(self):
        for output in (
            self.source,
            self.source / "new",
            self.base,
            self.root / "utils/handcar/new",
            self.root / "bin/new",
            self.root / "handcar/new",
        ):
            with self.subTest(output=output), self.assertRaises(ValueError):
                manage.snapshot(self.source, output)

    def test_output_symlink_parent_refused(self):
        link = self.base / "link"
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            manage.snapshot(self.source, link / "new")

    def test_external_input_symlink_refused(self):
        path = self.source / "riscv/external.h"
        path.symlink_to(self.root / "handcar/headers/handcar_cosim_wrapper.h")
        with self.assertRaisesRegex(ValueError, "escapes source"):
            self.snapshot()

    def test_internal_file_symlink_materialized(self):
        (self.source / "build/config.h").symlink_to("../config.h")
        output, _ = self.snapshot()
        self.assertFalse((output / "build/config.h").is_symlink())
        manage.verify_source(output)

    def test_changed_input_refused(self):
        output, _ = self.snapshot()
        (output / "build/add.cc").write_text("changed")
        with self.assertRaisesRegex(ValueError, "hashes/file set"):
            manage.verify_source(output)
        with self.assertRaises(ValueError):
            manage.snapshot(output, self.base / "bad")
        self.assertFalse((self.base / "bad").exists())

    def test_extra_file_refused(self):
        output, _ = self.snapshot()
        (output / "extra.h").write_text("new input")
        with self.assertRaises(ValueError):
            manage.verify_source(output)

    def test_missing_input_refused(self):
        (self.source / "build/insn_list.h").unlink()
        with self.assertRaisesRegex(ValueError, "missing required"):
            self.snapshot()

    def test_source_file_added_during_copy_refused(self):
        original = manage.checked_copy

        def changing_copy(source, target):
            result = original(source, target)
            (self.source / "riscv/added.cc").write_text("new source\n")
            return result

        with mock.patch.object(manage, "checked_copy", side_effect=changing_copy):
            with self.assertRaisesRegex(ValueError, "source changed during snapshot"):
                self.snapshot()

    def test_lock_digest_refused(self):
        output, lock = self.snapshot()
        lock["snapshot_sha256"] = "0" * 64
        manage.write_json(output / manage.LOCK, lock)
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            manage.verify_source(output)

    def test_snapshot_symlink_refused(self):
        output, _ = self.snapshot()
        (output / "extra").symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "self-contained"):
            manage.verify_source(output)

    def test_nm_failure_nonzero(self):
        failed = subprocess.CompletedProcess([], 1, "", "nm broken")
        with mock.patch.object(manage.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(ValueError, "tool failed"):
                manage.validate_library(self.base / "lib.so", {}, self.base)

    def test_tool_missing_nonzero(self):
        with mock.patch.object(manage.subprocess, "run", side_effect=FileNotFoundError("nm")):
            with self.assertRaises(OSError):
                manage.validate_library(self.base / "lib.so", {}, self.base)

    def test_unexpected_strong_and_weak_symbols(self):
        for symbol in ("surprise U", "surprise w", "surprise v", "_ITM_RU1 U"):
            with self.subTest(symbol=symbol), mock.patch.object(
                manage, "run", return_value=symbol
            ):
                with self.assertRaisesRegex(ValueError, "unexpected undefined"):
                    manage.validate_library(self.base / "lib.so", {}, self.base)

    def test_bad_nm_report(self):
        for report in ("", "garbage", "oops T"):
            with self.subTest(report=report), mock.patch.object(
                manage, "run", return_value=report
            ):
                with self.assertRaises(ValueError):
                    manage.validate_library(self.base / "lib.so", {}, self.base)

    def test_ldd_failure_and_unresolved_versioned_symbol(self):
        for report in (
            "libc.so.6 => not found",
            "undefined symbol: bad@GLIBC_2.2 (lib.so)",
            "libc.so.6 => /lib/libc.so.6 (0x123)\nundefined symbol: bad (lib.so)",
            "libc.so.6 => /lib/libc.so.6 (0x123)\nloader error",
        ):
            with self.subTest(report=report), mock.patch.object(
                manage, "run", side_effect=["bad@GLIBC_2.2 U", report]
            ):
                with self.assertRaises(ValueError):
                    manage.validate_library(self.base / "lib.so", {}, self.base)

    def test_ldd_nonzero_is_fatal(self):
        with mock.patch.object(
            manage.subprocess,
            "run",
            side_effect=[
                subprocess.CompletedProcess([], 0, "update_generator_memory U", ""),
                subprocess.CompletedProcess([], 1, "", "failed"),
            ],
        ):
            with self.assertRaisesRegex(ValueError, "tool failed"):
                manage.validate_library(self.base / "lib.so", {}, self.base)

    def test_host_callbacks_and_runtime_weak_allowed(self):
        library = self.base / "lib.so"
        runtime = self.base / "libc.so.6"
        runtime.write_bytes(b"runtime")
        nm = (
            "update_generator_memory U\nupdate_generator_register U\n"
            "memcpy@GLIBC_2.14 U\n__gmon_start__ w\n_ITM_RU1 w\n"
            "_ZTH22softfloat_roundingMode w\n"
        )
        ldd = (
            f"libc.so.6 => {runtime} (0x123)\n"
            f"undefined symbol: update_generator_memory ({library})\n"
            f"undefined symbol: update_generator_register ({library})\n"
        )
        with mock.patch.object(manage, "run", side_effect=[nm, ldd]):
            result = manage.validate_library(library, {}, self.base)
        self.assertEqual(result["runtime_inputs"][str(runtime)], manage.sha256(runtime))

    def test_build_refuses_existing_before_tools(self):
        with mock.patch.object(manage, "environment") as env:
            with self.assertRaises(ValueError):
                manage.build(self.source, self.source, 1, "gcc", "g++")
            env.assert_not_called()

    def test_build_invalid_jobs(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            manage.build(self.source, self.base / "out", 0, "gcc", "g++")

    def test_missing_build_tool_preflight_no_output(self):
        with mock.patch.object(
            manage, "environment", return_value={"PATH": "/bin"}
        ), mock.patch.object(manage.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "missing tool"):
                manage.build(self.source, self.base / "out", 1, "missing", "missing")
        self.assertFalse((self.base / "out").exists())

    def test_disk_preflight_no_output(self):
        with mock.patch.object(
            manage, "environment", return_value={"PATH": "/bin"}
        ), mock.patch.object(
            manage.shutil, "which", return_value="/usr/bin/gcc"
        ), mock.patch.object(
            manage.shutil, "disk_usage", return_value=mock.Mock(free=0)
        ):
            with self.assertRaisesRegex(ValueError, "GiB free"):
                manage.build(self.source, self.base / "out", 1, "gcc", "g++")
        self.assertFalse((self.base / "out").exists())

    @unittest.skipUnless(
        all(shutil.which(p) for p in ("gcc", "g++", "dtc", "nm", "ldd")),
        "native toolchain not installed",
    )
    def test_native_fixture_build_no_stale_list_or_install(self):
        (self.source / "riscv/insn_list.h").write_text("#error stale list\n")
        (self.source / "riscv/processor.cc").write_text('#include "insn_list.h"\n')
        (self.source / "spike_main/spike_lib.cc").write_text(
            '#include <stdio.h>\n#include "../headers/handcar_cosim_wrapper.h"\n'
            'extern "C" void update_generator_memory();\n'
            'extern "C" void update_generator_register();\n'
            'extern "C" void fixture() { puts("fixture"); update_generator_memory(); '
            "update_generator_register(); }\n"
        )
        before = {p: manage.sha256(p) for p in manage.targets().values()}
        output, lock = self.snapshot()
        with mock.patch.dict(os.environ, {"FORCE_SOURCED": "True"}):
            result = manage.build(output, self.base / "built", 2, "gcc", "g++")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["snapshot_sha256"], lock["snapshot_sha256"])
        self.assertEqual(result["library_sha256"], manage.sha256(result["library"]))
        self.assertTrue(result["compiler_inputs"])
        self.assertTrue(result["linker_inputs"])
        compiled = [command for command in result["commands"] if "-c" in command]
        self.assertEqual(
            {Path(command[-1]).name for command in compiled},
            {
                "insn_add.o",
                "disasm_a.o",
                "softfloat_a.o",
                "fdt_a.o",
                "processor.o",
                "spike_lib.o",
                "a.o",
            },
        )
        self.assertEqual({p: manage.sha256(p) for p in before}, before)
        manage.verify_source(output)

    def test_environment_sanitized(self):
        with mock.patch.dict(
            os.environ, {"FORCE_SOURCED": "True", "CPATH": "/bad", "LD_PRELOAD": "/bad"}
        ):
            env = manage.environment()
        self.assertNotIn("CPATH", env)
        self.assertNotIn("LD_PRELOAD", env)

    def test_install_requires_yes(self):
        with self.assertRaisesRegex(ValueError, "requires --yes"):
            manage.install(self.base / "missing", self.base, self.base, False, "utils")

    def fake_acceptance(self, library, profile="m1", seeds=None):
        directory = self.base / "acceptance"
        directory.mkdir()
        archived = directory / "inputs/handcar.so"
        archived.parent.mkdir()
        archived.write_bytes(library.read_bytes())
        cases = [
            {"id": f"{kind}-seed-{seed:x}", "kind": kind, "seed": seed}
            for kind in ("access", "fault", "two_stage")
            for seed in (range(1, 101) if kind == "two_stage" else (1, 0xDEADBEEF, 0x123456789))
        ]
        manifest = {
            "schema": 1,
            "profile": profile,
            "seeds": seeds,
            "cases": cases,
            "handcar": "inputs/handcar.so",
            "ptg": "inputs/ptg.so",
            "friscv": "inputs/friscv",
            "config": "inputs/config",
            "inputs": {"inputs/handcar.so": {"sha256": manage.sha256(archived)}},
        }
        manage.write_json(directory / "manifest.json", manifest)
        manage.write_json(directory / "results.json", {"passed": True, "cases": [True] * 106})
        return directory

    def test_fake_106_pass_is_not_acceptance(self):
        library = self.base / "lib.so"
        library.write_bytes(b"library")
        directory = self.fake_acceptance(library)
        with mock.patch.object(manage, "ROOT", Path(__file__).resolve().parents[2]):
            with self.assertRaisesRegex(ValueError, "re-audit did not pass"):
                manage.acceptance(library, directory)

    def test_install_fake_acceptance_does_not_touch_targets(self):
        library = self.base / "lib.so"
        library.write_bytes(b"library")
        directory = self.fake_acceptance(library)
        selected = manage.targets()
        before = {p: manage.sha256(p) for p in selected.values()}
        with mock.patch.object(
            manage, "ROOT", Path(__file__).resolve().parents[2]
        ), mock.patch.object(manage, "targets", return_value=selected), mock.patch.object(
            manage, "environment", return_value={}
        ), mock.patch.object(
            manage, "validate_library"
        ) as validator:
            with self.assertRaisesRegex(ValueError, "re-audit did not pass"):
                manage.install(library, directory, self.base / "backups", True, "both")
            validator.assert_not_called()
        self.assertEqual({p: manage.sha256(p) for p in before}, before)
        self.assertFalse((self.base / "backups").exists())

    def test_acceptance_wrong_library_hash(self):
        library = self.base / "lib.so"
        library.write_bytes(b"library")
        directory = self.fake_acceptance(library)
        library.write_bytes(b"other library")
        with mock.patch.object(manage, "ROOT", Path(__file__).resolve().parents[2]):
            with self.assertRaisesRegex(ValueError, "library hash mismatch"):
                manage.acceptance(library, directory)

    def test_acceptance_smoke_and_custom_seeds_refused(self):
        library = self.base / "lib.so"
        library.write_bytes(b"library")
        directory = self.fake_acceptance(library, profile="smoke")
        with self.assertRaisesRegex(ValueError, "full default M1"):
            manage.acceptance(library, directory)
        manifest = json.loads((directory / "manifest.json").read_text())
        manifest.update(profile="m1", seeds=[1])
        manage.write_json(directory / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "full default M1"):
            manage.acceptance(library, directory)

    def install_fixture(self, target="both"):
        directory = self.base / "candidate"
        directory.mkdir()
        library = directory / "lib.so"
        library.write_bytes(b"candidate")
        backup = self.base / "backups"
        backup.mkdir()
        acceptance = self.base / "accepted"
        acceptance.mkdir()
        with mock.patch.object(manage, "environment", return_value={}), mock.patch.object(
            manage, "acceptance", return_value={"library_sha256": manage.sha256(library)}
        ), mock.patch.object(manage, "validate_library"):
            result = manage.install(library, acceptance, backup, True, target)
        return Path(result["receipt"]), library

    def test_install_and_rollback_only_tmp_targets(self):
        originals = {p: manage.sha256(p) for p in manage.targets().values()}
        receipt_path, library = self.install_fixture()
        receipt = json.loads(receipt_path.read_text())
        for entry in receipt["targets"]:
            self.assertEqual(entry["original_sha256"], originals[Path(entry["target"])])
            self.assertEqual(manage.sha256(entry["target"]), manage.sha256(library))
        manage.rollback(receipt_path, True)
        for path, original in originals.items():
            self.assertEqual(manage.sha256(path), original)

    def test_install_utils_only(self):
        before = manage.sha256(manage.targets()["bin"])
        receipt, _ = self.install_fixture("utils")
        self.assertEqual(len(json.loads(receipt.read_text())["targets"]), 1)
        self.assertEqual(manage.sha256(manage.targets()["bin"]), before)

    def test_install_symlink_target_refused(self):
        path = manage.targets()["utils"]
        path.unlink()
        path.symlink_to(manage.targets()["bin"])
        before = manage.sha256(manage.targets()["bin"])
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.install_fixture()
        self.assertEqual(manage.sha256(manage.targets()["bin"]), before)

    def test_partial_install_can_rollback(self):
        before = {p: manage.sha256(p) for p in manage.targets().values()}
        original_replace = manage.atomic_replace
        calls = []

        def interrupted(*args):
            calls.append(args)
            if len(calls) == 2:
                raise OSError("fixture interruption")
            return original_replace(*args)

        with mock.patch.object(manage, "atomic_replace", side_effect=interrupted):
            with self.assertRaisesRegex(ValueError, "rollback receipt"):
                self.install_fixture()
        receipts = list((self.base / "backups").glob("*/receipt.json"))
        self.assertEqual(len(receipts), 1)
        manage.rollback(receipts[0], True)
        self.assertEqual({p: manage.sha256(p) for p in before}, before)

    def test_rollback_requires_yes(self):
        with self.assertRaisesRegex(ValueError, "requires --yes"):
            manage.rollback(self.base / "no-receipt", False)

    def test_rollback_preserves_user_subsequent_modification(self):
        receipt, library = self.install_fixture()
        manage.targets()["bin"].write_bytes(b"user update")
        with self.assertRaisesRegex(ValueError, "subsequently modified"):
            manage.rollback(receipt, True)
        self.assertEqual(manage.targets()["bin"].read_bytes(), b"user update")
        self.assertEqual(manage.sha256(manage.targets()["utils"]), manage.sha256(library))

    def test_rollback_bad_backup_hash_refused(self):
        receipt_path, library = self.install_fixture()
        receipt = json.loads(receipt_path.read_text())
        (receipt_path.parent / receipt["targets"][0]["backup"]).write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "backup hash mismatch"):
            manage.rollback(receipt_path, True)
        self.assertEqual(manage.sha256(manage.targets()["utils"]), manage.sha256(library))

    def test_rollback_receipt_path_traversal_refused(self):
        receipt_path, _ = self.install_fixture()
        receipt = json.loads(receipt_path.read_text())
        receipt["targets"][0]["backup"] = "../elsewhere"
        manage.write_json(receipt_path, receipt)
        with self.assertRaises(ValueError):
            manage.rollback(receipt_path, True)

    def test_atomic_replace_wrong_hash_preserves_target(self):
        source = self.base / "replacement"
        source.write_bytes(b"replacement")
        target = manage.targets()["utils"]
        before = target.read_bytes()
        with self.assertRaisesRegex(ValueError, "replacement hash"):
            manage.atomic_replace(source, target, manage.sha256(target), "0" * 64, 0o755)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(list(target.parent.glob(".handcar-*")), [])

    def test_cli_failure_nonzero(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(manage.main(["verify-source", "--source-dir", str(self.source)]), 1)


if __name__ == "__main__":
    unittest.main()
