# PTG Fault Injection V2 FORCE Integration Status

**Status date**: 2026-08-25

**PTG baseline**: `1cdf841` (`fix(fault): reject malformed Sv32 sign-extension aliases`)

**Integration status**: PTG V2 native acceptance passed; FORCE ctypes integration and the
core Handcar trap matrix are complete

## 1. Current Status

PTG Fault Injection V2 is now integrated into FORCE-RISCV. The integration no longer relies on
the legacy count-only fault API for the validated trap matrix. FORCE can submit a typed V2
request, perform the required two-call result-buffer protocol, compare dry-run and commit
records, load the committed page tables into Handcar, execute a real faulting instruction, and
assert the resulting trap CSRs.

The completed real-execution matrix covers:

- S-stage direct instruction, load, and store page faults from S and U privilege.
- VS-stage direct instruction, load, and store page faults from VS and VU privilege.
- G-stage direct instruction, load, and store guest-page faults.
- G-stage guest-implicit instruction, load, and store guest-page faults.
- G-stage guest-explicit instruction, load, and store guest-page faults.

The baseline stage/scope Handcar matrix uses `InvalidPTE` (`fault_cause=1`) as its deterministic
PTE mutation. The expanded direct matrix additionally executes causes 2 through 9 from S/U/VS/VU
and G-stage VS contexts. PTG native acceptance covers the wider V2 cause/support table, but causes
10 through 12 have not been promoted to architectural execution tests yet.

## 2. Newly Supported FORCE Features

### 2.1 V2 ctypes ABI

`py/riscv/paging/PtgBackend.py` now exposes:

- `PtgFaultRequestV2` with the verified 112-byte ABI layout.
- `PtgFaultResultV2` with the verified 104-byte ABI layout.
- `PtgVmConfigV2` with the verified 48-byte ABI layout.
- `ptg_fault_request_v2_init` and `ptg_vm_config_v2_init` wrappers.
- `ptg_context_set_vm_config_v2` support.
- `ptg_inject_fault_v2` using the required preflight and result-buffer calls.
- Status, selection-mode, scope, address-kind, stage, access, privilege, verification, flag,
  VM-target, and result-validity constants.

The wrapper supports the V2 request dimensions defined by PTG:

| Dimension | Exposed values |
|---|---|
| Selection | disabled, exact-one, exact-count, probability |
| Stage | S, VS, G |
| Scope | direct, guest-implicit, guest-explicit |
| Address kind | stage-native, GVA, GPA |
| Access | execute, read, write |
| Privilege | S, U, VS, VU |
| Verification | mutation-only, require-fault |
| VM configuration | shared S/VS target or G target; PBMTE, ADUE, SUM, MXR, SSE, Svnapot |

### 2.2 Exact result records

FORCE now consumes and validates the V2 result record instead of accepting only an injected
count. The validated fields include:

- Requested and resolved address.
- Requested and resolved page-table level.
- Fault scope and stage.
- Requested and actual diagnostic cause.
- Expected and actual architectural `mcause`.
- Failing GPA where applicable.
- Mutated PTE physical address.
- Old and new PTE values.

Exact-one tests require one result, reject metadata mismatches, and verify that the committed PTE
appears in the exported page-table image.

### 2.3 Dry-run and transaction checks

The FORCE tests now prove that:

- Result-buffer preflight does not mutate page tables.
- A dry-run returns the same record as the later commit.
- A dry-run leaves all relevant page-table images unchanged.
- A commit changes the expected stage image.
- Guest-scope commits mutate the G-stage tree and preserve the raw VS-stage tree.
- Invalid arguments, unsupported combinations, exact target misses, unsuitable exact targets, and
  insufficient exact-count requests covered by the ctypes tests leave the image unchanged for both
  dry-run and commit requests.

Guest-implicit tests compare raw sparse blocks rather than `get_force_blocks("VS")` after the
mutation. The latter intentionally projects VS page-table GPAs through the current G-stage and
therefore changes its output address when the tested G mapping is invalidated; that projection
change is not a VS-tree mutation.

### 2.4 Wrapper safety checks

The integration adds the following FORCE-side guards:

- Batch `REQUIRE_FAULT` requests require `PTG_FAULT_ONE_PER_WALK` by default.
- Callers must explicitly opt in if they accept PTG V2's per-mutation verification behavior for
  a batch without that flag.
- V2 VM configuration accepts only the public shared `S_VS` target or the `G` target.
- S and VS cannot be configured independently through a synthetic FORCE-only target.
- Synchronous `get_force_blocks()` collection callbacks are no longer retained indefinitely.
- The dedicated runner places the directory of `sys.executable` first in `PATH`, so shebang-based
  `forrest_run.py` children use the same Python ABI as the parent process.

