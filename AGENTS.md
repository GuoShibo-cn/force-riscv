# AGENTS.md — FORCE-RISCV

## 语言偏好

- **Thinking 过程**：使用中文
- **与用户交流**：使用中文
- **代码注释**：英文（除非用户特别要求）
- **提交信息**：英文（除非用户特别要求）

## What this is

RISC-V instruction sequence generator (ISG) for processor design verification. C++ core with Python test templates. Generates randomized `.ELF`/`.S` test files, simulates via Handcar (Spike-based ISS).

## Build & test commands

## Hypervisor Session Entry

**User-confirmed architecture: PTG-first Hypervisor integration.** Use and extend
PTG as the Hypervisor page-table generation backend. FORCE owns the adapter,
generator constraints/context, memory synchronization and CSR/fence instruction
generation; Handcar is the execution oracle. Do not develop a competing native
Hypervisor page-table generator or silently fall back to one when PTG is missing
a capability. Preserve earlier native Mapper changes as historical work, not the
new implementation roadmap.
First check existing PTG APIs before proposing extensions. Record every PTG
requirement or suspected bug under `docs/`, distinguishing confirmed PTG bugs,
API requirements, FORCE adapter bugs and unverified hypotheses. Include the
version/library hash, minimal reproducer, expected/actual behavior, impact and
acceptance criteria. The user submits these documents to PTG maintainers; do not
modify/publish the external PTG repository or file remote issues without explicit
authorization. Track requests in `docs/PTG_FORCE_INTEGRATION_REQUIREMENTS.md`.

For Hypervisor/Handcar work, first read `docs/HYPERVISOR_QUICKSTART.md`, then
`docs/HYPERVISOR_WORKFLOW_GUIDE.md` and `docs/HANDCAR_DEPENDENCY_GUIDE.md`.
The current migration evidence is in `docs/HANDCAR_UPSTREAM_REBASE_STATUS.md`.
For a fresh checkout, use `docs/HYPERVISOR_BUILD_FROM_SOURCE.md`; historical
`output/` binaries/configs are acceptance evidence, not checkout dependencies.
The PTG source baseline is now published as
`addd85d973dd5bac9d0e0580e0ade7c32888b48c`; record its build hash separately.
The independent development repository is `handcar/dev-spike/`: keep `master`
tracking `upstream/master`, and put local commits on `handcar/force-integration`.
Read `docs/HANDCAR_BRANCH_WORKFLOW.md` before updating/rebasing it. Do not confuse
its branches with FORCE's branches; no fork publishing remote is configured yet.
Use `handcar/upstream.lock.json` plus its pinned patch and
`handcar/tools/upstream.py` for the new upstream build. The ignored
`handcar/standalone-v2` tree is a historical local input, not pristine upstream.
Never install/replace the existing dirty Handcar libraries without explicit
authorization. Always pass candidate `--handcar-so` and `--ptg-lib` to acceptance.
New upstream profiles explicitly enable Zicclsm; use
`config/riscv_rv64_handcar.config` or `config/riscv_rv64_twostage_handcar.config`.
The supported candidate contract is single hart 0; non-default RAM must be
declared/initialized by the host before architectural access.
**Do not run root `make tests` during these workflows: it deletes `output/`,
including isolated sources, builds and acceptance evidence.** Use the documented
targeted seedgen build or unit runner instead. Do not clean unrelated changes.

## General Build Commands

```bash
# One-shot: env check + build + regression + unit tests (interactive)
./setup

# Manual steps (preferred in CI/agent context):
source setenv.bash          # sets PYTHONPATH — required before any Python tool
make -j                     # builds bin/friscv + fpix + handcar .so
make tests                  # deletes output/ and runs test-generation/seedgen targets

# Run a single test template directly:
bin/friscv -t utils/smoke/test_force.py
bin/friscv -t <path>/<name>_force.py --cfg config/riscv_rv64.config

# Full regression (from repo root):
./utils/regression/master_run.py -f examples/riscv/_def_fctrl.py -c utils/regression/config/_riscv_rv64_fcfg.py -k all

# C++ unit tests (parallel, from repo root):
./utils/regression/unit_tests.py

# Regenerate enum classes (after arch_data XML changes):
make enums
```

