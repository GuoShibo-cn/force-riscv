# PTG G-stage Permission Bits Bug Report

## Bug Summary

**PTG `add_mapping()` 传入的权限位（U/A/D bits）未被正确应用到生成的 G-stage PTE**

## Reproduction

### Test File
`tests/riscv/ptg_gstage_ubit_bug_force.py`

### Run Command
```bash
source setenv.bash
bin/friscv -t tests/riscv/ptg_gstage_ubit_bug_force.py --cfg config/riscv_rv64_twostage.config
```

### Expected Behavior
当调用 `ptg.handle.add_mapping(ctx, "G", gpa, spa, 0x200000, 0, 0x7F)` 时：
- 传入权限位 `0x7F` = `0b0111_1111` = V=1, R=1, W=1, U=1, A=1, D=1, X=1
- 生成的 G-stage PTE 应该包含所有这些权限位

### Actual Behavior
生成的 G-stage PTE 只包含部分权限位，缺失 U/A/D 位：

```
[PTE_LOAD] paddr=0xa0005000 pte=0x2800000f (from sparse)
[S2XLATE] FAULT: U bit not set (G-stage requires U=1)
```

**PTE 值分析：**
- PTE = `0x2800000f`
- 低 8 位 = `0x0F` = `0b0000_1111`
- 实际权限位：V=1, R=1, W=1, X=1
- **缺失权限位：U (bit 4), A (bit 5), D (bit 6)**

## Detailed Log

### Input Parameters
```python
# VS-stage mapping
vs_perms = 0x1F  # V=1, R=1, W=1, A=1, D=1
ptg.handle.add_mapping(ctx, "VS", gva, gpa, 0x200000, 0, vs_perms)

# G-stage mapping (问题所在)
g_perms = 0x7F   # V=1, R=1, W=1, U=1, A=1, D=1, X=1
ptg.handle.add_mapping(ctx, "G", gpa, spa, 0x200000, 0, g_perms)
```

### Generated PTE
```
[PTE_LOAD] paddr=0xa0005000 pte=0x2800000f (from sparse)
```

**Bit breakdown:**
```
PTE = 0x2800000f = 0b0010_1000_0000_0000_0000_0000_0000_1111

Bits [7:0]:
  Bit 0 (V) = 1 ✓
  Bit 1 (R) = 1 ✓
  Bit 2 (W) = 1 ✓
  Bit 3 (X) = 1 ✓
  Bit 4 (U) = 0 ✗ ← MISSING
  Bit 5 (A) = 0 ✗ ← MISSING
  Bit 6 (D) = 0 ✗ ← MISSING
  Bit 7 (Reserved) = 0
```

### Spike Translation Failure
```
[S2XLATE] level=0 idx=0 pte_paddr=0xa0005000 pte=0x2800000f ppn=0xa0000
[S2XLATE] FAULT: U bit not set (G-stage requires U=1)
[S2XLATE] THROW: guest page fault (gva=0x80000000 gpa=0x90000010 type=0)
```

## Root Cause Analysis

PTG 的 `add_mapping()` 函数接收权限位参数，但在生成 PTE 时没有正确应用这些位。

**可能的原因：**
1. `add_mapping()` 内部存储权限位时丢失了 U/A/D 位
2. `generate_random()` 在生成 PTE 时覆盖了传入的权限位
3. G-stage PTE 生成逻辑有特殊处理，清除了 U/A/D 位

## Impact

- 无法通过 PTG 生成带有正确权限位的 G-stage 页表
- 两阶转译测试失败（Spike 要求 G-stage PTE 必须设置 U=1）
- 无法验证 Hypervisor Extension 的两阶地址转译功能

## Workaround

手动构建页表（不使用 PTG），直接写入 PTE 值：
```python
# 手动设置 PTE，确保包含 U/A/D 位
pte_value = 0x2800007F  # V=1, R=1, W=1, U=1, A=1, D=1, X=1
self.genThread.writeRegister("x1", pte_value)
self.genInstruction("SD##RISCV", {"rs1": 1, "NoRestriction": 1})
```

参考：`tests/riscv/ptg_two_stage_iss_walk_force.py` 使用手动页表构建成功通过测试。

## Status: FIXED ✅

**Date**: 2026-06-20  
**Fix Commit**: PTG master branch (uncommitted changes)

### Fix Details

PTG 维护者确认并修复了两个 Bug：

| Bug | 问题 | 修复 |
|-----|------|------|
| **Bug 1** | `ptg_add_mapping` 只解析 bits 0-2 (R/W/X)，忽略 bits 4-6 (U/A/D) | 添加 U/A/D 位解析 |
| **Bug 2** | `gs_inherit=1` 默认 U=0 不合理 | 改为默认 U=1 |

### Verification

重新编译 PTG 后测试通过：

```
[PTE_LOAD] paddr=0xa0005000 pte=0x280000df (from sparse)
[S2XLATE] level=0 idx=0 pte_paddr=0xa0005000 pte=0x280000df ppn=0xa0000
[S2XLATE] SUCCESS: gpa=0x90000010 -> pa=0xa0000010
```

**PTE = `0x280000df` = `0b1101_1111`** ✓
- V=1, R=1, W=1, U=1, A=1, D=1, X=1 — 全部位正确！

### Randomized Testing Status

PTG 修复后，随机化测试 (`ptg_two_stage_random_force.py`) 暴露了 **FORCE 约束系统的问题**：

```python
# 期望：强制使用 x1 作为 rs1
self.genInstruction("HLV.D##RISCV", {"rs1": 1})

# 实际：FORCE 仍然随机选择目标寄存器
[SimApiHANDCAR::WriteRegister] x1 0x8a800000/0xffffffffffffffff
[SimApiHANDCAR::WriteRegister] x13 0x1d8de3feba16873c/0xffffffffffffffff  # 随机值！
```

**问题**：`{"rs1": 1}` 参数没有强制 FORCE 使用 x1 作为源寄存器。

**Workaround**：使用 `NoRestriction: 1` 禁用随机化：
```python
self.genInstruction("HLV.D##RISCV", {"rs1": 1, "NoRestriction": 1})
```

**结论**：PTG 的 U/A/D 位 bug 已修复，随机化测试需要解决 FORCE 约束系统问题。

## Environment

- FORCE-RISCV version: feature/hypervisor-phase3 branch
- Commit: 2b7867d (feat(hypervisor): two-stage translation working with NoRestriction)
- Config: `config/riscv_rv64_twostage.config`
- Python: 3.12
- OS: Linux
- PTG version: master branch (post-fix)

## Additional Notes

- VS-stage PTE 的权限位设置正常（0x1F 正确生成）
- 问题仅出现在 G-stage PTE
- `gs_inherit=1` 参数现在默认为 VS 节点创建 U=1 的 G-stage 映射
