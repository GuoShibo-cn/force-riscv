# PTG Fault Injection Capability and Gap Report

**Report date**: 2026-08-03

**Status**: Historical pre-V2 audit; upgrade completed and integrated

**Severity**: High

**PTG baseline**: `407dfec` plus the maintainer's current uncommitted allocator-validation fix

**Reporter**: FORCE-RISCV Hypervisor/PTG integration

> This document preserves the capability gaps observed before Fault Injection V2. It is not the
> current support baseline. See
> [PTG Fault Injection V2 FORCE Integration Status](PTG_FAULT_INJECTION_V2_FORCE_STATUS.md) for
> the accepted PTG baseline, implemented FORCE features, real Handcar trap matrix, current
> boundaries, and next improvements.

## 1. Executive Summary

PTG can currently alter page-table entries and is sufficient for a small deterministic
`InvalidPTE` smoke matrix. It is not yet sufficient for systematic Hypervisor-extension
fault generation across stage, access type, page-table level, guest-fault scope, and fault
cause.

The main blocker is not the number of enum values. The blocker is that the public API cannot
reliably prove which PTE was changed, whether the requested mutation was actually applied,
or whether the mutation produces the requested architectural page fault for the selected
access context.

The highest-priority gaps are:

- Exact `target_va + target_level` selection is not exact. It selects only the leaf reached by
  `target_va`, ignores `target_level`, and silently falls back to another PTE on failure.
- The implicit/explicit guest-fault APIs ignore almost all of `PtgFaultConfig` and always
  invalidate mappings by clearing `V`.
- Several causes can return an injected count even when the PTE did not change or the resulting
  fault is a different cause.
- Access type, privilege, and VM controls are not part of target suitability, so permission and
  A/D mutations cannot guarantee the requested outcome.
- PTG translation reporting loses the actual G-stage cause and frequently hard-codes load or
  `InvalidPTE` results.
- Existing native tests mostly establish no-crash behavior rather than cause-by-cause semantics.

FORCE should continue using the current API only for the already-proven deterministic
`InvalidPTE` cases. Full fault-cause expansion should wait for the acceptance criteria in this
report.

## 2. Scope and Reference Model

This audit covers:

- `PtgFaultConfig` and `FaultInjectionConfig`
- `FaultInjector` target selection and PTE mutation
- S-stage, VS-stage, and G-stage direct injection
- implicit and explicit guest-page-fault helpers
- `translate()` and `translate_sequential()` fault reporting
- native verification and stress coverage
- page-table export and `MemoryModel` synchronization

This audit does not request a Spike or Handcar semantic change. Spike remains the architectural
golden reference. In particular, malformed, invalid, permission-denied, A/D, misaligned
superpage, and invalid NAPOT PTE conditions terminate the walk and raise the page-fault class
selected by the original access. A G-stage walk failure raises the corresponding guest-page
fault. A physical failure while fetching or updating a PTE is a separate access-fault case.

PTG `FaultCause` is best treated as a diagnostic or mutation category. It is not itself an
architectural exception code. The architectural exception type must be derived from stage,
original access, and the point at which the walk failed.

## 3. Required Hypervisor Coverage Model

The upgraded API must support all valid combinations of the following dimensions and reject
invalid combinations explicitly.

| Dimension | Required values |
|---|---|
| Translation stage | S, VS, G |
| Original access | Execute, Read, Write/AMO |
| VS/S architectural result | Instruction, Load, Store/AMO page fault |
| G architectural result | Instruction, Load, Store/AMO guest-page fault |
| Guest scope | Direct G-stage, implicit VS page-table access, explicit final data access |
| Target level | Every level supported by Sv32/Sv39/Sv48/Sv57 and x4 equivalents |
| Target address | Including address zero; exact target must never silently fall back |
| Privilege context | S/U and VS/VU where U/SUM rules affect the result |
| VM controls | ADUE, SUM, MXR, PBMTE, SSE, and applicable NAPOT enablement |
| Operation mode | Exact-one, exact-count, probability, dry-run |

The core H-extension trap matrix is:

| Faulting stage | Execute | Read | Write/AMO |
|---|---:|---:|---:|
| VS-stage | 12 | 13 | 15 |
| G-stage, implicit or explicit | 20 | 21 | 23 |

Virtual-instruction exception 22 is not a PTE fault-injection outcome and should not be folded
into this API.

