# PTG Fault Injection V2 Second Acceptance Feedback

**Review date**: 2026-08-13

**Reviewed PTG commit**: `5a2b5f9f9d85c5b7c6089075413627f901b5c722`

**Decision**: Not accepted; one new regression and one incomplete semantic fix remain

## 1. Summary

The follow-up correctly fixes the four original independent reproduction cases:

```text
ACTUAL_CAUSE status=0 reported=4 observed=4 fault=2
PRECEDENCE fault=5 cause=1 scope=1 failing=0x20000000 root_pte_gpa=0x20000000
NONCANONICAL status=2 canonical_pte=0x10002008 aliased_pte=0x0
DRY_CALLBACK status=0 callbacks=0
```

The interleaved two-stage walk and quiet callback implementation are significant corrections. The
documented V2-05 batch limitation and V2-06 shared S/VS configuration limitation are also clear
enough for FORCE to avoid unsupported combinations.

However, the canonical-address fix regresses valid Sv32 addresses, and the cause 7/8 semantic
verifier still contains the broad exemption that the first feedback required to remove. Full V2
acceptance therefore remains blocked.

## 2. Verification Results

The maintainer's published commands reproduce:

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

make stress:
  1026 passed, 2 failed
  unchanged failures: two-stage 90% threshold and Sv32x4 walk

git diff 8bb6c35..5a2b5f9 --check:
  clean

git diff 407dfec..5a2b5f9 --check:
  clean
```

These results do not cover the Sv32 high-address regression or a negative cause 7/8 oracle check.

## 3. Blocking Findings

### R2-01 P0: Native Sv32 rejects the valid upper half of the 32-bit address space

Evidence: `src/core/page_table_tree.cpp:22-35`.

The new native-address validation applies a sign-extension rule to all native modes. For Sv32 it
sets `width=32` and requires addresses with bit 31 set to have bits 63:32 all set. PTG's public API
accepts addresses as `uint64_t`; an RV32 virtual address is naturally represented by its 32-bit
unsigned value, so `0x0000000080000000` through `0x00000000ffffffff` are valid Sv32 addresses.

The current rule rejects that entire valid range. The extended independent reproduction now adds:

```text
SV32_HIGH added=0 resolved=2 hit=0 fault=2
REPRO cause=0 precedence=0 noncanonical=0 callback=0 sv32=1
```

Here `sv32=1` means the new regression was reproduced:

- `add_mapping(0x80000000, ...)` returns false.
- `resolve_pte_on_walk(0x80000000, 0)` returns `PathMiss`.
- `walk(0x80000000)` faults.

Required fix:

- Define the public normalization contract for Sv32 explicitly.
- At minimum, accept zero-extended `uint32_t` addresses in `[0, 0xffffffff]`.
- If sign-extended RV32 values are also accepted for caller convenience, normalize both forms to
  the same 32-bit address and reject all other upper-bit patterns.
- Keep Sv39/Sv48/Sv57 canonical sign-extension checks and x4 GPA width checks mode-specific.

Required regressions:

- Sv32 native: `0x7fffffff`, `0x80000000`, `0xffffffff` are valid.
- If supported, `0xffffffff80000000` normalizes to `0x80000000`.
- The first unsupported 64-bit encoding is rejected without alias mutation.
- Cover add, resolve, walk, remap, invalidate, V2 exact-one, optional-target exact-count, and
  optional-target probability paths.

This is a regression introduced by `5a2b5f9`; it invalidates the claimed V2-03 completion and
affects F-01/A03/A15 for Sv32.

### R2-02 P1: Cause 7/8 still bypass observed cause and diagnostic validation

Evidence:

- `src/fault/fault_oracle.cpp:103-111`
- `tests/fault/test_fault_oracle.cpp:199-214`

The follow-up correctly assigns public `actual_cause = observed.fault_cause`. It does not fully
fix semantic verification. `verify_fault_oracle()` still skips both checks when the requested
mutation is `NonLeafTerminal` or `LeafNotTerminal`:

- Expected diagnostic versus observed `FaultType`
- Expected/request mutation cause versus observed walk cause

The current unit test explicitly accepts arbitrary-looking observations such as:

```cpp
mutation request: NonLeafTerminal
observed cause:   MisalignedSuperpage
observed fault:   AccessFault
expected mapping: LoadPageFault
result:           PTG_FAULT_OK
```

The mismatch between mutation category and observed cause is legitimate. Skipping all semantic
checks is not. The verifier must validate the permitted post-mutation observed outcome for the
specific mode, stage, level, PTE shape, access, and VM controls.

Required fix:

- Rename `FaultOracleObservation::mutation_cause` to reflect that it now carries the observed walk
  cause.
- Derive or pass the expected observed cause for cause 7/8 proposals.
- Always validate observed `FaultType`, observed `FaultCause`, level, failing GPA, and PTE PA.
- A deliberately wrong observed cause or diagnostic must return `SEMANTIC_MISMATCH`.

Required regressions:

- Cause 7 intermediate pointer becoming `MisalignedSuperpage` on native S/VS.
- Cause 7 G-stage variant and its actual observed cause.
- Cause 8 level-zero becoming `NonLeafAtLevelZero`.
- Cause 8 intermediate leaf becoming its actual reserved/structural outcome.
- Negative copies of each case with incorrect observed cause and incorrect diagnostic; both must
  fail verification.

This leaves V2-01 only partially complete and keeps F-04/F-06/F-08/F-10/A09 at risk.

## 4. Missing Strengthening Tests

These are not additional blockers if the existing documented limitations remain unchanged, but
they should be included in the next handoff:

- Interleaved implicit priority at every G-stage level, not only G level zero.
- Exact VS A/D-write G-stage translation priority and diagnostic details.
- Exact-count/probability committed callback count: exactly one publish per committed PTE.
- Multi-item batch failure: zero externally visible callbacks.
- `REQUIRE_FAULT` exact-count selecting multiple levels from one walk without
  `PTG_FAULT_ONE_PER_WALK`, demonstrating the documented per-mutation-only contract.
- Native canonical boundaries for Sv39/Sv48/Sv57 and max/first-invalid GPA for every x4 mode.

## 5. Revised Acceptance Criteria

Please provide one follow-up commit that:

1. Restores the complete valid Sv32 address range under a documented `uint64_t` API contract.
2. Adds Sv32 boundary and V2 target-mode regressions.
3. Removes the broad cause 7/8 semantic-verifier exemption.
4. Validates the permitted observed cause and diagnostic for cause 7/8.
5. Adds negative cause 7/8 oracle tests that fail on wrong observed values.
6. Preserves all four original fixes and produces:

```text
REPRO cause=0 precedence=0 noncanonical=0 callback=0 sv32=0
```

7. Keeps acceptance, verify, ABI, example, stress baseline, and diff quality results unchanged or
   improved.

After these two blockers close, FORCE can accept V2 with the documented V2-05/V2-06 limitations,
mirror the ABI, and proceed to the real Handcar trap matrix.