## 3. Real Handcar Trap Matrix

All cells below execute a real instruction and assert trap state rather than relying only on PTG
software translation.

| PTG stage/scope | Execute | Read | Write | Status |
|---|---:|---:|---:|---|
| S direct | 12 | 13 | 15 | PASS |
| VS direct | 12 | 13 | 15 | PASS |
| G direct | 20 | 21 | 23 | PASS |
| G guest-implicit | 20 | 21 | 23 | PASS |
| G guest-explicit | 20 | 21 | 23 | PASS |

The tests assert `mcause`, `mepc`, `mtval`, `mtval2`, `mtinst`, and `mstatus`.

### Sv39 cause, privilege, access, and level matrix

The direct matrix now executes causes 2 through 9 from S-stage S/U, VS-stage VS/VU, and G-stage VS
contexts for execute, read, and write at every valid Sv39 target level. It checks the exact
access-specific old/new PTE value, proves that `pte_pa` identifies the changed raw S/VS/G slot,
proves that no bytes outside that 8-byte PTE changed, and then asserts the real Handcar
instruction/load/store page fault. VS-stage injections preserve the raw G-stage tree, and G-stage
injections preserve the raw VS-stage tree. The VS/VU paths keep their G-stage mappings valid and
explicitly clear guest `vsstatus.SUM/MXR` to match the PTG VM oracle. VU enters through a real
MRET-to-VS and SRET-to-VU trampoline before executing the faulting access.

| Requested cause | Sv39 levels | Mutation/priority condition | PTG verification | S/VS `mcause` | G `mcause` |
|---:|---|---|---|---|---|
| 2 ReservedIllegal | L0, L1, L2 | highest available Sv39 reserved bit is set | mutation-only | 12/13/15 | 20/21/23 |
| 3 ADZero | L0, L1, L2 | A is cleared for execute/read; D for write; PTG ADUE disabled | require-fault | 12/13/15 | 20/21/23 |
| 4 MisalignedSuperpage | L1, L2 | PPN bit 0 is set in an aligned leaf | require-fault | 12/13/15 | 20/21/23 |
| 5 PermUMismatch | L0, L1, L2 | U is set for S/VS; U is cleared for U/VU/G-stage | require-fault | 12/13/15 | 20/21/23 |
| 6 PermRWXViolation | L0, L1, L2 | execute clears X, read clears R/W, write clears W | require-fault | 12/13/15 | 20/21/23 |
| 7 NonLeafTerminal | L1, L2 | pointer gains R and becomes a terminal leaf | require-fault | 12/13/15 | 20/21/23 |
| 8 LeafNotTerminal | L0, L1, L2 | RWX are cleared; L0 becomes a deepest non-leaf, upper levels retain illegal A/D/U | require-fault | 12/13/15 | 20/21/23 |
| 9 NonLeafAtLevelZero | L0 | RWX are cleared; A/D/N/PBMT remain clear and U is retained only for U-mode | require-fault | 12/13/15 | 20/21/23 |

Handcar exposes the architectural page-fault class, not PTG's internal diagnostic cause. The
current Handcar and current upstream Spike can order internal checks differently while producing
the same architectural `mcause`. For structural causes, the committed PTE and independently
checked preconditions establish which malformed form was executed. Cause 2 intentionally remains
mutation-only in the PTG manifest; the subsequent Handcar instruction independently proves that
the mutation traps. For a G-stage cause 7 request, PTG reports actual diagnostic cause 5 because
the injected terminal leaf also violates the mandatory G-stage U-bit rule; the exact committed PTE
and the architectural guest-page-fault result are asserted independently.

| Trap path | `mtval` | `mtval2` | `mtinst` | Relevant `mstatus` |
|---|---|---|---|---|
| S direct | faulting VA | 0 | 0 | `MPP=S`, `MPV=0`, `GVA=0` |
| U direct | faulting VA | 0 | 0 | `MPP=U`, `MPV=0`, `GVA=0` |
| VS direct | faulting GVA | 0 | 0 | `MPP=S`, `MPV=1`, `GVA=1` |
| VU direct | faulting GVA | 0 | 0 | `MPP=U`, `MPV=1`, `GVA=1` |
| G direct | faulting GVA | failing GPA >> 2 | 0 | `MPP=S`, `MPV=1`, `GVA=1` |
| G guest-explicit | faulting GVA | final data GPA >> 2 | 0 | `MPP=S`, `MPV=1`, `GVA=1` |
| G guest-implicit | faulting GVA | exact VS PTE GPA >> 2 | `0x3000` | `MPP=S`, `MPV=1`, `GVA=1` |

