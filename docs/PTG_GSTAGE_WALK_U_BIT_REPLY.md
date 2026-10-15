# PTG Bug Reply: G-stage walk 函数错误拒绝 U 位

**Bug Report**: PTG_GSTAGE_WALK_U_BIT_BUG.md  
**Status**: ✅ 已修复  
**Date**: 2026-07-09

---

## 问题确认

**这是 PTG 的 bug，不是用户使用问题。**

你的分析完全正确。PTG 的 `walk_raw_with_sse` 函数错误地拒绝 G-stage PTE 的 U 位，但实际上 G-stage PTE **必须有 U=1**（根据 RISC-V 规范）。

## 根因分析

PTG 在两个地方犯了同样的错误：

1. **`page_table_tree.cpp:502`** - `walk_raw_with_sse` 函数
2. **`spike_ref_mmu.cpp:117`** - `spike_walk_inner` 函数

两处都写成了：
```cpp
// 错误：拒绝 U=1
if (is_g_stage && (pte & PTE_U)) break;
```

应该是：
```cpp
// 正确：拒绝 U=0（G-stage PTE 必须有 U=1）
if (is_g_stage && !(pte & PTE_U)) break;
```

**逻辑完全反了。**

## 修复方案

### 1. 修复 walk 函数

**`page_table_tree.cpp:502`**:
```cpp
// G-stage PTE 必须有 U=1（RISC-V 规范要求）
if (is_g_stage_ && !(pte & PTE_U)) {
    r.hit = false;
    r.fault = FaultType::AccessFault;
    r.fault_cause = FaultCause::PermUMismatch;
    r.fault_level = cur_level;
    return r;
}
```

**`spike_ref_mmu.cpp:117`**:
```cpp
// G-stage PTE 必须有 U=1（RISC-V 规范要求）
if (is_g_stage && !(pte & PTE_U)) break;
```

### 2. 修复测试

所有 G-stage 映射添加 `perm_u = true`：

**C++ API 测试**:
```cpp
gm.perm_r = true; gm.perm_w = true; gm.perm_u = true;
```

**C API 测试**:
```cpp
// 权限从 3 (RW) 改为 0x13 (RWU)
ptg_add_mapping(h, ctx, 2, gpa, spa, 0x1000, 0, 0x13);
```

## 为什么这个错误能藏这么久

之前的测试都"通过"了，是因为：
1. 测试中的 G-stage 映射没有设置 U 位（U=0）
2. 错误的 walk 函数接受 U=0
3. 所以测试"通过"了

现在修复后：
1. walk 函数要求 U=1
2. 测试中的 G-stage 映射都设置了 U=1
3. 所有测试正确通过

## 测试验证

修复后运行测试：
```
=== 2092 passed, 0 failed ===
```

所有两阶翻译测试都正确通过。

## 影响

- **修复前**：G-stage walk 拒绝 U=1，导致所有两阶翻译失败
- **修复后**：G-stage walk 正确接受 U=1，两阶翻译正常工作

## 感谢

感谢你的详细分析，准确指出了问题的根因和修复方向。这个错误确实是我们对 G-stage U 位语义的理解错误，不是 Spike 的问题。

---

**Status**: ✅ 已修复并测试通过
