# PTG Fault Injection V2 Acceptance Feedback

**Review date**: 2026-08-13

**Reviewed PTG commit**: `8bb6c3536fc81765dc57a7f168ba9422f9f8bff9`

**Decision**: Not accepted for FORCE real-trap matrix expansion

## 1. Summary

The V2 work is a substantial improvement. The public ABI, exact-address/level request shape,
two-call result buffer, no-fallback policy, guest scopes, synchronized PTE writes, transaction
framework, documentation, and native test organization are all useful and mostly behave as
documented.

The published test commands reproduce successfully:

```text
make fault_acceptance:
  F:10/10 PASS; causes:13/13 PASS; A:15/15 PASS; fallback:0
  FAULT_ACCEPTANCE: 15/15 PASS; manifest:1263 cells

make verify:
  2467 passed, 0 failed
  NodeRegistry: 39 passed, 0 failed

make shared && python3 tests/fault/test_ctypes_abi.py:
  ctypes ABI: PASS

make example_fault_v2:
  SUMMARY PASS
```

However, independent review and reproduction found four semantic defects that invalidate several
of the reported F/A passes. The central issue is that the acceptance oracle and the implementation
share assumptions that do not match the actual post-mutation walk or Spike walk ordering.

FORCE should not yet treat `actual_cause`, implicit-fault priority, exact address resolution, or
dry-run external side effects as trustworthy. The existing four direct level-zero InvalidPTE
Handcar cases remain usable, but full cause/level/guest expansion should wait for the fixes below.

## 2. Independent Reproduction

The independent source used for this review is stored in the FORCE evidence directory and is not
part of the PTG implementation or acceptance suite:

```text
tests/riscv/ptg_fault_v2_legacy_repro.cpp
```

Build and run against the reviewed static library:

```bash
FORCE_ROOT=/absolute/path/to/force-riscv
g++ -std=c++17 -Wall -Wextra -I include -I . \
    "$FORCE_ROOT/tests/riscv/ptg_fault_v2_legacy_repro.cpp" \
    build/libptg.a \
    -o /tmp/opencode/ptg_v2_independent_repro
/tmp/opencode/ptg_v2_independent_repro
```

Observed output:

```text
ACTUAL_CAUSE status=0 reported=7 observed=4 fault=2
PRECEDENCE fault=2 cause=1 scope=0 failing=0x1000 root_pte_gpa=0x20000000
NONCANONICAL status=0 canonical_pte=0x10002008 aliased_pte=0x10002008
DRY_CALLBACK status=0 callbacks=2
REPRO cause=1 precedence=1 noncanonical=1 callback=1
```

Each final value of 1 means the defect was reproduced.

## 3. Blocking Findings

### V2-01 P0: `actual_cause` reports the requested mutation category, not the observed walk cause

Evidence:

- `src/fault/fault_oracle.cpp:220` sets the result cause from the mutation proposal.
- `src/fault/fault_oracle.cpp:246-257` special-cases causes 7 and 8 and constructs the oracle
  observation with `input.request.cause`, rather than `observed.fault_cause`.
- `tests/fault/test_full_matrix.cpp:132` asserts `actual_cause == requested cause`, reproducing the
  same assumption instead of independently checking the post-mutation walk cause.

Independent reproduction requests cause 7 (`NonLeafTerminal`) on the Sv39 root pointer. The
mutation is accepted and V2 returns:

```text
status=OK, actual_cause=NonLeafTerminal(7)
```

The actual post-mutation PTG walk reports:

```text
fault=LoadPageFault, fault_cause=MisalignedSuperpage(4)
```

This is expected from the mutation: setting R on an intermediate pointer creates a leaf using a
PPN that is not necessarily aligned for that superpage level. Spike likewise evaluates the
resulting PTE and raises the failure produced by that PTE; it does not expose a
`NonLeafTerminal` architectural cause.

This means the following fields currently have different meanings despite their names:

- `requested_cause`: requested mutation category
- `actual_cause`: currently another copy of the mutation category, not actual observed cause

Required fix:

- Populate observed cause from `WalkResult::fault_cause` for semantic verification.
- Do not exempt causes 7 and 8 from diagnostic/cause/level/PTE-location validation.
- If both concepts are required, expose separate `mutation_cause` and `observed_fault_cause`
  fields. Do not label the mutation category as `actual_cause`.