For RV64 Sv39, `mtinst=0x3000` is the Handcar/Spike pseudoinstruction value observed for the
implicit 8-byte VS page-table access. It must not be treated as the trapped guest instruction.

### Guest-implicit VS/G level matrix

The guest-implicit matrix isolates the VS root, intermediate, and leaf page-table nodes in GPA
regions separated by 1 GiB. This prevents a G-stage L1/L2 mutation selected for a later VS PTE
fetch from also invalidating an earlier VS walk step. The template independently walks the raw VS
and G images and requires `failing_gpa` and `pte_pa` to identify the exact requested levels.

| VS walk level | G target levels | Execute | Load | Store |
|---:|---|---:|---:|---:|
| L0 | L0, L1, L2 | PASS | PASS | PASS |
| L1 | L0, L1, L2 | PASS | PASS | PASS |
| L2 | L0, L1, L2 | PASS | shadowed | shadowed |

At VS root level, a normal guest load/store cannot reach its data translation after the injected G
mapping is invalidated: fetching the load/store instruction first reads a PTE from the same 4 KiB
VS root page and therefore takes instruction guest-page-fault `mcause=20`. The matrix records this
architectural priority boundary and executes the L2 crosses with instruction access only.

### Guest-explicit GVA/GPA parity

Guest-explicit execute, load, and store each run at G target levels 0, 1, and 2 as both a
GVA-selected and GPA-selected commit. For every target, both request forms first run as dry-runs on
the same clean trees. Their complete result records must match except for `requested_address`: the
GVA request retains the original GVA, while the GPA request retains the equivalent final data GPA.
Both must resolve to the same GPA and exact G-stage `pte_pa`, produce identical old/new PTE values
and `mcause`, preserve both trees during dry-run, and modify only the selected 8-byte G PTE during
commit. Level 2 places the three fault GPAs, normal instruction-fetch mappings, and VS page-table GPA
region in distinct G root entries so final-data faults are not shadowed by earlier VS walks or
instruction fetches. The subsequent guest instruction has identical architectural trap CSR
expectations for both request forms.

### Test files

- `tests/riscv/ptg_fault_v2_ctypes_test.py`
- `tests/riscv/ptg_fault_v2_s_stage_trap_force.py`
- `tests/riscv/ptg_vs_fault_matrix_force.py`
- `tests/riscv/ptg_fault_v2_instruction_trap_force.py`
- `tests/riscv/ptg_fault_v2_guest_scope_common.py`
- `tests/riscv/ptg_fault_v2_guest_scope_trap_force.py`
- `tests/riscv/ptg_fault_v2_guest_explicit_trap_force.py`
- `tests/riscv/ptg_fault_v2_sv39_cause_levels_force.py`
- `tests/riscv/ptg_fault_v2_fctrl.py`
- `utils/regression/run_ptg_fault_v2.py`

Guest-implicit and guest-explicit use separate FORCE templates because consecutive independent
linear blocks in one template can retain the previous block's replay state. Splitting the scopes
keeps each CSR result set isolated and deterministic.

## 4. Verification Evidence

### PTG native acceptance

- Independent reproduction:
  `REPRO cause=0 precedence=0 noncanonical=0 callback=0 sv32=0 sv32_bad_sign=0`.
- `make fault_acceptance`: 15/15 sections pass; manifest contains 1263 cells.
- `make verify`: 2479 pass, 0 fail; NodeRegistry 39 pass, 0 fail.
- ctypes ABI validation: PASS.
- V2 usage example: PASS.
- `make stress`: 1026 pass, 2 fail. Both failures are pre-existing frozen stress failures:
  `at least 90% two-stage translations OK` and `Sv32x4 walk`.

### FORCE integration

- V2 ctypes tests: 8/8 PASS, including negative status and no-mutation coverage for
  `INVALID_ARGUMENT`, `UNSUPPORTED_COMBINATION`, `TARGET_NOT_FOUND`, `UNSUITABLE_TARGET`, and
  `INSUFFICIENT_CANDIDATES`.
- S direct trap matrix: PASS.
- VS/G direct data trap matrix: PASS.
- VS/G direct instruction trap matrix: PASS.
- Guest-implicit trap matrix: PASS.
- Guest-explicit trap matrix: PASS.
- Dedicated regression seed set `0x15c0ffee`, `0x5eed1234`, and `0xc001d00d`: 990/990
  generation and 990/990 ISS simulation PASS; every per-seed summary reports 330 tasks and
  `Task Fails: 0`.
