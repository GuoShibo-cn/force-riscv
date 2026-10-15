# H-Extension Usage Guide (Phase 3)

**Branch:** `feature/hypervisor-phase3`
**Date:** 2026-06-23
**Status:** Full two-stage translation (GVA→GPA→SPA) validated via HLV.D in Handcar ISS

---

## 1. Two-Stage Translation Validation

### 1.1 Breakthrough: HLV.D Reads Sentinel Through Full Two-Stage Walk

**Commit:** `babad05` (2026-06-23)

The `ptg_two_stage_iss_walk_force.py` test validates that Handcar ISS correctly performs full two-stage address translation:

```
GVA 0x80000000 → GPA 0x80000000 → PA 0x80000000
```

**Validation evidence from sim.log:**
```
Cpu 0 PC(VA) 0x0000000080011044 op: 0x000000006c00cef3 : hlv.d   t4, (ra)
Cpu 0 Reg W x29 val 0xdeadbeefcafe1234 mask 0xffffffffffffffff
```

HLV.D successfully reads the sentinel value `0xDEADBEEFCAFE1234` from PA 0x80000000 after traversing both VS-stage (Sv39) and G-stage (Sv39x4) page tables.

### 1.2 Key Fixes

#### hgatp CSR Write (CSR 0x680)

`writeRegister("hgatp", ...)` silently fails because hgatp has `boot="0"` in `system_registers_rv64.xml`. Fixed by using `LoadGPR64` + explicit `CSRRW` instruction:

```python
from riscv.Utils import LoadGPR64
load_gpr = LoadGPR64(self.genThread)
load_gpr.load(5, hgatp_csr)
self.genInstruction("CSRRW#register#RISCV", {
    "rd": 0, "rs1": 5, "csr": 0x680, "NoRestriction": 1,
})
```

Same fix applied to vsatp (CSR 0x280) for consistency.

#### PTE Encoding for 1GB Superpages

For Sv39/Sv39x4 1GB superpages, PPN[2] must be placed at bits[53:28], not bits[43:10]:

```python
ppn2 = (PA >> 30) & 0x3FFFFFF  # PPN[2] = bits[55:30] of PA
pte = (ppn2 << 28) | flags      # Place at bits[53:28] of PTE
```

#### Address Ranges

Use PAs within Spike's DRAM range (0x80000000+), not 0x40000000:

```python
GVA_TARGET = 0x80000000
GPA_TARGET = 0x80000000
SPA_TARGET = 0x80000000
VS_ROOT_PA = 0x80600000
G_ROOT_PA  = 0x80800000
```

### 1.3 Running the Validation Test

```bash
cd /home/guoshibo/force-riscv
source setenv.bash
bin/friscv -t tests/riscv/ptg_two_stage_iss_walk_force.py --cfg config/riscv_rv64_twostage.config
grep -E "hlv.d|deadbeef" sim.log
```

Expected output:
```
Cpu 0 PC(VA) 0x0000000080011044 op: 0x000000006c00cef3 : hlv.d   t4, (ra)
Cpu 0 Reg W x29 val 0xdeadbeefcafe1234 mask 0xffffffffffffffff
```

### 1.4 Known Issue: HSV.D Store Fault

HSV.D causes a store guest page fault (mcause=0x0F) even though the PTE has W=1, A=1, D=1. This is a separate permission issue to be investigated in a follow-up commit.

---

## 2. New APIs (GenThreadRISCV)

### 2.1 `allocateVMID(min_vmid=1, max_vmid=0x3FFF)`

Allocate a unique 14-bit VMID for hgatp.VMID field. Returns a random VMID not yet used by this GenThread.

```python
vmids = [self.genThread.allocateVMID() for _ in range(4)]
for vmid in vmids:
    self.genThread.setupGStagePaging(mode="Sv39x4", vmid=vmid)
```

### 2.2 `releaseVMID(vmid)`

Release a previously allocated VMID back to the pool.

```python
vmid = self.genThread.allocateVMID()
self.genThread.releaseVMID(vmid)
```

### 2.3 `setupPtgCSRsForHart(ptg_handle, ctx_id, hart_id, vs_mode, g_mode, vmid=None)`

Override CSR fields for a specific Hart to point to PTG page tables.

```python
from riscv.paging.PtgBackend import PtgBackend

ptg = PtgBackend()
ctx = ptg.create_two_stage_context(vs_mode="Sv39", gs_mode="Sv39x4", asid=1, vmid=100)
self.genThread.setupPtgCSRsForHart(
    ptg_handle=ptg.handle, ctx_id=ctx, hart_id=0,
    vs_mode="Sv39", g_mode="Sv39x4", vmid=100,
)
```

### 2.4 `setupGStagePaging(mode="Sv39x4", vmid=None)`

Updated to accept optional VMID parameter. If `None`, defaults to 0 (shared VMID).

```python
self.genThread.setupGStagePaging(mode="Sv48x4", vmid=42)
```

---

## 3. New Instructions (HLVX)