For implicit guest faults, two levels must be distinguishable:

- The VS walk level whose PTE fetch is being disrupted.
- The G-stage walk level at which translation of that VS page-table GPA fails.

For explicit guest faults, the API must identify the final data GPA and the G-stage walk level
to mutate.

## 4. Current Public API

`include/ptg/ptg.h:169-180` exposes `PtgFaultConfig` with cause, type, level, probability,
random cause, count, leaf filter, target VA, and dry-run fields. The corresponding internal
configuration at `include/ptg/ptg_types.h:304-331` additionally contains `random_type`,
`random_level`, stage flags, and `implicit_guest`.

The C conversion at `src/api/ptg_api.cpp:808-822` does not expose or initialize
`random_type` or `random_level`. The internal stage flags and `implicit_guest` are also not used
to drive the public injection calls.

Documentation is inconsistent:

- `include/ptg/ptg.h:147` and `:170` describe causes 1 through 11.
- `docs/USAGE.md:690` describes causes 1 through 17.
- `FaultCause` currently contains 1 through 13.
- Cause 13 is `MPTDenied`, but `FaultInjector` has no mutation for it; MPTE mutations use a
  separate MPT injector and enum.

## 5. Findings

### F-01 P0: Exact target selection is not exact

Evidence: `src/fault/fault_injector.cpp:37-95`.

The earlier FORCE integration issue correctly reported that `target_va` was completely ignored
and proposed leaf selection followed by a compatibility fallback. The current implementation
closes that older single-leaf regression. The stricter requirement here is new: full fault-matrix
generation needs exact address-and-level selection and therefore cannot accept silent fallback.

When `target_va != 0`, `find_target()` calls `walk_raw(target_va)`, obtains only
`leaf_pte_pa`, and returns that leaf if suitable. `target_level` is not consulted on this path.
If the walk misses or the leaf is unsuitable, the function silently scans the entire tree and
may mutate an unrelated PTE.

Additional target-selection problems:

- VA zero cannot be selected because `target_va == 0` means automatic selection.
- An out-of-range level falls back to a whole-tree scan. The existing test explicitly accepts
  either injection or skip at `tests/verify.cpp:996-1015`.
- Count and probability modes at `fault_injector.cpp:215-364` ignore `target_va` and
  `target_level`.
- `per_leaf_only` is ignored in deterministic mode.
- A target VA mapped by a leaf cannot be used to target the root or intermediate PTEs on its
  walk path.

Required behavior:

- Exact mode must resolve the PTE on the requested address walk at the requested level.
- Unmapped address, nonexistent level, or unsuitable cause must return a non-success status and
  leave the entire tree unchanged.
- Exact mode must never silently select another address or level.
- Address zero must be representable. A separate `has_target` field or a non-address sentinel is
  required.

### F-02 P0: Selection mode is ambiguous

Evidence: `src/fault/fault_injector.cpp:195-213` and `include/ptg/ptg.h:169-180`.

The documented `fault_probability == 0.0` meaning is disabled, but the implementation interprets
zero probability with no random/count options as deterministic single injection. A zeroed C
structure also sets `fault_level=0`, although documentation describes 255 as automatic/random.

`random_level` is serialized internally but is never used by `FaultInjector`. The C API does not
expose `random_level` or `random_type`.

Required behavior:

- Add an explicit selection mode: disabled, exact-one, exact-count, or probability.
- Do not infer mode from a combination of zero values.
- Validate probability range, enum values, level range, and incompatible fields before mutation.
- Provide a documented initializer or a versioned structure with safe defaults.

### F-03 P0: Guest-fault APIs ignore the requested configuration

Evidence: `src/core/context.cpp:165-291`.

`inject_implicit_guest_fault()` and `inject_explicit_guest_fault()` consume only probability and
seed. They do not honor:

- `fault_cause`
- `fault_type`
- `target_level`
- `target_va`
- `target_count`
- `per_leaf_only`
- `dry_run`
- random cause/type/level

Both functions call `invalidate_va()`, so every successful request becomes an `InvalidPTE`
mutation regardless of the requested cause. The C wrappers still set `last_error=PTG_OK` at
`src/api/ptg_api.cpp:856-865` and `:910-919`.

This makes current FORCE tests that vary cause or level through these APIs false coverage. They
exercise the same V-bit invalidation repeatedly.

Required behavior:

- Guest helpers must resolve their implicit or explicit GPA target, then invoke the same checked
  mutation engine as direct injection.
- Every accepted field must either affect behavior or be rejected as unsupported.
- Dry-run must return exactly the same resolved targets and proposed old/new PTE values without
  modifying state.
- Implicit mode must accept a GVA and VS walk level so the intended VS PTE-page GPA can be selected.

### F-04 P0: Injection count does not prove a mutation or requested fault

Evidence: `src/fault/fault_injector.cpp:7-24`, `:98-184`, `:215-367`, and `:369-410`.

The injector increments `count` after dispatch but does not compare old and new PTE values and
does not validate the post-mutation walk. Examples include:

- `ReservedIllegal` has no Sv32 mutation mask, but the operation can still report success.
- `ADZero` clears D when A is already clear. A read may remain unaffected because D is irrelevant
  to the requested access.
- `PermRWXViolation` suitability is not access-specific. Clearing a bit that was already zero is
  a no-op, and clearing R from an RW leaf creates illegal R=0/W=1 encoding instead of a pure read
  permission failure.
- `NonLeafTerminal` sets R on a pointer. This may create a usable leaf or a misaligned-superpage
  fault; it does not guarantee a diagnostic `NonLeafTerminal` result.
- `LeafNotTerminal` can be observed as reserved-illegal, level-zero nonleaf, or invalid next-level
  state depending on the original PTE and level.
- `NonLeafAtLevelZero` requires a pre-existing level-zero pointer, which a valid generated tree
  normally does not contain. If found, its mutation clears V and changes the observed condition
  to `InvalidPTE`.
- `ShadowStackViolation` always converts a leaf to an SS encoding. It does not create the inverse
  case of an SS instruction accessing a normal page and may be a no-op on an existing SS page.

Required behavior:

- A successful result must include `old_pte` and `new_pte`, and they must differ.
- The result must identify the actual mutated PTE PA, address, level, stage, and mutation cause.
- In semantic mode, PTG must perform a post-mutation walk using the requested access/context and
  confirm the expected fault class and diagnostic cause.
- If a requested pure permission failure cannot be represented from the selected PTE without
  changing it into a different malformed class, return unsuitable rather than false success.

### F-05 P0: Permission suitability lacks execution context

Evidence: `src/fault/fault_injector.cpp:14-20`, `:143-171`, and
`src/core/page_table_tree.cpp:363-438`.

`PermUMismatch` only considers a leaf with U=1 and then toggles U. This is appropriate for making
a G-stage PTE invalid because G-stage leaf PTEs require U=1. It is not generally appropriate for
S/VS-stage injection. In the current S/VS software walk, U=1 with SUM=0 is the mismatch, so
clearing U can remove the fault rather than create one. VU behavior cannot be represented because
the walker has no current-privilege input.

`PermRWXViolation` similarly needs the original access and MXR state. `GuestADUpdateFault` needs
ADUE state, a VS PTE that actually requires A/D update, and a writable G-stage mapping that can be
changed to readable but non-writable.

Required behavior:

- Suitability must receive original access, effective privilege, and relevant VM controls.
- U, SUM, MXR, ADUE, SSE, PBMTE, and NAPOT-dependent mutations must be rejected when their required
  context is absent or incompatible.
- Stage-specific rules must be explicit; the same U-bit mutation is not valid for all stages.

### F-06 P0: Translation results are not a reliable fault oracle

Evidence: `src/core/page_table_tree.cpp:303-445`, `:452-578`, and
`src/core/context.cpp:31-100`, `:294-409`.

Observed issues include:

- `walk_raw_with_sse()` reports reserved PTE encodings and G-stage U mismatch as `AccessFault`,
  whereas Spike terminates the walk and raises the access-selected page-fault or guest-page-fault.
- Misaligned-superpage and invalid-NAPOT paths set a diagnostic cause but can leave
  `FaultType::None`.
- Invalid PTE and nonleaf paths frequently hard-code `LoadPageFault` regardless of original access.
- `AddressContext::translate()` overwrites every final G-stage failure with
  `LoadGuestFault + InvalidPTE`.
- `translate_sequential()` similarly overwrites underlying G-stage type/cause and hard-codes load
  results in several VS walk failures.
- The C API `ptg_translate_sequential()` returns only fault type and level, not diagnostic cause,
  PTE PA, failing GPA, or implicit/explicit scope.