- Direct `sim.log` audits of all 900 S/U/VS/VU/G-stage cause/access/level tasks: 900/900 PASS (300
  execute, 300 load, 300 store). Each log contains the real faulting access, the expected
  access-specific `mcause` (`12/13/15` for S/VS or `20/21/23` for G), exact `mepc` and `mtval`,
  zero `mtinst`, the expected S/U/VS/VU/G-stage `MPP/MPV/GVA` state, and a successful Handcar exit.
  S/VS logs have zero `mtval2`; G-stage logs have the exact failing `GPA >> 2` value
  `0x80000000`. VU logs additionally execute the observable `sepc` setup and `sstatus.SPP` clear in
  the VS trampoline.
- Direct `sim.log` audits of all 63 guest-implicit level/access tasks: 63/63 PASS (27 execute, 18
  load, 18 store). Each log contains the expected `mcause=20/21/23`, exact `mepc`, faulting GVA in
  `mtval`, selected VS PTE GPA shifted into `mtval2`, `mtinst=0x3000`, M-mode trap state, and a
  successful Handcar exit.
- Direct audits of all 18 guest-explicit GVA/GPA/level `sim.log` files: 54/54
  access/address-kind/level scenarios PASS. Paired GVA/GPA records resolve to identical
  GPA/PTE/mutation data; both commit forms produce `mcause=20/21/23`, faulting GVA in `mtval`, final
  data `GPA >> 2` in `mtval2`, zero `mtinst`, the expected M-mode trap state, and a successful
  Handcar exit.
- `ruff format --check`, `ruff check`, `py_compile`, and `git diff --check`: PASS.
- The C++ unit runner now returns nonzero when any child fails. A controlled failing Makefile exits
  1, while the real suite passes 42/42 and exits 0.
- A direct `/usr/bin/python3.12` invocation of the Fault V2 runner, without an external `PATH`
  override, passes the ABI preflight and one complete 330-task generation/ISS seed.

The productized entry point runs the ctypes suite first as an ABI preflight, then runs nine baseline
FORCE tasks, 21 isolated guest-implicit level/access tasks, and 300 isolated
S/U/VS/VU/G-stage cause/access/level tasks. It validates generation count, ISS count, and failures
in `regression_summary.log` because `master_run.py` does not reliably return nonzero when a child
task fails:

```bash
make -j
make tests
source setenv.bash
python3 utils/regression/run_ptg_fault_v2.py \
    --ptg-lib /path/to/libptg.so \
    --artifact-root /path/to/artifacts
```

The default seed set is `0x15c0ffee`, `0x5eed1234`, and `0xc001d00d`. One or more explicit seeds
can replace it by repeating `--seed`, for example `--seed 0x1 --seed 0x2`.

The artifact root contains `ctypes.log` and one `seed_<hex>` directory per seed. Each seed directory
contains `master_run.log`, its regression summary, and an isolated task directory for each
template. With `-k all`, each task retains its ELF, assembly, generation log, Handcar `sim.log`,
FPIX log, and `forrest.log`.

## 5. Current Boundaries

The completed core matrix does not mean every PTG V2 combination has real Handcar coverage.
Current boundaries are:

- Causes 2 through 9 now have real S-stage S/U, VS-stage VS/VU, and G-stage VS
  execute/read/write coverage at every valid Sv39 target level.
- Cause 3 is verified against the current Handcar Svade behavior. PTG ADUE is disabled for target
  selection, but a future Svadu-capable ISS still needs explicit `menvcfg.ADUE` control/readback and
  an ADUE-enabled update-success counterpart.
- Cause 10 requires a real guest-implicit A/D writeback. The current Handcar build does not enable
  hardware A/D updates, so this path cannot yet be represented faithfully.
- Causes 11 and 12 remain mutation-only at PTG level and require real Svnapot and SSE support,
  respectively, before they can be promoted to architectural execution tests.
- Guest-implicit real execution covers every VS walk/G target level pair. VS L0/L1 cover all three
  accesses; VS L2 uses execute because normal guest load/store is architecturally shadowed by the
  earlier instruction fetch through the same VS root page.
- Guest-explicit GVA and GPA exact requests have paired dry-run parity, commit, and Handcar trap
  coverage for execute, load, and store at every Sv39x4 G target level.
- Exact-count and probability selection have wrapper/native coverage but no real trap replay
  suite.
- SUM/MXR/PBMTE/SSE/Svnapot interaction matrices still need real execution coverage; direct U/VU
  fault execution is now covered with SUM and MXR disabled.
