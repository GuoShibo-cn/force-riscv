"""Workflow orchestration tests mock every runner; never recursively run the workflow."""

import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

import hypervisor_workflow as workflow


class WorkflowTests(unittest.TestCase):
    def test_default_profiles_keep_isa_consistent(self):
        profiles = (
            "config/riscv_rv64_handcar.config",
            "config/riscv_rv64_twostage_handcar.config",
            "fpix/config/riscv_rv64_hypervisor.config",
        )
        declarations = [ET.parse(workflow.ROOT / path).find("simulator_config_string").get("value")
                        for path in profiles]
        self.assertEqual(declarations, [declarations[0]] * len(profiles))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = []
        for option in ("handcar-so", "ptg-lib", "m1-config", "generator-config", "fpix-config"):
            path = self.root / option
            path.write_bytes(option.encode())
            self.args += ["--" + option, str(path)]
        self.artifacts = self.root / "artifacts"
        self.args += ["--artifact-root", str(self.artifacts)]
        for patch in (
            mock.patch.dict(os.environ, {"FORCE_SOURCED": "True"}),
            mock.patch.object(workflow.sys, "version_info", (3, 12)),
            mock.patch.object(workflow.sys, "platform", "linux"),
            mock.patch("sys.stdout", new_callable=io.StringIO),
            mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def invoke(self, extra=(), codes=(), launch_error=None, mutation=None):
        returns = iter(codes)

        def launch(command, **kwargs):
            self.assertTrue(kwargs["start_new_session"])
            self.assertNotIn("shell", kwargs)
            self.assertEqual(kwargs["cwd"], str(workflow.ROOT))
            self.assertEqual(kwargs["env"]["PTG_LIB_PATH"], str(self.root / "ptg-lib"))
            if launch_error:
                raise launch_error
            kwargs["stdout"].write(b"runner output retained\n")
            if "--artifact-root" in command:
                directory = command[command.index("--artifact-root") + 1] + "/child-run"
                marker = "Run directory" if "run_ptg_fault_v2.py" in command[2] else "Artifacts"
                kwargs["stdout"].write(f"{marker}: {directory}\n".encode())
                kwargs["stdout"].write(b"unrelated Artifacts: /wrong\nArtifacts: relative\n")
            if mutation:
                mutation()
            process = mock.Mock(pid=987654321, returncode=next(returns, 0))
            process.wait.return_value = process.returncode
            return process

        old = set(self.artifacts.glob("*/workflow.json"))
        with mock.patch.object(workflow.subprocess, "Popen", side_effect=launch) as popen:
            rc = workflow.main(self.args + list(extra))
        new = set(self.artifacts.glob("*/workflow.json")) - old
        self.assertEqual(len(new), 1)
        manifest = new.pop()
        return rc, json.loads(manifest.read_text()), popen

    def test_defaults_and_explicit_libraries(self):
        args = workflow.parse_args(["--handcar-so", "candidate.so", "--ptg-lib", "ptg.so"])
        self.assertEqual((args.profile, args.jobs, args.timeout), ("quick", 8, 120))
        self.assertEqual(args.artifact_root, workflow.ROOT / "output/hypervisor_workflow")
        self.assertEqual(args.m1_config, workflow.ROOT / "config/riscv_rv64_handcar.config")
        self.assertEqual(
            args.generator_config, workflow.ROOT / "config/riscv_rv64_twostage_handcar.config"
        )
        self.assertEqual(args.fpix_config, workflow.ROOT / "fpix/config/riscv_rv64_hypervisor.config")
        for argv in ([], ["--handcar-so", "a"], ["--ptg-lib", "b"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as error:
                workflow.parse_args(argv)
            self.assertEqual(error.exception.code, 2)

    def test_bad_profile_numbers_and_install_options_never_launch(self):
        for extra in (
            ["--profile", "smoke"],
            ["--profile", "FULL"],
            ["--jobs", "0"],
            ["--jobs", "bad"],
            ["--timeout", "nan"],
            ["--timeout", "inf"],
            ["--timeout", "0"],
            ["--timeout", "-1"],
            ["--install"],
            ["--build"],
        ):
            with self.subTest(extra=extra), mock.patch.object(
                workflow.subprocess, "Popen"
            ) as popen, self.assertRaises(SystemExit) as error:
                workflow.main(self.args + extra)
            self.assertEqual(error.exception.code, 2)
            popen.assert_not_called()

    def test_help_needs_no_environment_or_libraries(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit) as error:
            workflow.main(["--help"])
        self.assertEqual(error.exception.code, 0)

    def test_quick_is_not_full_and_uses_exact_unit_names(self):
        rc, report, popen = self.invoke()
        self.assertEqual(rc, 0)
        self.assertEqual(report["profile"], "quick")
        self.assertEqual(
            [s["name"] for s in report["commands"]],
            [Path(name).stem for _, name in workflow.UNIT_TESTS] + ["preflight", "smoke"],
        )
        self.assertEqual(popen.call_count, 8)
        names = []
        for stage in report["commands"][:6]:
            command = stage["command"]
            self.assertEqual(command[2:5], ["-m", "unittest", "discover"])
            name = command[command.index("-p") + 1]
            self.assertNotIn("*", name)
            names.append(name)
        self.assertEqual(
            names,
            [
                "test_manage.py",
                "test_upstream.py",
                "test_hypervisor_m1.py",
                "test_ptg_fault_v2_runner.py",
                "test_ptg_replay_audit.py",
                "test_hypervisor_workflow.py",
            ],
        )
        smoke = report["commands"][-1]["command"]
        self.assertEqual(smoke[smoke.index("--profile") + 1], "smoke")

    def test_m1_has_only_preflight_and_default_106_matrix(self):
        rc, report, _ = self.invoke(["--profile", "m1", "--jobs", "3", "--timeout", "7"])
        self.assertEqual(rc, 0)
        self.assertEqual([s["name"] for s in report["commands"]], ["preflight", "m1"])
        for stage in report["commands"]:
            command = stage["command"]
            self.assertEqual(command[command.index("--config") + 1], str(self.root / "m1-config"))
            self.assertEqual(command[command.index("--jobs") + 1], "3")
            self.assertEqual(float(command[command.index("--timeout") + 1]), 7)
            self.assertNotIn("--seed", command)
        self.assertIsNone(report["commands"][-1]["timeout"])

    def test_full_preserves_three_fault_seeds_both_configs_and_no_install(self):
        rc, report, popen = self.invoke(["--profile", "full"])
        self.assertEqual(rc, 0)
        self.assertEqual(popen.call_count, 13)
        self.assertEqual(
            [s["name"] for s in report["commands"]][-7:],
            ["preflight", "smoke", "m1", "fault_v2", "ptg_context_contracts", "ptg_context",
             "ptg_cpp_mapper"]
        )
        for stage in report["commands"]:
            command = stage["command"]
            self.assertEqual(command[0], workflow.sys.executable)
            self.assertFalse(set(command) & {"install", "build", "make", "prepare", "--seed"})
            if "--handcar-so" in command:
                self.assertEqual(
                    command[command.index("--handcar-so") + 1], str(self.root / "handcar-so")
                )
                self.assertEqual(
                    command[command.index("--ptg-lib") + 1], str(self.root / "ptg-lib")
                )
        fault = report["commands"][-4]
        self.assertIsNone(fault["timeout"])
        for name in ("generator-config", "fpix-config"):
            self.assertEqual(
                fault["command"][fault["command"].index("--" + name) + 1], str(self.root / name)
            )
        self.assertNotIn("--jobs", fault["command"])
        self.assertNotIn("--timeout", fault["command"])
        self.assertEqual(set(report["input_configs"]), {"m1", "generator", "fpix"})

    def test_preflight_only_for_every_profile(self):
        for profile in ("quick", "m1", "full"):
            with self.subTest(profile=profile):
                rc, report, popen = self.invoke(["--profile", profile, "--preflight-only"])
                self.assertEqual(rc, 0)
                self.assertTrue(report["preflight_only"])
                self.assertEqual(popen.call_count, 1)
                self.assertEqual(report["commands"][0]["name"], "preflight")
                self.assertIn("--preflight", report["commands"][0]["command"])

    def test_each_stage_failure_propagates_and_skips_all_later_stages(self):
        for index in range(13):
            with self.subTest(index=index):
                rc, report, popen = self.invoke(["--profile", "full"], codes=[0] * index + [7])
                self.assertEqual((rc, report["rc"], report["status"]), (7, 7, "failed"))
                self.assertEqual(popen.call_count, index + 1)
                self.assertEqual(report["commands"][index]["rc"], 7)
                self.assertTrue(
                    all(
                        s["status"] == "skipped" and s["rc"] is None
                        for s in report["commands"][index + 1 :]
                    )
                )
                self.assertEqual(report["libraries_before"], report["libraries_after"])

    def test_missing_source_environment_does_not_launch(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            rc, report, popen = self.invoke()
        self.assertEqual(rc, 2)
        popen.assert_not_called()
        self.assertIn("source setenv.bash", report["errors"][0])

    def test_wrong_python_does_not_launch(self):
        with mock.patch.object(workflow.sys, "version_info", (3, 11)):
            rc, report, popen = self.invoke()
        self.assertEqual(rc, 2)
        popen.assert_not_called()
        self.assertIn("Python 3.12", report["errors"][0])

    def test_missing_explicit_library_never_uses_environment_fallback(self):
        (self.root / "handcar-so").unlink()
        with mock.patch.dict(os.environ, {"PTG_LIB_PATH": "/installed/libptg.so"}):
            rc, report, popen = self.invoke()
        self.assertEqual(rc, 2)
        popen.assert_not_called()
        self.assertIsNone(report["libraries_before"]["handcar_so"]["sha256"])

    def test_missing_config_does_not_launch(self):
        (self.root / "generator-config").unlink()
        rc, _, popen = self.invoke(["--profile", "full"])
        self.assertEqual(rc, 2)
        popen.assert_not_called()

    def test_unique_directories_preserve_old_manifest_and_logs(self):
        _, first, _ = self.invoke()
        manifest = Path(first["run_dir"]) / "workflow.json"
        original = manifest.read_bytes()
        log = Path(first["commands"][0]["log"])
        log_original = log.read_bytes()
        _, second, _ = self.invoke()
        self.assertNotEqual(first["run_dir"], second["run_dir"])
        self.assertEqual(manifest.read_bytes(), original)
        self.assertEqual(log.read_bytes(), log_original)

    def test_manifest_has_hashes_durations_logs_and_exact_child_directories(self):
        rc, report, _ = self.invoke(["--profile", "full"])
        self.assertEqual(rc, 0)
        self.assertEqual(report["libraries_before"], report["libraries_after"])
        for record in (*report["libraries_before"].values(), *report["input_configs"].values()):
            self.assertEqual(len(record["sha256"]), 64)
        self.assertGreaterEqual(report["duration"], 0)
        for stage in report["commands"]:
            self.assertGreaterEqual(stage["duration"], 0)
            self.assertEqual((stage["rc"], stage["status"]), (0, "passed"))
            self.assertIn("runner output retained", Path(stage["log"]).read_text())
            expected = (
                [str(Path(report["run_dir"]) /
                     {"ptg_context": "contexts", "ptg_cpp_mapper": "cpp_mapper"}.get(
                         stage["name"], stage["name"]) / "child-run")]
                if stage["name"] in ("smoke", "m1", "fault_v2", "ptg_context", "ptg_cpp_mapper")
                else []
            )
            self.assertEqual(stage["run_directories"], expected)

    def test_library_change_cannot_report_success(self):
        rc, report, _ = self.invoke(
            mutation=lambda: (self.root / "handcar-so").write_bytes(b"new")
        )
        self.assertEqual((rc, report["status"]), (1, "failed"))
        self.assertNotEqual(report["libraries_before"], report["libraries_after"])
        self.assertIn("Library changed", report["errors"][0])

    def test_start_failure_keeps_manifest_and_skips_later_stages(self):
        rc, report, popen = self.invoke(launch_error=OSError("cannot execute"))
        self.assertEqual((rc, popen.call_count), (2, 1))
        self.assertEqual(report["commands"][0]["error"], "cannot execute")
        self.assertTrue(all(s["status"] == "skipped" for s in report["commands"][1:]))

    def test_signal_exit_is_failure_with_original_stage_return_code(self):
        rc, report, popen = self.invoke(codes=[-15])
        self.assertEqual((rc, popen.call_count), (143, 1))
        self.assertEqual(report["commands"][0]["rc"], -15)

    def test_timeout_and_interrupt_cleanup_and_failfast(self):
        for error, code, status in (
            (subprocess.TimeoutExpired("mock", 1), 124, "timeout"),
            (KeyboardInterrupt(), 130, "interrupted"),
        ):
            with self.subTest(status=status):
                process = mock.Mock(pid=987654321, returncode=-9)
                process.wait.side_effect = error
                with mock.patch.object(
                    workflow.subprocess, "Popen", return_value=process
                ) as popen, mock.patch.object(workflow, "stop_process_tree") as stop:
                    old = set(self.artifacts.glob("*/workflow.json"))
                    self.assertEqual(workflow.main(self.args), code)
                manifest = (set(self.artifacts.glob("*/workflow.json")) - old).pop()
                report = json.loads(manifest.read_text())
                self.assertEqual(report["status"], status)
                self.assertEqual(popen.call_count, 1)
                stop.assert_called_once_with(process)
                self.assertTrue(all(s["status"] == "skipped" for s in report["commands"][1:]))

    def test_cleanup_only_targets_owned_groups_and_checks_pid_identity(self):
        table = {
            100: (1, 100, "10"),
            101: (100, 101, "11"),
            102: (101, 101, "12"),
            200: (1, 200, "20"),
        }

        def stat(path, *args, **kwargs):
            pid = int(path.parent.name)
            parent, group, start = table[pid]
            fields = ["S", str(parent), str(group)] + ["0"] * 16 + [start]
            return f"{pid} (fixture) " + " ".join(fields)

        process = mock.Mock(pid=100, returncode=None)
        with mock.patch.object(
            Path, "iterdir", return_value=[Path(f"/proc/{p}") for p in table]
        ), mock.patch.object(Path, "read_text", stat), mock.patch.object(
            workflow.os, "killpg"
        ) as kill, mock.patch.object(workflow.time, "sleep"):
            workflow.stop_process_tree(process)
        self.assertEqual(
            set(call.args for call in kill.call_args_list),
            {(p, sig) for p in (100, 101) for sig in (signal.SIGTERM, signal.SIGKILL)},
        )
        process.wait.assert_called_once_with()

    def test_cleanup_never_signals_reaped_process(self):
        with mock.patch.object(workflow.os, "killpg") as kill:
            workflow.stop_process_tree(mock.Mock(pid=100, returncode=0))
        kill.assert_not_called()

    def test_cleanup_skips_recycled_descendant_pid(self):
        reads = {}

        def stat(path, *args, **kwargs):
            pid = int(path.parent.name)
            reads[pid] = reads.get(pid, 0) + 1
            start = "new" if pid == 101 and reads[pid] > 1 else "old"
            parent = "1" if pid == 100 else "100"
            return f"{pid} (fixture) " + " ".join(["S", parent, str(pid)] + ["0"] * 16 + [start])

        with mock.patch.object(
            Path, "iterdir", return_value=[Path("/proc/100"), Path("/proc/101")]
        ), mock.patch.object(Path, "read_text", stat), mock.patch.object(
            workflow.os, "killpg"
        ) as kill, mock.patch.object(workflow.time, "sleep"):
            workflow.stop_process_tree(mock.Mock(pid=100, returncode=None))
        self.assertEqual([call.args[0] for call in kill.call_args_list], [100, 100])

    def test_missing_unit_file_cannot_silently_pass_zero_tests(self):
        with mock.patch.object(workflow, "UNIT_TESTS", (("utils", "missing_test.py"),)):
            rc, report, popen = self.invoke()
        self.assertEqual(rc, 2)
        popen.assert_not_called()
        self.assertIn("Missing required unit test", report["errors"][0])


if __name__ == "__main__":
    unittest.main()