The Spike reference behavior is visible in FORCE's checked-in source at
`handcar/patcher/originals/mmu.cc:288-335` and `:373-421`: malformed PTE conditions break the walk,
then the original access selects instruction/load/store page fault or guest-page fault.

Required behavior:

- Preserve the underlying diagnostic cause and failing level.
- Derive architectural type from original access and stage.
- Distinguish implicit G-stage failure while fetching a VS PTE from explicit final-data failure.
- Return the failing input address/GPA and PTE PA in a detailed result API.

### F-07 P1: Fault mutations bypass `MemoryModel` synchronization

Evidence: `src/fault/fault_injector.cpp:98-184` and `:413-436` directly modify node entries.
`PageTableTree::write_pte_synced()` at `src/core/page_table_tree.cpp:893-899` is the established
node-plus-model write path.

If a tree has already been synchronized to a `MemoryModel`, direct fault mutation updates only the
node. `BinaryOutput::serialize()` uses the model when present at
`src/output/binary_output.cpp:42-53`, so a later binary export can omit the injected fault.

Required behavior:

- Route every mutation through a tree-owned synchronized PTE write primitive.
- Add a test that synchronizes first, injects second, then checks node, model, sparse export, and
  dense export contain the same changed PTE.

### F-08 P1: Error and result reporting are insufficient

The direct and guest C APIs return only a count. Zero can mean no candidate, invalid context,
invalid configuration, unsupported cause, probability miss, or already-faulted state. A positive
count does not identify what changed. Most semantic failures still leave `last_error=PTG_OK`.

Required behavior:

- Return or expose a structured status per requested injection.
- Distinguish invalid parameter, unsupported combination, target not found, unsuitable target,
  no mutation, probability miss, and success.
- Return one detailed record per mutation, including requested and resolved values.
- Validate cause 13 as MPT-only rather than silently treating it as a page-table cause.

### F-09 P1: Random modes are not constrained or semantically replayable

Random cause selection is hard-coded to values 1 through 12 at
`src/fault/fault_injector.cpp:228-230` and `:309-312`. It can select extension-dependent causes
without checking extension state and excludes `MPTDenied` without documenting that it belongs to
a different injector. Random type selects values 1 through 6 without checking stage or access.

Count mode chooses candidates based on a randomly assigned cause before shuffle. Probability and
count modes may mutate multiple PTEs on the same walk path, so only the earliest fault is
architecturally observable.

Required behavior:

- Random selection must draw only from caller-approved, context-compatible causes and types.
- Seed replay must reproduce resolved targets, old/new PTEs, and result order.
- Support an option to select at most one PTE per address walk when architectural observability is
  required.
- Stats must be mode-consistent and guest APIs must update them too.

### F-10 P1: Native tests do not establish advertised cause coverage

Current local results on the audited worktree:

```text
make verify: 2096 passed, 0 failed
make stress: 1026 passed, 2 failed
```

The two stress failures are `Stress: Two-Stage Translation` and `Stress: Sv32`; they are outside
this fault-specific acceptance audit and should be tracked separately.

Fault-specific coverage gaps:

- `test_fault_inject_specific()` checks only InvalidPTE, ADZero, and PermRWXViolation injection
  return values; only the permission case performs a post-walk check.
- The target-VA regression checks one level-zero InvalidPTE case and therefore cannot detect that
  `target_level` is ignored.
- Guest C API tests use only InvalidPTE and assert merely that translation later fails.
- Guest dry-run tests call separate debug helpers rather than `PtgFaultConfig.dry_run` on the guest
  injection APIs.
- `stress_all_fault_causes()` loops over causes 1 through 12, discards each injection count, and
  ends with an unconditional no-crash pass. Its title, loop bounds, final assertion text, and
  printed count disagree.
- There are no cause-by-cause old/new PTE assertions.
- There are no full Execute/Read/Write cross-products for S, VS, explicit G, and implicit G.
- There are no exact target tests across every walk level.
- There are no negative assertions proving a failed exact request changed nothing.

## 6. Cause Capability Matrix

The table below describes the current page-table injector, not the separate MPT injector.