- The current matrix forces traps to M-mode. HS/VS delegation, `stval/htval/htinst`, nested trap
  handling, and xRET return chains remain separate work.
- RV32/Sv32 and Sv32x4 need FORCE/Handcar trap coverage. The accepted Sv32 normalization fix is
  currently proven at PTG native level.
- `MPTDenied` remains a separate MPT path and is intentionally not exposed as a PTE V2 mutation.
- V2 batch `REQUIRE_FAULT` verification is per mutation unless one-per-walk semantics are used.
- Exact-count insufficiency is verified as an atomic no-mutation failure through the public C API.
  Forced semantic mismatch and apply-failure callback rollback remain PTG-native tests because the
  public C API exposes no fault-oracle or apply-failure test hook.
- Public V2 VM controls intentionally share one S/VS configuration target.
- The repository has no project CI configuration to update. The dedicated runner is ready for an
  external CI job, but that job has not yet been wired to this repository.

## 6. Next Improvements

### P0: Productize the completed matrix

Completed:

1. Added the five real-execution templates to `ptg_fault_v2_fctrl.py`.
2. Added a single runner that executes the ctypes ABI preflight before FORCE generation and
   converts summary task failures into a nonzero process exit.
3. Preserved complete, isolated task artifacts and validated the documented three-seed set end to
   end: 990 generation tasks and 990 ISS simulations pass.
4. Pinned shebang-based regression children to the runner's Python interpreter directory and
   revalidated one complete 330-task seed without an external `PATH` override.

Remaining:

1. Wire the runner into the external CI system and publish its artifact root on failure.

### P0: Expand real mutation semantics

Completed:

1. Promoted causes 2 through 9 to real S-stage S/U, VS-stage VS/VU, and G-stage VS
   execute/read/write tests with exact PTE mutation and trap CSR assertions.
2. Covered every valid Sv39 target level for those causes, including root, intermediate, 4 KiB,
   2 MiB, and 1 GiB leaf cases.
3. Added public ctypes negative tests for unsupported combinations, exact target misses, unsuitable
   targets, and insufficient candidates, with dry-run/commit image-preservation assertions.
4. Covered every guest-implicit VS walk/G target level pair with isolated VS-node GPA placement and
   real Handcar trap CSR assertions for every architecturally reachable access.
5. Added paired guest-explicit GVA/GPA dry-run parity, independent commits, and real trap coverage
   for execute, load, and store at every Sv39x4 G target level.

Remaining:

1. Add cause 10 after Handcar can perform and expose guest A/D writeback semantics.
2. Add causes 11 and 12 after Svnapot and SSE execution support is available.
3. Add FORCE-side semantic-mismatch and apply-failure callback rollback tests after PTG exposes
   controlled public test hooks.

### P1: Expand architectural context

1. Extend the S/U and VS/VU permission matrices with SUM, MXR, and G-stage U-bit rules.
2. Add ADUE read/write behavior and `GuestADUpdateFault` real execution.
3. Add PBMTE, SSE, and Svnapot enabled/disabled tests where PTG reports support.
4. Verify delegated traps in HS and VS handlers, including `scause`, `stval`, `htval`, `htinst`,
   and the MRET/SRET return chain.
5. Add nested VS/G faults only after each individual trap path remains independently stable.

### P1: Expand modes and operation types

1. Add RV32 Sv32/Sv32x4 real trap tests, including accepted zero/sign extension boundaries and
   malformed-address rejection.
2. Extend mode coverage to Sv48/Sv48x4 and Sv57/Sv57x4.
3. Add exact-count and probability seed replay with complete result-record comparison.
4. Add AMO/store fault instructions in addition to the current scalar store representative.

### P2: Complete adjacent fault infrastructure

1. Build a separate MPT denial matrix instead of routing `MPTDenied` through the PTE injector.
2. Add VMID, ASID, HFENCE, and HINVAL interactions after a committed fault mutation.
3. Add multi-Hart isolation and concurrent PTG context tests.
4. Resolve or formally rebaseline the two frozen PTG stress failures before release closure.

## 7. Definition of Complete

Fault Injection V2 integration can be considered release-complete when:

- Every supported native cause cell selected for FORCE has a real instruction and CSR assertion.
- Every unsupported cell returns the documented status without mutation.
- Level, privilege, VM-control, guest-scope, and address-kind crosses are represented.
- Exact-count and probability modes have deterministic seed replay evidence.
- M-mode and delegated HS/VS trap paths are both verified where architecturally applicable.
- RV64 and RV32 target modes pass dedicated regression jobs.
- The suite is part of normal CI and no longer depends on manual log inspection.