- `SEMANTIC_MISMATCH` must return the real observed diagnostic where available.

Required regression:

- Cause 7 at an intermediate pointer that becomes a misaligned leaf.
- Cause 8 at levels where clearing RWX produces reserved-illegal, L0 nonleaf, or another actual
  diagnosis.
- Assert the observed cause from the walker; never derive it from the request.

Affected prior requirements: F-04, F-06, F-08, F-10, A09.

### V2-02 P0: Two-stage detailed translation does not preserve Spike's interleaved walk order

Evidence: `src/core/context.cpp:83-117`.

`translate_detailed()` currently:

1. Completes the entire VS walk with `vs_stage_->walk_with_config()`.
2. Returns any VS fault immediately.
3. Only after a successful VS walk, iterates the VS path and checks G-stage translation of each
   VS PTE GPA.

Spike performs the G-stage translation of each VS PTE address before reading that VS PTE. See the
checked-in reference flow in `handcar/patcher/originals/mmu.cc:359-370`. Therefore an implicit
G-stage fault while fetching an earlier VS PTE has priority over a fault in a later VS PTE that
could never have been read.

Independent reproduction creates both:

- An invalid G-stage mapping for the VS root PTE GPA.
- An invalid VS leaf PTE.

PTG reports the later VS leaf failure:

```text
fault=LoadPageFault(13), cause=InvalidPTE, direct scope, failing GVA=0x1000
```

Spike ordering requires the earlier implicit G-stage failure:

```text
LoadGuestPageFault(21), implicit scope, failing GPA=VS root PTE GPA
```

Required fix:

- Implement one interleaved two-stage walker.
- At each VS level, translate the exact VS PTE GPA through G-stage before reading/evaluating the
  VS PTE.
- Perform any required G-stage write translation before VS A/D update.
- Preserve original guest access for mcause 20/21/23 while using physical read/write as the
  internal G-stage PTE access.
- Make `translate()`, `translate_sequential()`, and semantic verification use the same walker.

Required regression:

- For each VS level, combine an earlier implicit G-stage PTE-fetch failure with a later VS PTE
  failure and assert the implicit guest fault wins.
- Check exact failing GPA, G-stage level, G PTE PA, and original-access mcause for execute/read/write.

Affected prior requirements: F-06, A08.

### V2-03 P0: Non-canonical native addresses and out-of-range x4 GPAs can alias valid PTEs

Evidence:

- `src/core/page_table_tree.cpp:483-516`
- `src/core/page_table_tree.cpp:519-649`

`resolve_pte_on_walk()` and the page-table walk extract VPN fields without first validating the
address against the selected translation mode. For Sv39, a value with bit 39 set and otherwise the
same low VPN fields aliases the valid low address.

Independent reproduction shows:

```text
non-canonical address: (1 << 39) | 0x1000
canonical PTE PA:     0x10002008
resolved PTE PA:      0x10002008
status:               Found
```

Spike rejects non-canonical S/VS virtual addresses before the walk. G-stage input is also limited
by the applicable x4 GPA width and must not alias through truncated VPN extraction.

Required fix:

- Add mode-specific canonical VA validation for Sv32/Sv39/Sv48/Sv57 native walks.
- Add mode-specific GPA width validation for Sv32x4/Sv39x4/Sv48x4/Sv57x4.
- Apply the same validation in resolver, normal walk, detailed walk, guest GVA/GPA resolution,
  and V2 exact/count/probability target enumeration.
- Invalid addresses must not resolve or mutate an aliased PTE.

Required regression:

- Positive and negative canonical boundaries for each native mode.
- Highest valid and first invalid GPA for each x4 mode.
- Exact-one, exact-count optional target, probability optional target, and normal translation all
  reject invalid addresses without mutation.

Affected prior requirements: F-01, A03, A15.

### V2-04 P1: Dry-run and failed semantic preflight emit externally visible PTE write callbacks

Evidence:

- `src/fault/fault_engine.cpp:54-63`
- `src/fault/fault_engine.cpp:186-190`
- `src/core/page_table_tree.cpp:965-971`
- `src/memory/memory_model.cpp:54-65`