| Value | Cause | Current state | Required upgrade |
|---:|---|---|---|
| 1 | InvalidPTE | Mutation works; exact level and guest configuration do not | Exact address/level selection; preserve original access type |
| 2 | ReservedIllegal | Sv39/48/57 mutation exists; Sv32 can report a no-op; reported type is wrong | Mode-specific mask; no-op rejection; page/guest type by access |
| 3 | ADZero | Leaf-only mutation exists but is not access/ADUE aware | Clear required A/D bit for selected access; reject incompatible ADUE mode |
| 4 | MisalignedSuperpage | Works only on superpage leaves; detailed fault type may be missing | Exact superpage level; correct type/cause and negative 4KB test |
| 5 | PermUMismatch | G-stage U clear can work; S/VS behavior is contextually wrong | Stage and privilege-aware U mutation with SUM handling |
| 6 | PermRWXViolation | Bit clear exists; suitability can select no-op or transformed fault | Access/MXR-aware candidate and post-mutation semantic check |
| 7 | NonLeafTerminal | Converts pointer to leaf; may translate or become misaligned | Define as mutation class; report actual architectural outcome |
| 8 | LeafNotTerminal | Clears R/X; observed cause depends on level and W | Define legal preconditions and report actual resulting cause |
| 9 | NonLeafAtLevelZero | Valid trees provide no suitable candidate; mutation changes it to InvalidPTE | Build V=1,R=W=X=0 at L0 from a valid leaf and verify condition |
| 10 | GuestADUpdateFault | Direct W clear exists; dedicated guest APIs ignore it | Implicit-only semantic targeting with ADUE and required VS A/D update |
| 11 | NapotMisaligned | Invalid N encoding can be created; extension/context not checked | NAPOT enablement, level-specific patterns, correct fault type |
| 12 | ShadowStackViolation | Normal-to-SS mutation only; access context ignored | SSE/access-aware two-direction mutation or explicit unsupported status |
| 13 | MPTDenied | Detection value only; not handled by `FaultInjector` | Remove from PTE injector range or explicitly route to MPT API |

Not every cause is valid at every level or stage. Full coverage means all valid combinations are
generated and all invalid combinations return an explicit unsupported/unsuitable result without
mutation. It does not mean forcing every enum through every Cartesian-product cell.

## 7. Requested API Upgrade

Changing the layout of `PtgFaultConfig` in place would break existing ctypes consumers. A
versioned API is preferred.

At minimum, a v2 request needs:

```c
typedef enum {
    PTG_FAULT_DISABLED = 0,
    PTG_FAULT_EXACT_ONE,
    PTG_FAULT_EXACT_COUNT,
    PTG_FAULT_PROBABILITY
} PtgFaultSelectionMode;

typedef enum {
    PTG_FAULT_SCOPE_DIRECT = 0,
    PTG_FAULT_SCOPE_GUEST_IMPLICIT,
    PTG_FAULT_SCOPE_GUEST_EXPLICIT
} PtgFaultScope;

typedef struct {
    uint32_t struct_size;
    uint32_t abi_version;
    int stage;
    int scope;
    int selection_mode;
    int fault_cause;
    int access_type;
    int privilege;
    int target_level;
    int vs_walk_level;
    uint64_t target_address;
    int has_target_address;
    uint32_t target_count;
    double probability;
    uint64_t seed;
    int dry_run;
} PtgFaultRequestV2;
```

The names are illustrative. Equivalent fields are acceptable if the semantics are explicit.

A result record needs at least:

```c
typedef struct {
    int status;
    int stage;
    int scope;
    int requested_cause;
    int actual_cause;
    int expected_fault_type;
    int actual_fault_type;
    int requested_level;
    int resolved_level;
    uint64_t requested_address;
    uint64_t resolved_address;
    uint64_t failing_gpa;
    uint64_t pte_pa;
    uint64_t old_pte;
    uint64_t new_pte;
} PtgFaultResultV2;
```

Required semantic rules:

- Exact request: exactly one requested PTE or a non-success status, with no fallback.
- Exact count: exactly N compatible, distinct PTEs or an explicit partial/insufficient-candidates
  status chosen before mutation.
- Probability: only configured address/level/cause domains are eligible.
- Dry-run: same resolution and result records as a real run, but no state change.
- Guest implicit: resolve the selected VS PTE-page GPA from GVA plus VS walk level, then mutate the
  selected G-stage level translating that GPA.
- Guest explicit: resolve or accept the final data GPA, then mutate the selected G-stage level.
- Every success: old PTE differs from new PTE and post-walk outcome matches the accepted request.

