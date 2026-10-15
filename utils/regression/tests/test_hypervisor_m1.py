"""Validate legacy POST-PC archives and explicit instruction/next-PC v2 traces."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

SPEC = importlib.util.spec_from_file_location(
    "hypervisor_m1", Path(__file__).resolve().parents[1] / "run_hypervisor_m1.py"
)
m1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m1)


class Trace:
    def __init__(self, v2=False):
        self.v2 = v2
        self.lines = ([
            "# HANDCAR trace v2: PC(VA)=instruction address; "
            "NextPC(VA)=after step; Trap=take_trap event"
        ] if v2 else [])
        self.pc = 0x80011000
        self.count = 0

    def step(self, opcode, mnemonic, writes=None, memory=(), post=None):
        self.count += 1
        instruction_pc = self.pc
        self.pc = self.pc + 4 if post is None else post
        displayed_pc = instruction_pc if self.v2 else self.pc
        self.lines.extend(
            (
                f"Cpu 0 {self.count} ----",
                f"Cpu 0 PC(VA) 0x{displayed_pc:016x} op: 0x{opcode:016x} : {mnemonic}",
            )
        )
        if self.v2:
            self.lines.append(f"Cpu 0 NextPC(VA) 0x{self.pc:016x}")
        for reg, value in {"PC": self.pc, **(writes or {})}.items():
            self.lines.append(f"Cpu 0 Reg W {reg} val 0x{value:016x} mask 0xffffffffffffffff")
        for direction, bank, va, pa, size, data in memory:
            self.lines.append(
                f"Cpu 0 Mem {direction} bank {bank} VA 0x{va:016x} "
                f"PA 0x{pa:016x} size {size} bytes 0x{data}"
            )

    def finish(self):
        self.step(0x6F, "j pc + 0x0", post=self.pc)
        self.lines.extend(
            (
                f"Cpu 0 executed {self.count} instructions.",
                f"Executed {self.count} instructions, exit status (SUCCESS)",
            )
        )
        return "\n".join(self.lines) + "\n"


def fixture(kind, v2=False):
    trace, notices = (Trace(v2=True) if v2 else Trace()), []
    if kind == "two_stage":
        for i, ((va, pa), value, label) in enumerate(
            zip(m1.TWO_ADDRESSES, m1.TWO_VALUES, m1.TWO_LABELS)
        ):
            rd = i + 2
            trace.step(0xB7, "lui ra, 0x0", {"x1": va})
            memory = (
                [
                    m1.memory_event("R", va, pa, value & 0xFFFFFFFF, 4),
                    m1.memory_event("R", va + 4, pa + 4, value >> 32, 4),
                ]
                if i == 2
                else [m1.memory_event("R", va, pa, value)]
            )
            trace.step(0x6C00C073 | rd << 7, "hlv.d", {f"x{rd}": value}, memory)
            notices.append(f"[notice]Front-end: SUCCESS: {label}x{rd} = 0x{value:016X}")
    elif kind == "access":
        initial, stored = 0x1122334455667788, 0x8877665544332211
        trace.step(0xB7, "lui", {"x1": 0x40200000})
        trace.step(
            0x6C00C173,
            "hlv.d",
            {"x2": initial},
            [m1.memory_event("R", 0x40200000, 0x110200000, initial)],
        )
        trace.step(0xB7, "lui", {"x1": 0x40300000, "x3": stored})
        trace.step(
            0x6E30C073, "hsv.d", memory=[m1.memory_event("W", 0x40300000, 0x110300000, stored)]
        )
        trace.step(
            0x6C00C273,
            "hlv.d",
            {"x4": stored},
            [m1.memory_event("R", 0x40300000, 0x110300000, stored)],
        )
        trace.step(0x337, "lui", {"x6": 0x110300000})
        trace.step(
            0x33383, "ld", {"x7": stored}, [m1.memory_event("R", 0x110300000, 0x110300000, stored)]
        )
        trace.step(0xB7, "lui", {"x1": 0x40400000})
        trace.step(
            0x6830C2F3,
            "hlvx.wu",
            {"x5": 0xA1B2C3D4},
            [m1.memory_event("R", 0x40400000, 0x110400000, 0xA1B2C3D4, 4)],
        )
        trace.step(0x64502373, "csrr t1, hvip", {"x6": 4})
        notices.append("[notice]Front-end: HYPERVISOR ACCESS MATRIX: PASS")
    else:
        trace.step(0x337, "lui", {"x6": 0x20000})
        for i, (regs, sentinel) in enumerate(zip(m1.FAULT_REGS, m1.FAULT_SENTINELS)):
            target, entry = 0x80016000 + i * 0x1000, 0x80012000 + i * 0x1000
            gva, gpa, spa = (
                0x43000000 + i * 0x200000,
                0x86000000 + i * 0x200000,
                0x132000000 + i * 0x200000,
            )
            side_rd, cause = (28, 30, 29, 31)[i], (13, 15, 21, 23)[i]
            trace.step(0x437, "lui", {"x8": target})
            trace.step(0x30541073, "csrw mtvec, s0")
            trace.step(0x30200073, "mret", post=entry)
            trace.step(
                0xB7, "lui", {"x1": gva, "x2": sentinel if i % 2 == 0 else 0xDEADBEEF01234567}
            )
            fault_pc = trace.pc
            trace.step(
                0x6C00C173 if i % 2 == 0 else 0x6E20C073,
                "hlv.d" if i % 2 == 0 else "hsv.d",
                post=target,
            )
            values = (
                cause,
                fault_pc,
                gva,
                gpa >> 2 if i >= 2 else 0,
                0,
                m1.MSTATUS_EXPECTED | 0x8000000A00006080,
            )
            if v2:
                trace.lines.append(
                    f"Cpu 0 Trap trap_test cause=0x{cause:x} epc=0x{fault_pc:x} "
                    f"tval=0x{gva:x} tval2=0x{values[3]:x} tinst=0x0 target=0x{target:x} "
                    "from_priv=3 from_v=0 to_priv=3 to_v=0"
                )
            for csr, rd, value in zip((0x342, 0x341, 0x343, 0x34B, 0x34A, 0x300), regs, values):
                trace.step(csr << 20 | rd << 7 | 0x2073, "csrr", {f"x{rd}": value})
            if i % 2 == 0:
                trace.step(side_rd << 7 | 0x10013, "mv", {f"x{side_rd}": sentinel})
            else:
                trace.step(0xB7, "lui", {"x1": spa})
                trace.step(
                    side_rd << 7 | 0xB003,
                    "ld",
                    {f"x{side_rd}": sentinel},
                    [m1.memory_event("R", spa, spa, sentinel)],
                )
            name = (
                f"{'HLV' if i % 2 == 0 else 'HSV'}.D {'VS' if i < 2 else 'G'}-stage invalid leaf"
            )
            notices.append(
                f"[notice]Front-end: V2_RESULT name={name} pte_pa=0x{0x170008000 + i * 8:X} "
                f"old=0x1237 new=0x1236 mcause={cause} failing_gpa=0x{gpa if i >= 2 else 0:X}"
            )
        notices.append("[notice]Front-end: HLV/HSV INVALID VS/G PTE FAULT MATRIX: PASS")
    return trace.finish(), "\n".join(notices) + "\n"


class SemanticTests(unittest.TestCase):
    def test_v2_instruction_pc_and_actual_traps(self):
        for kind in m1.TEMPLATES:
            sim, log = fixture(kind, v2=True)
            result = m1.audit_semantics(kind, sim, log)
            self.assertTrue(result["evidence"])
        blocks, _ = m1.parse_trace(fixture("fault", v2=True)[0])
        fault = next(b for b in blocks if b["traps"])
        self.assertEqual(fault["pc"], 0x80012004)
        self.assertEqual(fault["post_pc"], 0x80016000)
        self.assertEqual(fault["traps"][0]["epc"], fault["pc"])

    def test_v2_missing_or_wrong_trap_is_rejected(self):
        sim, log = fixture("fault", v2=True)
        missing = "\n".join(line for line in sim.splitlines() if " Trap " not in line) + "\n"
        for broken in (missing, sim.replace("epc=0x80012004", "epc=0x80016000")):
            with self.assertRaisesRegex(ValueError, "actual trap event"):
                m1.audit_semantics("fault", broken, log)

    def test_v2_requires_distinct_next_pc_record(self):
        sim, log = fixture("two_stage", v2=True)
        broken = "\n".join(line for line in sim.splitlines() if " NextPC(VA) " not in line) + "\n"
        with self.assertRaisesRegex(ValueError, "incomplete instruction"):
            m1.audit_semantics("two_stage", broken, log)

    def test_all_positive_fixtures(self):
        for kind in m1.TEMPLATES:
            with self.subTest(kind=kind):
                evidence = m1.audit_semantics(kind, *fixture(kind))
                self.assertTrue(evidence["evidence"])
                self.assertGreater(evidence["instruction_count"], 0)

    def test_instruction_count_is_not_a_fixed_semantic_threshold(self):
        initialize = Trace.__init__

        def extra_instruction(trace):
            initialize(trace)
            trace.step(0x13, "nop")

        for kind in m1.TEMPLATES:
            count = m1.audit_semantics(kind, *fixture(kind))["instruction_count"]
            with mock.patch.object(Trace, "__init__", extra_instruction):
                result = m1.audit_semantics(kind, *fixture(kind))
            self.assertEqual(result["instruction_count"], count + 1)

    def test_exit_success_and_pass_do_not_override_fail(self):
        for failure in (
            "FAIL",
            "[fail]bad",
            "ERROR",
            "failed",
            "Traceback (most recent call last):",
        ):
            sim, log = fixture("access")
            with self.subTest(failure=failure), self.assertRaisesRegex(ValueError, "FAIL/ERROR"):
                m1.audit_semantics("access", sim, log + failure)

    def test_missing_truncated_and_concatenated_logs(self):
        sim, log = fixture("two_stage")
        for broken in (
            "",
            sim[:-1],
            sim[: sim.index("Cpu 0 executed")],
            sim + sim,
            sim.replace("mask 0xffffffffffffffff", "mask 0xffff", 1),
            sim.replace("size 8 bytes 0x3412fecaefbeadde", "size 8 bytes 0x3412"),
        ):
            with self.subTest(broken=broken[-70:]), self.assertRaises(ValueError):
                m1.audit_semantics("two_stage", broken, log)

    def test_wrong_sentinel_despite_success_notice(self):
        sim, log = fixture("two_stage")
        with self.assertRaisesRegex(ValueError, "sentinel"):
            m1.audit_semantics(
                "two_stage", sim.replace("val 0xdeadbeefcafe1234", "val 0x0000000000000050"), log
            )

    def test_final_register_not_arbitrary_earlier_match(self):
        sim, log = fixture("access")
        sim = sim.replace(
            "Cpu 0 executed",
            "Cpu 0 Reg W x2 val 0x0000000000000000 mask 0xffffffffffffffff\nCpu 0 executed",
        )
        with self.assertRaisesRegex(ValueError, "final x2"):
            m1.audit_semantics("access", sim, log)

    def test_memory_must_belong_to_its_instruction(self):
        sim, log = fixture("two_stage")
        lines = sim.splitlines()
        memory_indexes = [i for i, line in enumerate(lines) if " Mem " in line]
        a, b = memory_indexes[:2]
        lines[a], lines[b] = lines[b], lines[a]
        with self.assertRaisesRegex(ValueError, "trajectory"):
            m1.audit_semantics("two_stage", "\n".join(lines) + "\n", log)

    def test_cross_page_second_half_pa_and_data(self):
        sim, log = fixture("two_stage")
        for old, new in (
            ("PA 0x0000000140001000", "PA 0x0000000140000000"),
            ("bytes 0xd8c7b6a5", "bytes 0x00000000"),
        ):
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, "trajectory"):
                m1.audit_semantics("two_stage", sim.replace(old, new), log)

    def test_hvip_and_hsv_readback(self):
        sim, log = fixture("access")
        for old, new in (
            ("x6 val 0x0000000000000004", "x6 val 0x0000000000000200"),
            ("x7 val 0x8877665544332211", "x7 val 0x0000000000000000"),
        ):
            with self.subTest(old=old), self.assertRaises(ValueError):
                m1.audit_semantics("access", sim.replace(old, new), log)

    def test_wrong_trap_post_pc_not_instruction_start(self):
        sim, log = fixture("fault")
        with self.assertRaisesRegex(ValueError, "trap target"):
            m1.audit_semantics(
                "fault", sim.replace("0x0000000080016000", "0x0000000080012004"), log
            )

    def test_mepc_is_previous_post_pc(self):
        sim, log = fixture("fault")
        self.assertEqual(
            m1.audit_semantics("fault", sim, log)["evidence"][0]["fault_pc"], 0x80012004
        )
        with self.assertRaisesRegex(ValueError, "CSR 341"):
            m1.audit_semantics(
                "fault", sim.replace("x4 val 0x0000000080012004", "x4 val 0x0000000080016000"), log
            )

    def test_each_fault_csr_mask_sentinel_and_metadata(self):
        sim, log = fixture("fault")
        mutations = (
            ("x3 val 0x000000000000000d", "x3 val 0x0000000000000015"),
            ("x11 val 0x0000000080013004", "x11 val 0x0000000080012004"),
            ("x18 val 0x0000000043400000", "x18 val 0x0000000043000000"),
            ("x25 val 0x0000000021980000", "x25 val 0x0000000000000000"),
            ("x7 val 0x0000000000000000", "x7 val 0x0000000000000001"),
            ("val 0x8000004a00007880", "val 0x800000ca00007880"),
            ("val 0x8000004a00007880", "val 0x8000000a00007880"),
            ("val 0x8000004a00007880", "val 0x8000004a00006080"),
            ("x28 val 0x1111222233334444", "x28 val 0x0000000000000000"),
            ("bytes 0x0100ffffeeeedddd", "bytes 0x0000000000000000"),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                self.assertIn(old, sim)
                with self.assertRaises(ValueError):
                    m1.audit_semantics("fault", sim.replace(old, new), log)
        with self.assertRaisesRegex(ValueError, "V2 metadata"):
            m1.audit_semantics("fault", sim, log.replace("new=0x1236", "new=0x1234"))

    def test_csr_values_cannot_be_taken_from_another_scenario(self):
        sim, log = fixture("fault")
        sim = sim.replace("op: 0x00000000342021f3", "op: 0x0000000034202573")
        with self.assertRaisesRegex(ValueError, "CSR capture"):
            m1.audit_semantics("fault", sim, log)

    def test_fault_instruction_no_register_or_memory_effects(self):
        sim, log = fixture("fault")
        anchor = "Cpu 0 Reg W PC val 0x0000000080016000 mask 0xffffffffffffffff\n"
        for extra in (
            "Cpu 0 Reg W x2 val 0x0000000000000000 mask 0xffffffffffffffff\n",
            "Cpu 0 Mem W bank 0 VA 0x43000000 PA 0x132000000 size 8 bytes 0x0000000000000000\n",
        ):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "side effects"):
                m1.audit_semantics("fault", sim.replace(anchor, anchor + extra), log)

    def test_success_markers_are_exact_and_required(self):
        for kind in m1.TEMPLATES:
            sim, log = fixture(kind)
            for altered in ("", log + log, log.replace("[notice]Front-end:", "unrelated:")):
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    m1.audit_semantics(kind, sim, altered)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="m1-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        (self.repo / "tests/riscv").mkdir(parents=True)
        (self.repo / "py").mkdir()
        (self.repo / "py/runtime.json").write_text('{"keep": true}')
        for template in m1.TEMPLATES.values():
            (self.repo / "tests/riscv" / template).write_text("# unchanged template\n")
        self.paths = {}
        for name in ("handcar", "ptg", "friscv"):
            path = self.repo / name
            path.write_bytes(b"\x7fELF" + name.encode())
            self.paths[name] = path
        config = self.repo / "source.config"
        config.write_text(
            '<config_file><simulator_shared_object file="old.so"/>'
            '<simulator_config_string value="RV64IMAFDCVH"/>'
            '<memory_file file="py/runtime.json"/></config_file>'
        )
        self.paths["config"] = config
        self.args = m1.parse_args(
            [
                "--handcar-so",
                str(self.paths["handcar"]),
                "--ptg-lib",
                str(self.paths["ptg"]),
                "--artifact-root",
                str(self.root / "artifacts"),
                "--jobs",
                "3",
            ]
        )
        self.root_patch = mock.patch.object(m1, "ROOT", self.repo)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def prepared(self):
        return m1.prepare_run(
            self.args, self.paths, m1.config_dependencies(self.paths["config"], self.repo)
        )

    def completed(self, mutation=None, timeout=False, return_code=0):
        run, manifest, env = self.prepared()

        def launch(command, cwd, env, stdout, **kwargs):
            kind = next(k for k, v in m1.TEMPLATES.items() if command[4].endswith(v))
            sim, log = fixture(kind)
            log = (
                f"[notice]Initial seed = {command[2]}\n"
                f'[notice]Generating using test template "{command[4]}"...\n'
                f"[notice]Loading config file: {command[6]} ...\n"
                f"[notice]Simulator DLL: '{run / manifest['handcar']}'.\n"
                f" 123: calling init: {run / manifest['handcar']}\n"
                f" 123: calling init: {run / manifest['ptg']}\n" + log
            )
            if mutation:
                sim, log = mutation(kind, sim, log)
            if sim is not None:
                (cwd / "sim.log").write_text(sim)
            stdout.write(log.encode())
            stem = Path(m1.TEMPLATES[kind]).stem + ".Default"
            (cwd / (stem + ".ELF")).write_bytes(b"\x7fELFfixture")
            (cwd / (stem + ".S")).write_text("# assembly fixture\n")
            process = mock.Mock(pid=12345)
            process.wait.side_effect = (
                [subprocess.TimeoutExpired(command, 1), -9] if timeout else [return_code]
            )
            return process

        with mock.patch.object(m1.subprocess, "Popen", side_effect=launch), mock.patch.object(
            m1.os, "killpg"
        ) as kill:
            receipts = [m1.run_case(run, manifest, case, env) for case in manifest["cases"]]
            if timeout:
                self.assertEqual(kill.call_count, 3)
                kill.assert_called_with(12345, m1.signal.SIGKILL)
        m1.write_json(
            run / "receipts.json",
            {"manifest_sha256": m1.sha256(run / "manifest.json"), "cases": receipts},
        )
        return run

    def test_complete_run_and_audit_only_does_not_launch(self):
        run = self.completed()
        with mock.patch.object(m1.subprocess, "Popen") as launch, contextlib.redirect_stdout(
            io.StringIO()
        ):
            self.assertEqual(m1.main(["--audit-only", str(run)]), 0)
            launch.assert_not_called()
        result = json.loads((run / "results.json").read_text())
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["cases"]), 3)
        self.assertIn("3/3", (run / "summary.md").read_text())

    def test_exit_zero_fail_missing_log_wrong_library_and_seed(self):
        mutations = (
            lambda kind, sim, log: (sim, log + "FAIL\n"),
            lambda kind, sim, log: (None, log),
            lambda kind, sim, log: (sim[:-100], log),
            lambda kind, sim, log: (sim, log.replace("calling init:", "not actually loaded:")),
            lambda kind, sim, log: (sim, log.replace("Initial seed = 0x1", "Initial seed = 0x2")),
            lambda kind, sim, log: (sim, log.replace("Simulator DLL:", "Unrelated DLL:")),
            lambda kind, sim, log: (sim, log.replace("Loading config file:", "Unrelated config:")),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                run = self.completed(mutation)
                result = m1.audit_run(run)
                self.assertFalse(result["passed"])
                self.assertTrue(all(not case["passed"] for case in result["cases"]))

    def test_audit_failure_returns_one_and_reports_only_bad_case(self):
        run = self.completed(
            lambda kind, sim, log: (sim, log + ("FAIL\n" if kind == "fault" else ""))
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m1.main(["--audit-only", str(run)]), 1)
        result = json.loads((run / "results.json").read_text())
        self.assertEqual([case["passed"] for case in result["cases"]], [True, False, True])

    def test_requested_library_hash_must_match_archived_library(self):
        run = self.completed()
        self.paths["handcar"].write_bytes(b"\x7fELFwrong-library")
        result = m1.audit_run(run, self.args)
        self.assertFalse(result["passed"])
        self.assertIn("requested handcar hash", result["failures"][0])

    def test_absolute_xml_dependency_is_saved_and_bound(self):
        data = self.repo / "absolute.xml"
        data.write_text("<data/>")
        config = self.paths["config"]
        config.write_text(
            config.read_text().replace(
                "</config_file>", f'<instruction_file file="{data}"/></config_file>'
            )
        )
        run = self.completed()
        manifest = json.loads((run / "manifest.json").read_text())
        entry = next(
            (name, info)
            for name, info in manifest["inputs"].items()
            if info.get("live_absolute") == str(data)
        )
        self.assertEqual((run / entry[0]).read_text(), "<data/>")
        self.assertTrue(m1.audit_run(run)["passed"])
        data.write_text("<changed/>")
        self.assertFalse(m1.audit_run(run)["passed"])

    def test_timeout_overrides_fully_green_logs(self):
        run = self.completed(timeout=True)
        result = m1.audit_run(run)
        self.assertFalse(result["passed"])
        self.assertTrue(all(c["timeout"] and c["return_code"] == -9 for c in result["cases"]))
        self.assertIn("timed out", result["cases"][0]["failures"][0])

    def test_nonzero_exit_overrides_green_semantics(self):
        result = m1.audit_run(self.completed(return_code=7))
        self.assertFalse(result["passed"])
        self.assertTrue(all(c["return_code"] == 7 for c in result["cases"]))

    def test_stale_replaced_log_and_missing_elf_rejected(self):
        run = self.completed()
        (run / "access-seed-1/sim.log").write_text(fixture("two_stage")[0])
        (run / "fault-seed-1" / (Path(m1.TEMPLATES["fault"]).stem + ".Default.ELF")).unlink()
        result = m1.audit_run(run)
        self.assertFalse(result["passed"])
        self.assertIn("hash mismatch", result["cases"][0]["failures"][0])
        self.assertIn("missing/empty", result["cases"][1]["failures"][0])

    def test_mutated_template_config_library_and_manifest_bindings(self):
        names = (
            "inputs/templates/" + m1.TEMPLATES["access"],
            "inputs/derived.config",
            "inputs/bin/handcar/handcar",
            "inputs/force/py/runtime.json",
            "manifest.json",
        )
        for name in names:
            with self.subTest(name=name):
                run = self.completed()
                with (run / name).open("ab") as stream:
                    stream.write(b"\n ")
                self.assertFalse(m1.audit_run(run)["passed"])

    def test_execution_metadata_hash_and_missing_receipt(self):
        run = self.completed()
        record = run / "access-seed-1/execution.json"
        value = json.loads(record.read_text())
        value["timeout"] = True
        m1.write_json(record, value)
        self.assertIn("receipt hash", m1.audit_run(run)["cases"][0]["failures"][0])
        (run / "receipts.json").unlink()
        self.assertFalse(m1.audit_run(run)["passed"])

    def test_repeated_run_never_overwrites_existing_output(self):
        first, _, _ = self.prepared()
        sentinel = first / "do-not-touch"
        sentinel.write_text("user output")
        second, _, _ = self.prepared()
        self.assertNotEqual(first, second)
        self.assertEqual(sentinel.read_text(), "user output")
        self.assertEqual((first / "inputs/force/py/runtime.json").read_text(), '{"keep": true}')

    def test_preflight_failure_returns_two_without_generation(self):
        with mock.patch.object(
            m1, "preflight", side_effect=ValueError("missing dependency")
        ), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(m1.main(["--handcar-so", "absent", "--ptg-lib", "absent"]), 2)


class ConfigurationTests(unittest.TestCase):
    def test_preflight_diagnostic_preserves_error_before_loader_shutdown(self):
        error = b"RuntimeError: PTG library lacks Mapping Query/Strict Export v1\n"
        shutdown = b"  1234:\tcalling fini: /lib/libexample.so [0]\n" * 400
        self.assertEqual(m1.probe_diagnostic(error + shutdown), error.decode().strip())
        native_error = b"  1234:\tloader error\n"
        self.assertIn("loader error", m1.probe_diagnostic(native_error))

    def test_profiles_and_repeatable_seed_override(self):
        self.assertEqual(len(m1.case_matrix("smoke")), 3)
        cases = m1.case_matrix("m1")
        self.assertEqual(len(cases), 106)
        self.assertEqual(
            [c["seed"] for c in cases if c["kind"] == "two_stage"], list(range(1, 101))
        )
        self.assertEqual([c["seed"] for c in cases if c["kind"] == "access"], list(m1.FIXED_SEEDS))
        self.assertEqual(len(m1.case_matrix("m1", [1, 2, 1])), 6)
        args = m1.parse_args(
            [
                "--handcar-so",
                "new.so",
                "--ptg-lib",
                "ptg.so",
                "--seed",
                "1",
                "--seed",
                "0xdeadbeef",
            ]
        )
        self.assertEqual(args.seed, [1, 0xDEADBEEF])

    def test_required_explicit_libraries_invalid_numbers_and_help(self):
        for argv in (
            [],
            ["--ptg-lib", "ptg.so"],
            ["--handcar-so", "hc.so"],
            ["--jobs", "0"],
            ["--timeout", "nan"],
            ["--seed", "-1"],
            ["--seed", str(1 << 64)],
        ):
            with self.subTest(argv=argv), contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(SystemExit) as error:
                m1.parse_args(argv)
            self.assertEqual(error.exception.code, 2)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
            m1.parse_args(["--help"])
        self.assertEqual(error.exception.code, 0)

    def test_xml_only_library_attribute_changes(self):
        source = (
            b'<?xml version="1.0"?><!-- preserve -->\n<config_file>\n'
            b"<simulator_shared_object file = 'old.so'/>\n"
            b'<instruction_file file="a.xml"/><import_file file="b.config"/>'
            b'<simulator_config_string value="RV64IMAFDCVH"/></config_file>'
        )
        output = m1.derive_config(source, Path("/tmp/a&b.so"))
        self.assertEqual(output, source.replace(b"old.so", b"/tmp/a&amp;b.so"))
        self.assertEqual(
            ET.fromstring(output).find("simulator_config_string").attrib["value"], "RV64IMAFDCVH"
        )
        with self.assertRaises(ValueError):
            m1.derive_config(b"<config_file/>", Path("new.so"))

    def test_dependency_imports_and_missing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "base.config").write_text(
                '<config_file><instruction_file file="data.xml"/></config_file>'
            )
            (root / "data.xml").write_text("<instructions/>")
            (root / "main.config").write_text(
                '<config_file><import_file file="base.config"/></config_file>'
            )
            dependencies = m1.config_dependencies(root / "main.config", root)
            self.assertEqual(set(dependencies), {root / "base.config", root / "data.xml"})
            (root / "data.xml").unlink()
            with self.assertRaisesRegex(ValueError, "missing XML"):
                m1.config_dependencies(root / "main.config", root)

    def test_environment_has_no_implicit_python_or_ptg_fallback(self):
        with mock.patch.dict(
            os.environ,
            {
                "PYTHONPATH": "/wrong",
                "PATH": "/wrong",
                "PTG_LIB_PATH": "/wrong",
                "LD_PRELOAD": "evil.so",
            },
        ):
            env = m1.environment(Path("/snapshot"), Path("/snapshot/libptg.so"))
        self.assertEqual(env["PTG_LIB_PATH"], "/snapshot/libptg.so")
        self.assertEqual(env["FORCE_PATH"], "/snapshot")
        self.assertTrue(env["PATH"].startswith(str(Path(m1.sys.executable).parent)))
        self.assertNotIn("/wrong", env["PYTHONPATH"])
        self.assertNotIn("LD_PRELOAD", env)


if __name__ == "__main__":
    unittest.main()