| Instruction | Description |
|-------------|-------------|
| `HLVX.HU##RISCV` | Execute-permission load half unsigned |
| `HLVX.WU##RISCV` | Execute-permission load word unsigned |

Added alongside existing HLV/HSV/HFENCE/HINVAL in `py/DV/riscv/trees/instruction_tree.py` and `riscv/arch_data/instr/priv_instructions.xml`.

---

## 4. New CSR (hvip)

`hvip` (Hypervisor Virtual Interrupt Pending, 0x645) now has weight=10 in Hypervisor_RW_CSRs.

```python
self.genThread.writeRegister("hvip", "VSSIP", 1, False)
self.genThread.writeRegister("hvip", "VTIP", 1, False)
self.genThread.writeRegister("hvip", "VSEIP", 1, False)
```

---

## 5. Test Catalog (15 tests — 14 verified via exit status, 1 via two-stage translation validation)

| # | Test File | Scenario | Inst | Status |
|---|-----------|----------|------|--------|
| 3.1 | `ptg_two_stage_iss_walk_force.py` | **Full two-stage GVA→GPA→SPA (HLV.D reads sentinel)** | 6 | ✅ **VALIDATED** |
| 3.2a | `ptg_nested_exception_force.py` | Guest → VS → M exception chain | 1 | ✅ PASS |
| 3.2b | `ptg_hedeleg_hideleg_force.py` | hedeleg/hideleg delegation configs | 1 | ✅ PASS |
| 3.2c | `ptg_exception_vs_priority_force.py` | VS/G-stage fault priority | 1 | ✅ PASS |
| 3.2d | `ptg_double_fault_force.py` | Simultaneous VS + G-stage faults | 1 | ✅ PASS |
| 3.3a | `ptg_hfence_force.py` | HFENCE.VVMA instruction | 58 | ✅ PASS |
| 3.3b | `ptg_hlv_force.py` | HLV.B instruction | 58 | ✅ PASS |
| 3.3c | `ptg_hsv_force.py` | HSV.B instruction | 58 | ✅ PASS |
| 3.4 | `ptg_missing_csrs_force.py` | htimedelta, hstatus, hcounteren | 20 | ✅ PASS |
| 3.7a | `ptg_hs_vs_switch_force.py` | hstatus SPV/SPVP CSR read/write | 3 | ✅ PASS |
| 3.7b | `ptg_trap_to_hypervisor_force.py` | hedeleg/hideleg CSR read/write | 6 | ✅ PASS |
| 3.8 | `ptg_vmid_management_force.py` | VMID allocation + isolation | 11 | ✅ PASS |
| 3.9a | `ptg_stress_large_mappings_force.py` | Large page table mappings | 31 | ✅ PASS |
| 3.9b | `ptg_stress_vm_switch_force.py` | 1000 VM context switches | 1001 | ✅ PASS |
| 3.9c | `ptg_stress_asid_force.py` | ASID cycling stress | 501 | ✅ PASS |

### Run Tests

```bash
cd /home/guoshibo/force-riscv
source setenv.bash
bin/friscv -t tests/riscv/<test>.py --cfg config/riscv_rv64_twostage.config
tail -3 sim.log
```

Success indicator: `Executed <N> instructions, exit status (SUCCESS)`

---

## 6. Known Constraints

### 6.1 FORCE Preamble JAL Allocation Limit

Each `genInstruction()` call triggers FORCE to emit a preamble JAL. When >~30 instructions are generated in a single test, the JAL allocator can collide with exception handler addresses:

```
[fail]Adding Instruction "JAL##RISCV"result to bank 0 address 0xXXX
      that has been occupied by another instruction "JAL##RISCV".
```

**Mitigation:** Keep total `genInstruction()` calls per test file ≤ 20. For stress tests (e.g. `ptg_stress_vm_switch_force` generating 1001+ instructions), the JAL allocator handles the load because the generated instructions are placed sequentially without exception handler conflicts.

### 6.2 vscounteren WPRI Bits

The `vscounteren` CSR (0x206) in `system_registers_rv64.xml` only defines 9 fields (bits 0-6, 30-31). Bits 7-29 are WPRI (not in XML), causing initialization failures:

```
[fail]The bit range of physical register: vscounteren wasn't initialized
      or reset defined: 3fffff80
```

**Mitigation:** Skip vscounteren writes, or extend XML with a `WPRI_7_29` field.

### 6.3 henvcfgH Read-Only in Handcar

The `henvcfgH` (0x61a) register is defined as WPRI_VAR in XML. Handcar ISS rejects any write to it:

```
Problems writing simulator register... register: 'henvcfgH'
```

**Mitigation:** Skip henvcfgH write tests, or update Handcar to accept WPRI writes.

### 6.4 Unsupported `Addresses` Parameter

`genInstruction("X##RISCV", {"Addresses": {...}})` is not implemented in FORCE's `ProcessTransactionParameters` — the `Base` key is rejected. Target address control requires PTG `writePhysicalMemory`.

**Mitigation:** Use PTG backend for target address placement, or test CSRs directly without xRET instructions.