## Environment variables

`setenv.bash` must be sourced before running any Python tool. It adds `3rd_party/py`, `utils`, `utils/builder`, `utils/builder/test_builder`, `utils/builder/shared`, `utils/regression` to `PYTHONPATH`.

Build requires: g++ ≥ 5.1, Python ≥ 3.6.1. Override auto-detection with `FORCE_CC`, `FORCE_PYTHON_VER`, `FORCE_PYTHON_INC`, `FORCE_PYTHON_LIB`.

## Architecture layout

| Directory | Purpose |
|-----------|---------|
| `riscv/` | RISC-V arch C++ (inc/src/arch_data — XML instruction, register, paging, choices data) |
| `base/` | Arch-independent C++ framework |
| `py/base/` | Python base framework (`Sequence`, `GenThread`, `Env`, `ChoicesModifier`) |
| `py/riscv/` | Python RISC-V layer (`EnvRISCV`, `GenThreadRISCV`, memory models, paging) |
| `py/DV/riscv/trees/` | Instruction trees (defines ISA instruction strings) |
| `py/DV/riscv/sequences/` | Reusable generation sequences |
| `handcar/` | Handcar ISS source (Spike fork + patches). Rebuild: `handcar/regenerate_and_build.bash` |
| `utils/handcar/` | Handcar C++ wrapper → `handcar_cosim.so` (pre-built `.so` checked in) |
| `fpix/` | Post-generation instruction executor → `fpix_riscv` |
| `bin/` | Build outputs: `friscv`, `SimApiHANDCAR.so`, `handcar_cosim.so` |
| `config/` | XML arch configs: `riscv_rv64.config` (default), `riscv_rv32.config`, `riscv_rv64_sv39.config`, `riscv_rv64_twostage.config`, `riscv-cva6.config` |
| `tests/riscv/` | Regression test templates organized by feature (paging, vector, branch, etc.) |
| `examples/riscv/` | Example test templates |
| `unit_tests/` | C++ unit tests (base/, riscv/, fpix/) |
| `utils/regression/` | Regression framework (`master_run.py`, `unit_tests.py`, config/) |
| `utils/builder/` | Instruction/register/test builders |
| `3rd_party/` | pybind11, softfloat |

## File naming conventions

- `*_force.py` — Test templates (user-facing, invoke FORCE APIs)
- `*_fctrl.py` — Control files for `master_run.py` (list templates + options)
- `*_fcfg.py` — Configuration files for `master_run.py` (define app paths/modes)
- Output: `<template_name>.Default.ELF` and `<template_name>.Default.S`

## Test template structure

```python
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence

class MainSequence(Sequence):
    def generate(self, **kargs):
        self.genInstruction("ADD##RISCV")

MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
```

Instruction names are defined in `py/DV/riscv/trees/instruction_tree.py`. Use format `"MNEMONIC##RISCV"`.

## RV32 vs RV64

Default is RV64. For RV32:
- Direct: `bin/friscv -t <template> --cfg config/riscv_rv32.config`
- Regression: add `-c utils/regression/config/_riscv_rv32_fcfg.py`

## Python formatting

- **Black** (line-length=99, target py36+) — enforced via pre-commit
- **pycodestyle** — ignores E203, E402, W503; max-line-length=99
- Install hook: `pip install pre-commit && pre-commit install`

## Key gotchas

- `handcar_cosim.so` is pre-built in `utils/handcar/` and `bin/`. Rebuilding from source is complex (clones Spike, applies patches, builds). Avoid unless modifying Handcar itself.
- `make` builds `riscv/` then `fpix/`; the `riscv/` Makefile also triggers `utils/handcar/` build.
- `make tests` builds C++ unit test binaries only; Python regression is separate via `master_run.py`.
- `setenv.bash` must be sourced (not executed) for the env to persist: `source setenv.bash`. Running it creates a subshell.
- Config XML files reference paths relative to repo root (e.g., `riscv/arch_data/instr/g_instructions.xml`).
- The `--cfg` flag to `friscv` is required — it points to the arch config XML.