Dry-run semantic verification applies the proposed PTE through `write_pte_synced()` and then rolls
it back. The final bytes are restored, but an external `MemoryModel::on_pte_write()` observer sees
both writes.

Independent reproduction registers a callback after initial synchronization and performs one
exact InvalidPTE dry-run:

```text
status=OK, callbacks=2
```

The same issue affects semantic preflight for real execution and batches: observers can see
proposal, rollback, and final commit writes. Callback side effects cannot be rolled back.

The current A13 test verifies final node/model/export values, but its output callback is
`BinaryOutput::serialize_write()`, not the mutation callback registered through
`MemoryModel::on_pte_write()`. It therefore does not detect this issue.

Required fix:

- Verify proposals against a shadow state or a non-publishing transaction view.
- Publish synchronized writes and external callbacks only during final commit.
- Dry-run, preflight, semantic mismatch, and rollback must emit zero externally visible mutation
  callbacks.
- Successful exact-one should emit one committed PTE callback; exact-count should emit one per
  committed PTE with no preflight duplicates.

Required regression:

- Register `MemoryModel::on_pte_write()` after setup.
- Assert callback counts and values for dry-run, semantic mismatch, apply failure, exact-one
  success, exact-count success, and rollback.

Affected prior requirements: F-07, A05, A13, A14.

## 4. Additional High-Risk Gaps

These items were found by code review but are not part of the four-value independent reproduction
above. They should be addressed or explicitly constrained before release.

### V2-05 P1: Require-fault batches are verified one mutation at a time, not in final combined state

Evidence: `src/fault/fault_engine.cpp:169-205`.

Each batch candidate is temporarily applied and verified alone, then rolled back. After all
candidates individually pass, all proposals are committed together without re-verifying the final
combined page table. Multiple selected PTEs from the same address walk can therefore each claim a
successful observed level/PTE even though an upper-level final mutation masks every lower-level
mutation.

Required resolution:

- Make one-per-walk mandatory for `REQUIRE_FAULT`, or
- Define batch results as mutation records rather than simultaneously observable fault records,
  or
- Verify and report the final combined-state observability without making contradictory per-record
  claims.

Add an exact-count regression that selects multiple levels from one walk without
`PTG_FAULT_ONE_PER_WALK`.

### V2-06 P1: Public VM configuration combines S and VS controls

Evidence:

- `include/ptg/ptg_fault_v2.h:72-75`
- `src/fault/fault_oracle.cpp:147-154`

The public setter has `PTG_VM_CONFIG_S_VS` and `PTG_VM_CONFIG_G`, so S and VS share one
`VMConfig`. Real HS/S and VS/VU operation can have different effective SUM/MXR/A/D-update controls.

Please either:

- Expose separate S, VS, and G control snapshots, or
- Document that one `AddressContext` cannot model simultaneous differing S and VS controls and
  remove claims that such combinations are covered.

## 5. Quality Finding

`git diff 407dfec..8bb6c35 --check` reports:

```text
tests/fault/test_exact_engine.cpp:121: trailing whitespace.
```

This is non-blocking but should be cleaned before the next handoff.

## 6. Revised Acceptance Criteria

Please provide a follow-up commit satisfying all of the following:

1. `actual_cause` is derived from the observed walk, or the API clearly separates mutation and
   observed causes.
2. The two-stage walker follows Spike's per-level interleaving and implicit fault priority.
3. Native canonical and x4 GPA-width checks prevent address alias mutation.
4. Dry-run and all non-commit paths emit no external PTE write callbacks.
5. Require-fault batch observability has an explicit, tested contract.
6. S/VS control modeling is separated or its limitation is documented and removed from coverage
   claims.
7. The independent reproduction above no longer reports all four defects.
8. `make fault_acceptance`, `make verify`, ctypes ABI, and the V2 example still pass.
9. New regressions do not derive expected observed cause or priority from the request under test.
10. `git diff --check` passes for the follow-up range.

After these criteria pass, FORCE will mirror the V2 ABI in `PtgBackend.py` and start the real
instruction/CSR matrix for mcause 12/13/15/20/21/23.
