"""Offline fixtures only: no upstream network, full build or installed libraries."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("upstream", Path(__file__).with_name("upstream.py"))
upstream = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(upstream)


class UpstreamTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="upstream-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "force"
        self.root.mkdir()
        self.mirror = self.base / "official"
        self.mirror.mkdir()
        self.git("init", "--template=", self.mirror)
        self.git("remote", "add", "origin", upstream.OFFICIAL)
        (self.mirror / "configure").write_text("#!/bin/sh\nexit 0\n")
        (self.mirror / "configure").chmod(0o755)
        (self.mirror / "original.cc").write_text("original\n")
        (self.mirror / "link.cc").symlink_to("original.cc")
        (self.mirror / ".gitignore").write_text("*.o\n")
        self.git("add", ".")
        tree = self.git("write-tree").strip()
        pin = self.git("commit-tree", tree, "-m", "Offline fixture").strip()
        self.git("update-ref", "HEAD", pin)
        patch = (
            "diff --git a/original.cc b/original.cc\n"
            "--- a/original.cc\n+++ b/original.cc\n"
            "@@ -1 +1 @@\n-original\n+patched\n"
            "diff --git a/new.cc b/new.cc\nnew file mode 100644\n"
            "--- /dev/null\n+++ b/new.cc\n@@ -0,0 +1 @@\n+new file\n"
        )
        for name in upstream.ABI_HEADERS:
            patch += (
                "diff --git a/{0} b/{0}\nnew file mode 100644\n"
                "--- /dev/null\n+++ b/{0}\n@@ -0,0 +1 @@\n+// ABI fixture\n"
            ).format(name)
        self.patch_path = self.root / "handcar/patches/spike-4ffd6ba-handcar.patch"
        self.patch_path.parent.mkdir(parents=True)
        self.patch_path.write_text(patch)
        for name in (*upstream.TESTS, upstream.LOADER, "handcar/tools/test_upstream.py"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("// fixture\n")
        target = self.root / "handcar/tools/upstream.py"
        shutil.copyfile(Path(upstream.__file__), target)
        self.lock = {
            "schema_version": 1,
            "upstream": {"url": upstream.OFFICIAL, "commit": pin},
            "patch": {
                "path": str(self.patch_path.relative_to(self.root)),
                "sha256": upstream.sha256(self.patch_path),
            },
            "tests": {name: upstream.sha256(self.root / name) for name in upstream.TESTS},
            "consumer_headers": {upstream.LOADER: upstream.sha256(self.root / upstream.LOADER)},
        }
        self.lock_path = self.root / "handcar/upstream.lock.json"
        self.save_lock()
        for name, value in (("ROOT", self.root), ("LOCK", self.lock_path), ("PIN", pin)):
            patcher = mock.patch.object(upstream, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def git(self, *args, cwd=None):
        env = upstream.git_env()
        env.update(
            GIT_AUTHOR_NAME="Fixture",
            GIT_AUTHOR_EMAIL="fixture@example.invalid",
            GIT_COMMITTER_NAME="Fixture",
            GIT_COMMITTER_EMAIL="fixture@example.invalid",
        )
        result = subprocess.run(
            ["git", *map(str, args)],
            cwd=cwd or self.mirror,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return result.stdout.decode()

    def save_lock(self):
        self.lock_path.write_text(json.dumps(self.lock))

    def prepare(self):
        return upstream.prepare(self.base / "prepared", self.mirror)

    def test_offline_prepare_detached_patch_and_mirror_untouched(self):
        (self.mirror / "original.cc").write_text("dirty mirror must not leak\n")
        (self.mirror / "untracked.cc").write_text("not copied\n")
        before = self.git("status", "--porcelain")
        index = upstream.sha256(self.mirror / ".git/index")
        prepared = self.prepare()
        identity = upstream.check_source(prepared, self.lock)
        self.assertEqual((prepared / "source/original.cc").read_text(), "patched\n")
        self.assertEqual((prepared / "source/new.cc").read_text(), "new file\n")
        self.assertEqual((prepared / "source/.git/HEAD").read_text().strip(), upstream.PIN)
        self.assertFalse((prepared / "source/untracked.cc").exists())
        self.assertEqual(before, self.git("status", "--porcelain"))
        self.assertEqual(index, upstream.sha256(self.mirror / ".git/index"))
        self.assertEqual(identity["upstream"]["commit"], upstream.PIN)
        # Validation must not write even to the prepared index or object store.
        gitdir = prepared / "source/.git"
        objects = {str(p): upstream.sha256(p) for p in gitdir.rglob("*") if p.is_file()}
        upstream.check_source(prepared, self.lock)
        self.assertEqual(
            objects, {str(p): upstream.sha256(p) for p in gitdir.rglob("*") if p.is_file()}
        )

    def test_development_mirror_with_official_upstream_and_fork_origin(self):
        self.git("remote", "rename", "origin", "upstream")
        self.git("remote", "add", "origin", "https://example.invalid/handcar-fork")
        before = self.git("remote", "-v")
        prepared = self.prepare()
        self.assertEqual(
            upstream.check_source(prepared, self.lock)["upstream"], self.lock["upstream"]
        )
        self.assertEqual(self.git("remote", "-v"), before)

    def test_wrong_upstream_cannot_fall_back_to_official_origin(self):
        self.git("remote", "add", "upstream", "https://example.invalid/not-official")
        with self.assertRaisesRegex(ValueError, "not the official"):
            self.prepare()
        self.assertFalse((self.base / "prepared").exists())

    def test_pin_and_url_tamper(self):
        for key, value in (("commit", "0" * 40), ("url", "https://example.invalid/fork")):
            with self.subTest(key=key):
                old = self.lock["upstream"][key]
                self.lock["upstream"][key] = value
                self.save_lock()
                with self.assertRaisesRegex(ValueError, "pin/url"):
                    self.prepare()
                self.lock["upstream"][key] = old
        self.assertFalse((self.base / "prepared").exists())

    def test_patch_tamper(self):
        self.patch_path.write_text(self.patch_path.read_text() + "tamper\n")
        with self.assertRaisesRegex(ValueError, "input hash mismatch"):
            self.prepare()
        self.assertFalse((self.base / "prepared").exists())

    def test_test_and_loader_tamper(self):
        for name in (*upstream.TESTS, upstream.LOADER):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_text("changed\n")
                with self.assertRaisesRegex(ValueError, "input hash mismatch"):
                    self.prepare()
                path.write_bytes(original)

    def test_mirror_missing_pin_or_wrong_origin(self):
        with mock.patch.object(upstream, "PIN", "1" * 40):
            self.lock["upstream"]["commit"] = upstream.PIN
            self.save_lock()
            with self.assertRaisesRegex(ValueError, "git failed"):
                self.prepare()
        self.lock["upstream"]["commit"] = upstream.PIN
        self.save_lock()
        self.git("remote", "set-url", "origin", "https://example.invalid/not-official")
        with self.assertRaisesRegex(ValueError, "not the official"):
            self.prepare()

    def test_patch_check_failure_retains_failed_output(self):
        self.patch_path.write_text(self.patch_path.read_text().replace("-original", "-absent"))
        self.lock["patch"]["sha256"] = upstream.sha256(self.patch_path)
        self.save_lock()
        with self.assertRaisesRegex(ValueError, "git failed"):
            self.prepare()
        output = self.base / "prepared"
        self.assertTrue((output / "failure.json").is_file())
        self.assertFalse((output / "source.json").exists())
        self.assertEqual((output / "source/original.cc").read_text(), "original\n")
        with self.assertRaisesRegex(ValueError, "must be new"):
            self.prepare()

    def test_dirty_tracked_and_patch_added_source_refused(self):
        prepared = self.prepare()
        for name in ("original.cc", "new.cc", "configure"):
            with self.subTest(name=name):
                path = prepared / "source" / name
                original = path.read_bytes()
                path.write_text("tampered\n")
                with self.assertRaisesRegex(ValueError, "content differs"):
                    upstream.check_source(prepared, self.lock)
                path.write_bytes(original)

    def test_deleted_extra_and_ignored_files_refused(self):
        prepared = self.prepare()
        for name in ("extra.cc", "ignored.o"):
            path = prepared / "source" / name
            path.write_text("extra\n")
            with self.assertRaisesRegex(ValueError, "file set"):
                upstream.check_source(prepared, self.lock)
            path.unlink()
        (prepared / "source/new.cc").unlink()
        with self.assertRaisesRegex(ValueError, "file set"):
            upstream.check_source(prepared, self.lock)

    def test_source_mode_symlink_head_and_manifest_tamper(self):
        prepared = self.prepare()
        source = prepared / "source"
        (source / "configure").chmod(0o644)
        with self.assertRaisesRegex(ValueError, "mode mismatch"):
            upstream.check_source(prepared, self.lock)
        (source / "configure").chmod(0o755)
        (source / "link.cc").unlink()
        (source / "link.cc").symlink_to(self.root / upstream.LOADER)
        with self.assertRaisesRegex(ValueError, "unsafe source symlink"):
            upstream.check_source(prepared, self.lock)
        (source / "link.cc").unlink()
        (source / "link.cc").symlink_to("original.cc")
        (source / ".git/HEAD").write_text("ref: refs/heads/master\n")
        with self.assertRaisesRegex(ValueError, "detached at pin"):
            upstream.check_source(prepared, self.lock)
        (source / ".git/HEAD").write_text(upstream.PIN + "\n")
        saved = json.loads((prepared / "source.json").read_text())
        saved["identity"]["tree"] = "0" * 40
        (prepared / "source.json").write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError, "manifest mismatch"):
            upstream.check_source(prepared, self.lock)

    def test_staged_source_change_refused_even_if_worktree_restored(self):
        prepared = self.prepare()
        source = prepared / "source"
        self.git("add", "original.cc", cwd=source)
        with self.assertRaisesRegex(ValueError, "index differs"):
            upstream.check_source(prepared, self.lock)

    def test_new_output_parent_and_overlap_safety(self):
        (self.base / "existing").mkdir()
        (self.base / "existing/precious").write_text("keep")
        (self.base / "link").symlink_to(self.mirror, target_is_directory=True)
        outputs = [
            self.base / "existing",
            self.base / "missing/new",
            self.base / "link/new",
            self.mirror / "new",
            self.root / "handcar/new",
            self.base / "bad name",
            self.base / "existing/../new",
        ]
        for output in outputs:
            with self.subTest(output=output), self.assertRaises(ValueError):
                upstream.new_output(output, (self.mirror,))
        self.assertEqual((self.base / "existing/precious").read_text(), "keep")
        dangling = self.base / "dangling"
        dangling.symlink_to(self.base / "absent")
        with self.assertRaisesRegex(ValueError, "symlink"):
            upstream.new_output(dangling)

    def test_dirty_source_build_fails_before_tools_or_output(self):
        prepared = self.prepare()
        (prepared / "source/new.cc").write_text("dirty\n")
        with self.assertRaisesRegex(ValueError, "content differs"):
            upstream.build(prepared, self.base / "build", 1)
        self.assertFalse((self.base / "build").exists())

    def test_build_existing_output_and_invalid_jobs_refused(self):
        prepared = self.prepare()
        output = self.base / "build"
        output.mkdir()
        with self.assertRaisesRegex(ValueError, "must be new"):
            upstream.build(prepared, output, 1)
        with self.assertRaisesRegex(ValueError, "positive"):
            upstream.build(prepared, output, 0)
        with self.assertRaisesRegex(ValueError, "overlaps"):
            upstream.build(prepared, prepared / "new", 1)

    def test_missing_tool_records_failed_manifest(self):
        prepared = self.prepare()
        with mock.patch.object(upstream.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "missing native build tool"):
                upstream.build(prepared, self.base / "build", 1)
        manifest = json.loads((self.base / "build/build.json").read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertIn("missing native", manifest["error"])
        upstream.check_source(prepared, self.lock)

    def simulated_build(
        self, prepared, asan=False, failure=False, mutate=False, missing_input=None
    ):
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if command[0] == "git" or "cwd" not in kwargs:
                return real_run(command, **kwargs)
            output = Path(kwargs["cwd"])
            text = "fixture tool\n"
            code = 0
            if command[-1].startswith(("-print-file-name=", "-print-prog-name=")):
                query, name = command[-1].split("=", 1)
                expected = (
                    "-print-prog-name" if name in {"cc1plus", "collect2"} else "-print-file-name"
                )
                text = (
                    "/usr/bin/true\n"
                    if query == expected and name != missing_input
                    else name + "\n"
                )
            elif command[0].endswith("/configure"):
                (output / "config.h").write_text("// generated\n")
                if failure:
                    code = 2
            elif command[0] == "make":
                for name in command[3:]:
                    (output / name).write_bytes(b"fixture archive")
                (output / "add.cc").write_text("// generated instruction\n")
            elif command[0] == "nm":
                text = "puts@GLIBC_2.2.5 U\n" + "".join(
                    name + " U\n" for name in sorted(upstream.CALLBACKS)
                )
            elif command[0] == "ldd":
                text = "libc.so.6 => /usr/bin/true\n" + "".join(
                    "undefined symbol: " + name + " (./handcar_cosim.so)\n"
                    for name in sorted(upstream.CALLBACKS)
                )
                if mutate:
                    (prepared / "source/new.cc").write_text("mutated during build\n")
            elif "-o" in command:
                (output / command[command.index("-o") + 1]).write_bytes(b"fixture output")
            elif command[-1] in ("-p2", "--hartids=0,1", "--hartids=1"):
                code = 1
            if kwargs["stdout"] != subprocess.PIPE:
                kwargs["stdout"].write(text)
                text = None
            return subprocess.CompletedProcess(command, code, stdout=text)

        with (
            mock.patch.object(upstream.subprocess, "run", side_effect=fake_run),
            mock.patch.object(upstream.shutil, "which", return_value="/usr/bin/true"),
        ):
            return upstream.build(prepared, self.base / "build", 3, asan)

    def test_build_recipe_manifest_and_no_source_changes(self):
        prepared = self.prepare()
        library = self.simulated_build(prepared, asan=True)
        manifest = json.loads((library.parent / "build.json").read_text())
        self.assertEqual(manifest["status"], "passed")
        self.assertTrue(manifest["source_unchanged"])
        self.assertEqual(manifest["library_sha256"], upstream.sha256(library))
        self.assertEqual(manifest["log_sha256"], upstream.sha256(library.parent / "build.log"))
        commands = [record["argv"] for record in manifest["commands"]]
        for name in ("cc1plus", "collect2"):
            self.assertIn(["/usr/bin/true", "-print-prog-name=" + name], commands)
            self.assertNotIn(["/usr/bin/true", "-print-file-name=" + name], commands)
        for name in ("libstdc++.a", "libgcc.a", "libgcc_eh.a", "libasan.so"):
            self.assertIn(["/usr/bin/true", "-print-file-name=" + name], commands)
        self.assertIn(
            [
                "make",
                "-j3",
                "project_ver=" + upstream.PIN + "-handcar-" + self.lock["patch"]["sha256"][:12],
                "libriscv.a",
                "libdisasm.a",
                "libfesvr.a",
                "libsoftfloat.a",
                "libfdt.a",
            ],
            commands,
        )
        configure = next(cmd for cmd in commands if cmd[0].endswith("/configure"))
        self.assertEqual(configure[0], str(prepared / "source/configure"))
        self.assertIn("CXXFLAGS=-O2 -g0 -fPIC", configure)
        normal_link = next(
            cmd for cmd in commands if "-shared" in cmd and "handcar_cosim.so" in cmd
        )
        self.assertIn("-Wl,--whole-archive", normal_link)
        self.assertIn("-static-libstdc++", normal_link)
        self.assertFalse(any("install" in cmd or "manage.py" in " ".join(cmd) for cmd in commands))
        self.assertEqual(manifest["asan_scope"], "wrapper+ABI caller only")
        self.assertTrue(
            any(
                "ASAN_OPTIONS" in record["environment_overrides"]
                for record in manifest["commands"]
            )
        )
        self.assertIn("add.cc", manifest["artifact_sha256"])
        for name in upstream.ABI_HEADERS:
            self.assertEqual(
                upstream.sha256(library.parent / "abi" / name),
                upstream.sha256(prepared / "source" / name),
            )
        upstream.check_source(prepared, self.lock)

    def test_tool_failure_records_command_exit_and_preserves_source(self):
        prepared = self.prepare()
        with self.assertRaisesRegex(ValueError, "command failed"):
            self.simulated_build(prepared, failure=True)
        manifest = json.loads((self.base / "build/build.json").read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["commands"][-1]["exit_code"], 2)
        self.assertNotIn("library_sha256", manifest)
        upstream.check_source(prepared, self.lock)

    def test_unresolved_compiler_program_is_rejected(self):
        prepared = self.prepare()
        with self.assertRaisesRegex(ValueError, "missing compiler input: cc1plus"):
            self.simulated_build(prepared, missing_input="cc1plus")
        manifest = json.loads((self.base / "build/build.json").read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["commands"][-1]["argv"][-1], "-print-prog-name=cc1plus")
        self.assertFalse((self.base / "build/config.h").exists())
        upstream.check_source(prepared, self.lock)

    def test_unresolved_compiler_library_is_rejected(self):
        prepared = self.prepare()
        with self.assertRaisesRegex(ValueError, "missing compiler input: libstdc\\+\\+\\.a"):
            self.simulated_build(prepared, missing_input="libstdc++.a")
        manifest = json.loads((self.base / "build/build.json").read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["commands"][-1]["argv"][-1], "-print-file-name=libstdc++.a")
        self.assertFalse((self.base / "build/config.h").exists())

    def test_default_build_does_not_enable_asan(self):
        prepared = self.prepare()
        library = self.simulated_build(prepared)
        manifest = json.loads((library.parent / "build.json").read_text())
        self.assertEqual(manifest["status"], "passed")
        self.assertEqual(manifest["asan_scope"], "disabled")
        self.assertFalse(
            any("-fsanitize=address" in record["argv"] for record in manifest["commands"])
        )

    def test_final_source_recheck_rejects_build_time_mutation(self):
        prepared = self.prepare()
        with self.assertRaisesRegex(ValueError, "content differs"):
            self.simulated_build(prepared, mutate=True)
        manifest = json.loads((self.base / "build/build.json").read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertFalse(manifest["source_unchanged"])

    def test_symbol_audit(self):
        nm = "puts@GLIBC_2.2.5 U\n__gmon_start__ w\n" + "".join(
            name + " U\n" for name in sorted(upstream.CALLBACKS)
        )
        ldd = "libc.so.6 => /lib/libc.so.6\n" + "".join(
            "undefined symbol: " + name + " (./handcar_cosim.so)\n"
            for name in sorted(upstream.CALLBACKS)
        )
        upstream.audit_symbols(nm, ldd)
        for bad_nm, bad_ldd in (
            (nm + "unexpected U\n", ldd),
            (nm + "unknown_weak w\n", ldd),
            (nm, ldd + "libfoo.so => not found\n"),
            (nm, ldd + "undefined symbol: unexpected\n"),
            (nm, ldd + "libstdc++.so.6 => /lib/libstdc++.so.6\n"),
            ("", ldd),
        ):
            with self.subTest(nm=bad_nm, ldd=bad_ldd), self.assertRaises(ValueError):
                upstream.audit_symbols(bad_nm, bad_ldd)


if __name__ == "__main__":
    unittest.main()
