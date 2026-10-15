"""Runner tests: no FORCE, FPIX, ctypes or full regression subprocess is run."""

import argparse
import copy
import io
import json
import os
import runpy
import shlex
import subprocess
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import run_ptg_fault_v2 as runner
from test_ptg_replay_audit import traces


REPO_ROOT = Path(__file__).resolve().parents[3]


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        for relative in (
            "config/riscv_rv64_twostage.config",
            "fpix/config/riscv_rv64_hypervisor.config",
            "tests/riscv/ptg_fault_v2_fctrl.py",
            "utils/regression/config/_riscv_rv64_fcfg.py",
        ):
            self.write(self.repo / relative, (REPO_ROOT / relative).read_text())
        for relative in (
            "bin/friscv",
            "bin/SimApiHANDCAR.so",
            "fpix/bin/fpix_riscv",
            "utils/regression/seedgen/bin/seedgen.so",
            "utils/regression/run_ptg_fault_v2.py",
            "utils/regression/ptg_replay_audit.py",
            "utils/regression/run_hypervisor_m1.py",
            "utils/regression/applications/fpix_riscv/FpixExecutor.py",
            "tests/riscv/ptg_fault_v2_ctypes_test.py",
        ):
            self.write(self.repo / relative, "fixture\n")
        (self.repo / "bin/friscv").chmod(0o755)
        (self.repo / "fpix/bin/fpix_riscv").chmod(0o755)
        self.handcar = self.root / "isolated library/selected.so"
        self.ptg = self.root / "libptg.so"
        self.write(self.handcar, "isolated handcar\n")
        self.write(self.ptg, "ptg\n")
        self.artifacts = self.root / "artifacts"
        self.args = [
            "--artifact-root",
            str(self.artifacts),
            "--handcar-so",
            str(self.handcar),
            "--ptg-lib",
            str(self.ptg),
            "--seed",
            "0x1",
        ]

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def prepare(self):
        destination = self.root / "run"
        destination.mkdir()
        return runner._prepare_run(
            self.repo,
            destination,
            self.repo / "config/riscv_rv64_twostage.config",
            self.repo / "fpix/config/riscv_rv64_hypervisor.config",
            self.handcar,
        )

    @staticmethod
    def summary_text(count=330):
        return (
            "Generate: {0}\nGenerate Fails: 0\nISS Sim: {0}\nISS Sim Fails: 0\n"
            "Total Tasks: {0}\nTask Fails: 0\n"
        ).format(count)

    def loader_logs(self, directory, count=330, selected=None, stages=None):
        if selected is None:
            selected = self.handcar
        if stages is None:
            stages = ("bin/friscv", "fpix/bin/fpix_riscv")
        for stage_index, stage in enumerate(stages):
            for index in range(count):
                pid = stage_index * count + index + 1000
                self.write(
                    directory / "trace.{}".format(pid),
                    " {pid}:\tinitialize program: {program}\n"
                    " {pid}:\ttransferring control: {program}\n"
                    " {pid}:\tcalling init: {library}\n".format(
                        pid=pid, program=self.repo / stage, library=selected
                    ),
                )

    def fake_run(self, command, cwd, env, log_path):
        self.assertEqual(cwd, self.repo)
        self.assertEqual(env["PTG_LIB_PATH"], str(self.ptg))
        self.write(log_path, "mock subprocess output\n")
        if "master_run.py" not in command[1]:
            return 0
        self.assertEqual(env["LD_DEBUG"], "libs")
        self.assertEqual(command[-2:], ["-k", "all"])
        seed_root = Path(command[command.index("--target-dir") + 1])
        for option in ("-f", "-c"):
            self.assertEqual(Path(command[command.index(option) + 1]).parent, seed_root.parent)
        self.write(seed_root / "output/regression/regression_summary.log", self.summary_text())
        self.loader_logs(Path(env["LD_DEBUG_OUTPUT"]).parent)
        generation, replay = traces()
        image = bytearray(64)
        image[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", image, 18, 243)
        struct.pack_into("<Q", image, 24, 0x50000000)
        for index in range(330):
            case = seed_root / "output/regression" / f"task_{index}" / "00000"
            self.write(case / "sim.log", generation)
            self.write(case / "fpix_sim.log", replay)
            (case / "fixture.Default.ELF").write_bytes(image)
        return 0

    def run_main(self, side_effect=None, args=None):
        with mock.patch.object(
            runner, "__file__", str(self.repo / "utils/regression/run_ptg_fault_v2.py")
        ), mock.patch.object(
            runner, "_source_record", return_value={"dirty": True, "head": "mock-head"}
        ), mock.patch.object(
            runner, "_run_logged", side_effect=side_effect or self.fake_run
        ) as execute, mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            code = runner.main(self.args if args is None else args)
        manifests = sorted(
            self.artifacts.glob("run_*/manifest.json"), key=lambda p: p.stat().st_mtime
        )
        return code, json.loads(manifests[-1].read_text()), execute

    def test_usage_defaults_and_seed_validation(self):
        args = runner._parse_args([])
        self.assertIsNone(args.seed)
        self.assertEqual(args.handcar_so, REPO_ROOT / "utils/handcar/handcar_cosim.so")
        self.assertEqual(runner.DEFAULT_SEEDS, ("0x15c0ffee", "0x5eed1234", "0xc001d00d"))
        self.assertEqual(runner.EXPECTED_TASKS, 330)
        args = runner._parse_args(["--seed", "16", "--seed", "0xffffffffffffffff"])
        self.assertEqual(args.seed, ["0x10", "0xffffffffffffffff"])
        for value in ("-1", "0x10000000000000000", "bad"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                runner._seed_value(value)

    def test_explicit_ptg_does_not_fall_back(self):
        with mock.patch.dict(os.environ, {"PTG_LIB_PATH": str(self.ptg)}):
            self.assertEqual(runner._resolve_ptg_lib(self.repo, None), self.ptg)
            with self.assertRaises(FileNotFoundError):
                runner._resolve_ptg_lib(self.repo, self.root / "missing.so")

    def test_abi_environment_and_interpreter_path_are_preserved(self):
        original = {
            "PATH": "/custom/bin:" + str(Path(sys.executable).parent),
            "PYTHONPATH": "/custom/python",
            "LD_LIBRARY_PATH": "/existing/abi",
            "LD_PRELOAD": "/existing/preload.so",
            "PYTHONHOME": "/existing/python",
            "ISS_SO_PATH": "/old/handcar.so",
        }
        with mock.patch.dict(os.environ, original, clear=True):
            env = runner._regression_env(self.repo, self.ptg)
        for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "ISS_SO_PATH"):
            self.assertEqual(env[key], original[key])
        self.assertTrue(env["PYTHONPATH"].endswith(":/custom/python"))
        self.assertEqual(env["PATH"].split(":"), [str(Path(sys.executable).parent), "/custom/bin"])

    def test_isolated_library_needs_no_installed_handcar(self):
        self.assertFalse((self.repo / "utils/handcar/handcar_cosim.so").exists())
        runner._check_regression_prerequisites(self.repo, self.handcar)
        with self.assertRaisesRegex(RuntimeError, "missing.so"):
            runner._check_regression_prerequisites(self.repo, self.root / "missing.so")

    def test_missing_or_nonexecutable_binary_is_rejected(self):
        (self.repo / "bin/friscv").chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "not executable"):
            runner._check_regression_prerequisites(self.repo, self.handcar)

    def test_generated_matrix_and_configs_preserve_original_settings(self):
        source_control = self.repo / "tests/riscv/ptg_fault_v2_fctrl.py"
        before = runner._file_record(source_control)
        originals = runpy.run_path(str(source_control))["control_items"]
        control, workflow, configs = self.prepare()
        generated = runpy.run_path(str(control))["control_items"]
        self.assertEqual(len(generated), 330)
        for original, item in zip(originals, generated):
            expected = copy.deepcopy(original)
            expected["fname"] = str(source_control.parent / original["fname"])
            expected["generator"]["--cfg"] = str(configs["generator"])
            self.assertEqual(item, expected)
        self.assertEqual(runner._file_record(source_control), before)
        for name, relative in (
            ("generator", "config/riscv_rv64_twostage.config"),
            ("fpix", "fpix/config/riscv_rv64_hypervisor.config"),
        ):
            expected_tree = ET.parse(str(self.repo / relative))
            expected_tree.find("simulator_shared_object").set("file", str(self.handcar))
            self.assertEqual(
                ET.tostring(ET.parse(str(configs[name])).getroot()),
                ET.tostring(expected_tree.getroot()),
            )
        options = dict(runpy.run_path(str(workflow))["sequence_app_opts"])
        self.assertEqual(options["fpix_riscv"]["cfg"], str(configs["fpix"]))
        self.assertEqual(options["fpix_riscv"]["iss_so_path"], str(self.handcar))

    def test_actual_executor_commands_use_both_generated_configs(self):
        with mock.patch.dict(sys.modules, {"seedgen": mock.Mock()}):
            from applications.force.ForceExecutor import ForceExecutor
            from applications.fpix_riscv.FpixExecutor import FpixExecutor
            from applications.fpix_riscv.FpixInit import (
                FpixParametersProcessor,
                process_fpix_control_data,
            )
            from common.sys_utils import SysUtils

        control, workflow, configs = self.prepare()
        options = dict(runpy.run_path(str(workflow))["sequence_app_opts"])
        fpix_options = options["fpix_riscv"]
        cmd_options = SimpleNamespace(
            mProgramPath=str(self.repo / "utils/regression"),
            option_def=lambda key: fpix_options.get(key.split(".")[-1]),
        )
        params = FpixParametersProcessor(cmd_options).mAppParameters
        fpix_control = {}
        process_fpix_control_data(fpix_control, params)
        generator = runpy.run_path(str(control))["control_items"][0]["generator"]
        generator["path"] = options["force"]["path"]
        item = SimpleNamespace(
            generator=generator,
            fpix_riscv=fpix_control,
            max_instr=100000,
            num_chips=1,
            num_cores=1,
            num_threads=1,
            seed="0x1",
            suffix=None,
            no_sim=False,
            timeout=600,
        )
        force = ForceExecutor()
        force.load(item)
        force_command = shlex.split(force.force_cmd % "fixture_force.py")
        self.assertEqual(
            force_command[force_command.index("--cfg") + 1], str(configs["generator"])
        )
        fpix = FpixExecutor()
        fpix.load(item)
        fpix.task_name = "fixture_force"
        with mock.patch.object(
            fpix, "locate_test_case", return_value="fixture.Default.ELF"
        ), mock.patch.object(fpix, "extract_results", return_value={}), mock.patch.object(
            SysUtils, "exec_process", return_value=(0,)
        ) as execute:
            self.assertTrue(fpix.execute())
        fpix_command = shlex.split(execute.call_args[0][0])
        self.assertEqual(execute.call_args[0][1:3], ("fpix_console.log", "fpix_console.log"))
        self.assertEqual(fpix_command[fpix_command.index("--cfg") + 1], str(configs["fpix"]))

    def test_invalid_xml_library_node_is_rejected(self):
        self.write(self.repo / "fpix/config/riscv_rv64_hypervisor.config", "<config/>")
        with self.assertRaisesRegex(RuntimeError, "H-enabled"):
            self.prepare()

    def test_missing_h_is_rejected(self):
        path = self.repo / "fpix/config/riscv_rv64_hypervisor.config"
        self.write(path, path.read_text().replace("RV64IMAFDCVH", "RV64IMAFDCV"))
        with self.assertRaisesRegex(RuntimeError, "H-enabled"):
            self.prepare()

    def test_matrix_size_cannot_silently_change(self):
        self.write(self.repo / "tests/riscv/ptg_fault_v2_fctrl.py", "control_items = []\n")
        with self.assertRaisesRegex(RuntimeError, "exactly 330"):
            self.prepare()

    def test_loader_evidence_checks_every_process_in_both_stages(self):
        directory = self.root / "loader"
        self.loader_logs(directory)
        self.write(directory / "trace.python", "initialize program: /usr/bin/python3\n")
        evidence = runner._check_loaded_libraries(directory, self.handcar, self.repo)
        self.assertEqual(evidence["errors"], [])
        self.assertEqual(len(evidence["generation"]), 330)
        self.assertEqual(len(evidence["standalone_iss"]), 330)
        self.assertTrue(all(item["selected_loaded"] for item in evidence["generation"]))

    def test_config_mentions_and_loader_searches_do_not_prove_loading(self):
        directory = self.root / "loader"
        self.write(
            directory / "trace.1",
            "initialize program: {}\ntrying file={}\n".format(
                self.repo / "bin/friscv", self.handcar
            ),
        )
        evidence = runner._check_loaded_libraries(directory, self.handcar, self.repo)
        self.assertFalse(evidence["generation"][0]["selected_loaded"])
        self.assertTrue(evidence["errors"])

    def test_wrong_iss_library_and_missing_stage_are_rejected(self):
        directory = self.root / "loader"
        self.loader_logs(directory, count=1, selected=self.repo / "utils/handcar/handcar_cosim.so")
        evidence = runner._check_loaded_libraries(directory, self.handcar, self.repo)
        self.assertTrue(
            any("Unexpected installed Handcar" in error for error in evidence["errors"])
        )
        self.assertTrue(any("standalone_iss" in error for error in evidence["errors"]))

    def test_one_wrong_iss_process_fails_despite_correct_generation_and_counts(self):
        directory = self.root / "loader"
        self.loader_logs(directory)
        self.write(
            directory / "trace.1330",
            "initialize program: {}\ncalling init: {}\n".format(
                self.repo / "fpix/bin/fpix_riscv", self.repo / "utils/handcar/handcar_cosim.so"
            ),
        )
        evidence = runner._check_loaded_libraries(directory, self.handcar, self.repo)
        self.assertTrue(all(item["selected_loaded"] for item in evidence["generation"]))
        self.assertEqual(len(evidence["standalone_iss"]), 330)
        self.assertEqual(sum(item["selected_loaded"] for item in evidence["standalone_iss"]), 329)
        self.assertTrue(evidence["errors"])

    def test_summary_checks_failures_counts_and_freshness(self):
        summary = self.root / "summary.log"
        self.write(summary, self.summary_text())
        self.assertEqual(runner._check_summary(summary, 0)["Total Tasks"], 330)
        with self.assertRaisesRegex(RuntimeError, "current summary"):
            runner._check_summary(summary, summary.stat().st_mtime + 1)
        for text in (
            self.summary_text(329),
            self.summary_text().replace("ISS Sim Fails: 0", "ISS Sim Fails: 1"),
            "Total Tasks: 330\n",
        ):
            self.write(summary, text)
            with self.assertRaises(RuntimeError):
                runner._check_summary(summary, 0)

    def test_source_dirty_and_git_failure_are_not_hidden(self):
        responses = [
            subprocess.CompletedProcess([], 0, "/checkout\n", ""),
            subprocess.CompletedProcess([], 0, "abcdef\n", ""),
            subprocess.CompletedProcess([], 0, " M dirty.cc\n", ""),
        ]
        with mock.patch.object(runner.subprocess, "run", side_effect=responses):
            self.assertTrue(runner._source_record(self.repo)["dirty"])
        with mock.patch.object(
            runner.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 128, "", "not a repo"),
        ):
            record = runner._source_record(self.repo)
        self.assertIsNone(record["dirty"])
        self.assertEqual(record["head"]["return_code"], 128)

    def test_main_records_commands_hashes_summary_and_load_proof(self):
        code, manifest, execute = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(manifest["return_code"], 0)
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(manifest["results"][0]["counts"]["Total Tasks"], 330)
        self.assertEqual(len(manifest["results"][0]["load_evidence"]["standalone_iss"]), 330)
        self.assertEqual(manifest["inputs"]["handcar_so"], runner._file_record(self.handcar))
        self.assertEqual(manifest["inputs_after"], manifest["inputs"])
        self.assertTrue(manifest["sources"]["force"]["dirty"])
        self.assertTrue(all(command["return_code"] == 0 for command in manifest["commands"]))

    def test_repeated_runs_never_overwrite_old_artifacts(self):
        code, first, _ = self.run_main()
        first_manifest = Path(first["run_root"]) / "manifest.json"
        original = first_manifest.read_bytes()
        second_code, second, _ = self.run_main()
        self.assertEqual((code, second_code), (0, 0))
        self.assertNotEqual(first["run_root"], second["run_root"])
        self.assertEqual(first_manifest.read_bytes(), original)

    def test_duplicate_seeds_run_once(self):
        code, manifest, execute = self.run_main(args=self.args + ["--seed", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(manifest["seeds"], ["0x1"])
        self.assertEqual(execute.call_count, 2)

    def test_custom_config_arguments_preserve_isa_in_run_copies(self):
        generator = self.root / "custom-generator.config"
        fpix = self.root / "custom-fpix.config"
        for path in (generator, fpix):
            self.write(
                path,
                '<config><simulator_shared_object file="old.so"/>'
                '<simulator_config_string value="--isa=RV64IMACH_zicclsm"/></config>',
            )
        code, manifest, _ = self.run_main(
            args=self.args + ["--generator-config", str(generator), "--fpix-config", str(fpix)]
        )
        self.assertEqual(code, 0)
        for name in ("generator", "fpix"):
            tree = ET.parse(manifest["generated"][name]["path"])
            self.assertEqual(tree.find("simulator_config_string").get("value"), "--isa=RV64IMACH_zicclsm")
            self.assertEqual(tree.find("simulator_shared_object").get("file"), str(self.handcar))

    def test_later_seeds_still_run_after_master_failure(self):
        def execute(*args):
            self.fake_run(*args)
            command = args[0]
            if "--seed" in command and command[command.index("--seed") + 1] == "0x1":
                return 8
            return 0

        code, manifest, process = self.run_main(
            side_effect=execute, args=self.args + ["--seed", "2"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(process.call_count, 3)
        self.assertEqual([item["return_code"] for item in manifest["results"]], [8, 0])

    def test_default_three_seeds_are_retained_without_running_regression(self):
        code, manifest, execute = self.run_main(side_effect=lambda *args: 7, args=self.args[:-2])
        self.assertEqual(code, 1)
        self.assertEqual(manifest["seeds"], list(runner.DEFAULT_SEEDS))
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(manifest["commands"][0]["return_code"], 7)

    def test_master_failure_keeps_summary_and_return_code(self):
        def execute(*args):
            self.fake_run(*args)
            return 9 if "master_run.py" in args[0][1] else 0

        code, manifest, _ = self.run_main(side_effect=execute)
        self.assertEqual(code, 1)
        self.assertEqual(manifest["results"][0]["return_code"], 9)
        self.assertIn("summary_text", manifest["results"][0])

    def test_missing_loader_evidence_fails_even_with_passing_summary(self):
        with mock.patch.object(self, "loader_logs"):
            code, manifest, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertTrue(any("loader records" in error for error in manifest["failures"]))

    def test_passing_summary_and_loader_cannot_hide_wrong_replay(self):
        def execute(*args):
            result = self.fake_run(*args)
            command = args[0]
            if "--target-dir" in command:
                root = Path(command[command.index("--target-dir") + 1])
                path = root / "output/regression/task_0/00000/fpix_sim.log"
                self.write(path, path.read_text().replace("cause=0xd", "cause=0x1"))
            return result
        code, manifest, _ = self.run_main(side_effect=execute)
        self.assertEqual(code, 1)
        self.assertTrue(any("replay traps mismatch" in e for e in manifest["failures"]))

    def test_missing_selected_library_is_setup_error_without_subprocess(self):
        self.handcar.unlink()
        code, manifest, execute = self.run_main()
        self.assertEqual(code, 2)
        execute.assert_not_called()
        self.assertEqual(manifest["return_code"], 2)
        self.assertTrue(manifest["failures"])

    def test_start_failure_is_recorded(self):
        code, manifest, _ = self.run_main(side_effect=OSError("cannot start"))
        self.assertEqual(code, 2)
        self.assertIsNone(manifest["commands"][0]["return_code"])
        self.assertIn("cannot start", manifest["failures"])

    def test_library_changed_during_run_is_rejected(self):
        def execute(*args):
            result = self.fake_run(*args)
            if "master_run.py" in args[0][1]:
                self.write(self.handcar, "changed handcar\n")
            return result

        code, manifest, _ = self.run_main(side_effect=execute)
        self.assertEqual(code, 1)
        self.assertIn("Input changed during run: handcar_so", manifest["failures"])

    def test_logged_process_captures_output_and_return_code(self):
        process = mock.Mock(stdout=io.StringIO("one\ntwo\n"))
        process.wait.return_value = 4
        log = self.root / "process.log"
        with mock.patch.object(
            runner.subprocess, "Popen", return_value=process
        ) as popen, mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(runner._run_logged(["mock"], self.repo, {"ABI": "kept"}, log), 4)
        self.assertEqual(log.read_text(), "one\ntwo\n")
        self.assertEqual(popen.call_args[1]["env"], {"ABI": "kept"})


if __name__ == "__main__":
    unittest.main()
