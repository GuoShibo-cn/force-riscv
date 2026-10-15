# PTG Bug Report: G-stage walk 函数错误拒绝 U 位

## 问题描述

PTG 的 `walk_raw_with_sse` 函数错误地拒绝 G-stage PTE 的 U 位，但实际上 G-stage PTE **必须有** U=1（根据 RISC-V 规范和 Spike 实现）。

## 复现步骤

```python
ptg = PtgBackend()
ctx = ptg.create_two_stage_context(
    vs_mode="Sv39", gs_mode="Sv39x4",
    asid=1, vmid=1,
    gpa_base=0x80000000, gpa_limit=0x90000000,
    pa_base=0x90000000, pa_limit=0xA0000000,
)

pte_perms = 0x7F  # VRWXUAD (包含 U=1)
ptg.handle.add_mapping(ctx, "G", gpa, spa, 0x200000, 0, pte_perms)

# 尝试 G-stage 转译
pa, fault_code = ptg.handle.translate(ctx, gpa, 0)
# 结果：pa=0, fault=5 (PermUMismatch)
```

## 预期行为

G-stage PTE 必须有 U=1，walk 应该成功。

## 实际行为

PTG 的 walk 函数拒绝有 U 位的 G-stage PTE：
```
G-stage translate: GPA 0x80000000 -> PA 0x00000000 (fault=5)
```

## 根因分析

`page_table_tree.cpp` 的 `walk_raw_with_sse` 函数：

```cpp
if (is_g_stage_ && (pte & PTE_U)) {
    r.hit = false;
    r.fault = FaultType::AccessFault;
    r.fault_cause = FaultCause::PermUMismatch;
    r.fault_level = cur_level;
    return r;
}
```

这个检查是**错误的**！

## 正确行为（Spike 实现）

Spike 的 `s2xlate` 函数（G-stage 转译）要求：
```cpp
} else if (!(pte & PTE_U)) {
  fprintf(stderr, "[S2XLATE] FAULT: U bit not set (G-stage requires U=1)\n");
  break;
}
```

**G-stage PTE 必须有 U=1！**

## 建议修复

删除 PTG 的错误检查：

```cpp
// 删除这段代码：
// if (is_g_stage_ && (pte & PTE_U)) {
//     r.hit = false;
//     r.fault = FaultType::AccessFault;
//     r.fault_cause = FaultCause::PermUMismatch;
//     r.fault_level = cur_level;
//     return r;
// }
```

或者改为检查 U 位必须为 1：

```cpp
if (is_g_stage_ && !(pte & PTE_U)) {
    r.hit = false;
    r.fault = FaultType::AccessFault;
    r.fault_cause = FaultCause::PermUMismatch;
    r.fault_level = cur_level;
    return r;
}
```

## 影响

- 无法使用 PTG 进行两阶转译测试
- G-stage walk 失败（fault=5: PermUMismatch）

## 环境

- PTG version: master branch
- FORCE-RISCV version: feature/hypervisor-phase3 branch
