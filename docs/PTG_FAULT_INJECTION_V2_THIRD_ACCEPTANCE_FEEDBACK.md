# PTG Fault Injection V2 Third Acceptance Feedback

**Review date**: 2026-08-14

**Reviewed PTG commit**: `75574a3dc5c99ebf568cc40073398c5318ee51ec`

**Decision**: Not accepted; cause 7/8 is fixed, but native Sv32 still aliases an invalid
64-bit address encoding

## 1. Summary

The cause 7/8 semantic-verifier blocker from the second review is closed. The verifier now checks
the independently observed `FaultCause` and `FaultType`, and the new negative tests reject an
incorrect observed cause or diagnostic.

The Sv32 fix restores valid zero-extended addresses, including the upper half of the 32-bit address
space, but accepts too many `uint64_t` encodings as sign-extended forms. In particular,
`0xffffffff00001000` is accepted and normalized to `0x1000`, although bit 31 of the low word is
zero and therefore the value is not a valid sign extension of a 32-bit address. This creates an
address alias in add, resolve, walk, remap, invalidate, and V2 target resolution.

FORCE should not mirror the V2 ABI or expand the Handcar trap matrix until this final normalization
boundary is fixed and independently reproduced as zero.

## 2. Independent Reproduction

The independent source was extended with a malformed Sv32 sign-extension case:

```text
tests/riscv/ptg_fault_v2_legacy_repro.cpp
```

Build and run:

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
ACTUAL_CAUSE status=0 reported=4 observed=4 fault=2
PRECEDENCE fault=5 cause=1 scope=1 failing=0x20000000 root_pte_gpa=0x20000000
NONCANONICAL status=2 canonical_pte=0x10002008 aliased_pte=0x0
DRY_CALLBACK status=0 callbacks=0
SV32_HIGH added=1 resolved=0 hit=1 fault=0
SV32_BAD_SIGN added=1 status=0 canonical_pte=0x10001004 aliased_pte=0x10001004 hit=1
REPRO cause=0 precedence=0 noncanonical=0 callback=0 sv32=0 sv32_bad_sign=1
```

Only `sv32_bad_sign=1` remains. It means the malformed encoding resolved the same PTE and completed
the same walk as canonical `0x1000`.

## 3. Blocking Finding

### R3-01 P0: Native Sv32 accepts malformed sign-extension aliases

Evidence: `src/core/page_table_tree.cpp:22-28`.

The current check accepts an Sv32 native address whenever bits 63:32 are either all zero or all
one:

```cpp
const uint64_t upper = address >> 32;
if (upper != 0 && upper != UINT32_MAX) return false;
*normalized = static_cast<uint32_t>(address);
```

Bits 63:32 being all one is necessary but not sufficient for a sign-extended 32-bit value. Bit 31
must also be one. The current implementation therefore incorrectly accepts the complete range:

```text
0xffffffff00000000 through 0xffffffff7fffffff
```

and aliases it to:

```text
0x00000000 through 0x7fffffff
```

For example, `0xffffffff00001000` is not the sign extension of `0x00001000`; the valid 64-bit form
of that address is `0x0000000000001000`.

The public native Sv32 contract should accept exactly:

- Every zero-extended `uint32_t`: `0x0000000000000000` through `0x00000000ffffffff`.
- Optionally, the redundant sign-extended representation of values whose low-word bit 31 is one:
  `0xffffffff80000000` through `0xffffffffffffffff`.
- No other 64-bit encoding.

A minimal equivalent validation is:

```cpp
const uint32_t low = static_cast<uint32_t>(address);
const uint64_t upper = address >> 32;
if (upper != 0 && !(upper == UINT32_MAX && (low & 0x80000000U))) return false;
*normalized = low;
```

The shared helper propagates the alias to these paths:

- `add_mapping`: `src/core/page_table_tree.cpp:258`
- `walk` and `walk_with_config`: `src/core/page_table_tree.cpp:374,562`
- `resolve_pte_on_walk`: `src/core/page_table_tree.cpp:527`
- `invalidate_va`: `src/core/page_table_tree.cpp:704`
- `remap_va`: `src/core/page_table_tree.cpp:791`
- `walk_node_addrs`: `src/core/page_table_tree.cpp:920`
- Direct V2 exact resolver: `src/fault/fault_oracle.cpp:225-227`
- Guest implicit resolver: `src/fault/guest_implicit_resolver.cpp:172-177`
- Guest explicit resolver: `src/fault/guest_explicit_resolver.cpp:108-109,131-134`

Required regressions:

- Accept `0x7fffffff`, `0x80000000`, and `0xffffffff` as zero-extended native Sv32 addresses.
- Accept `0xffffffff80000000` as an optional sign-extended alias of `0x80000000`.
- Reject both endpoints of the malformed range: `0xffffffff00000000` and
  `0xffffffff7fffffff`.
- Prove rejection without mutation or aliasing in add, resolve, walk, remap, invalidate, and V2
  exact-one/optional-target paths.

The revised tests cover `0x0000000100000000`, but that only exercises an upper word of one. They do
not exercise an all-ones upper word paired with low-word bit 31 equal to zero, so the acceptance
suite misses this alias.

## 4. Closed Finding and Residual Test Risk

### R2-02: Cause 7/8 observed outcome validation is fixed

`src/fault/fault_oracle.cpp:284-303` obtains the observed result from a post-mutation walk, records
`observed.fault_cause`, and verifies it against the derived permitted outcome. The verifier at
`src/fault/fault_oracle.cpp:148-166` always checks mcause, diagnostic `FaultType`, observed
`FaultCause`, level, failing GPA, and PTE PA. The negative tests at
`tests/fault/test_fault_oracle.cpp:199-240` reject wrong cause and diagnostic values.

No implementation-level self-verification remains in this path. As a non-blocking strengthening
item, the production `expected_observed_cause()` branches should receive explicit integration tests
for all cause 7 outcomes (`PermUMismatch`, `MisalignedSuperpage`, `PermRWXViolation`, `ADZero`) and
cause 8 outcomes (`NonLeafAtLevelZero`, `ReservedIllegal`, `InvalidPTE`). The current focused oracle
tests manually provide only one permitted mask for each requested cause.

## 5. Verification Results

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

git diff 5a2b5f9..75574a3 --check:
  clean

git diff 407dfec..75574a3 --check:
  clean
```

The successful project suites do not override the independent malformed-address result because no
existing test covers this bit-pattern combination.

## 6. Revised Acceptance Criteria

Please provide one follow-up commit that:

1. Rejects all-ones upper words when native Sv32 low-word bit 31 is zero.
2. Preserves the full zero-extended `uint32_t` range and valid optional sign-extended aliases.
3. Adds the malformed-range endpoint regressions across all shared normalization paths, including
   V2 selection paths.
4. Produces:

```text
REPRO cause=0 precedence=0 noncanonical=0 callback=0 sv32=0 sv32_bad_sign=0
```

5. Keeps acceptance, verify, ABI, example, stress baseline, and diff-quality results unchanged or
   improved.

After this blocker closes, FORCE can accept V2 with the documented V2-05/V2-06 limitations, mirror
the ABI in `PtgBackend.py`, and proceed to the real Handcar trap matrix.