The legacy count-only APIs can remain as compatibility wrappers, but should be documented as
limited and should not silently discard v2 error statuses.

## 8. Native Acceptance Suite

The upgrade should first pass a PTG-native suite without FORCE or Handcar. Suggested mandatory
tests are:

| ID | Test | Mandatory assertion |
|---|---|---|
| A01 | Exact target at VA 0 | Requested VA zero and level are mutated; no other PTE changes |
| A02 | Exact target each Sv39 level | L2, L1, and L0 PTE PAs differ and match the requested walk path |
| A03 | Exact target miss | Unmapped VA returns target-not-found and binary tree snapshot is unchanged |
| A04 | Exact unsuitable cause | Returns unsuitable, no fallback, no PTE change |
| A05 | Dry-run parity | Dry-run and real run resolve identical target/old/new records; only real run mutates |
| A06 | InvalidPTE access cross | Execute/Read/Write produce correct page-fault type at S and VS |
| A07 | G explicit access cross | Execute/Read/Write produce guest-page-fault types 20/21/23 and preserve cause |
| A08 | G implicit access cross | Each original access and each VS walk level produces 20/21/23 at the intended PTE-page GPA |
| A09 | Cause 1 through 12 table | Every supported combination checks exact old/new bits and post-walk type/cause |
| A10 | Unsupported cause table | Invalid combinations and MPTDenied-through-PTE return explicit errors with no mutation |
| A11 | Permission contexts | S/U/VS/VU, SUM, MXR, and G-stage U rules select only semantically valid targets |
| A12 | A/D contexts | Read versus write, ADUE on/off, and GuestADUpdate requirements are distinguished |
| A13 | Memory synchronization | Node, MemoryModel, dense dump, sparse blocks, and write callback expose the same mutation |
| A14 | Count/probability replay | Same seed reproduces target order and old/new PTE records; level filters are honored |
| A15 | C ABI validation | Nulls, invalid enums, invalid levels, out-of-range probability, and small result buffers return documented status |

For every supported cause, tests must assert all of the following rather than only `count > 0`:

- Exact target address and level
- Exact PTE physical address
- Expected old PTE precondition
- Expected changed bit pattern
- No unrelated PTE mutation in exact-one mode
- Correct diagnostic cause
- Correct architectural page-fault or guest-page-fault type for the original access
- Correct implicit/explicit scope and failing GPA
- Correct dry-run behavior

Recommended commands after implementation:

```bash
make verify
make stress
build/fault_acceptance
```

`make verify` and the new fault acceptance target must pass with zero failures. The current two
unrelated stress failures must not increase; a fully clean `make stress` is recommended before
release.

## 9. FORCE/Handcar Acceptance After Native API Passes

Once PTG passes the native suite, FORCE will extend
`tests/riscv/ptg_vs_fault_matrix_force.py` from its current four deterministic InvalidPTE cases.

The current proven baseline is:

- VS load page fault, `mcause=13`
- VS store page fault, `mcause=15`
- G explicit load guest-page fault, `mcause=21`
- G explicit store guest-page fault, `mcause=23`
- Strong checks of `mcause`, `mepc`, `mtval`, `mtval2`, `mtinst`, and `mstatus`

The upgraded real-execution suite will add:

- Instruction page fault 12
- Instruction guest-page fault 20
- All PTG-supported PTE mutation causes at every valid level
- Implicit G-stage faults at each VS walk level
- Explicit final-data G-stage faults
- VS and VU permission contexts where applicable
- Negative cases that must be rejected by PTG before execution
- CSR checks against Spike/Handcar, including failing GPA encoding in `mtval2`

PTG software translation success alone will not count as final acceptance. Each architectural
cell must be triggered by a real instruction and observed through the trap CSRs.

## 10. Requested Maintainer Response

Please confirm one of the following implementation directions:

1. Add the proposed versioned exact/result API while retaining legacy wrappers.
2. Extend the existing API with equivalent explicit target, context, status, and result semantics
   while providing an ABI migration plan.

Before FORCE expands the fault matrix, please provide:

- The implementation commit ID
- Updated public enum and structure documentation
- A cause/stage/level support table
- Native acceptance test output
- Explicit handling policy for `MPTDenied`
- Confirmation that exact requests never fall back
- Confirmation that guest APIs honor cause, type/access, level, target, count, and dry-run

Until then, FORCE will treat only direct, exact, level-zero `InvalidPTE` injection as validated.
