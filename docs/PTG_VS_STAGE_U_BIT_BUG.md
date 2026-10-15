# PTG Bug Report: VS-stage 中间节点 PTE 缺少 U 位

## 问题描述

PTG 自动创建的 VS-stage 页表节点（中间节点，非叶子 PTE）只有 `V` 位，没有继承用户数据映射的 `U` 位。Spike 在 VS-stage 转译时检查 U 位失败。

## 复现步骤

```python
ptg = PtgBackend()
ctx = ptg.create_two_stage_context(...)

# 添加用户数据映射，权限包含 U=1
pte_perms = 0x7F  # VRWXUAD
ptg.handle.add_mapping(ctx, "VS", gva, gpa, 0x200000, 0, pte_perms)
ptg.handle.add_mapping(ctx, "G", gpa, spa, 0x200000, 0, pte_perms)
```

## 预期行为

VS-stage 所有节点（包括中间节点）的 PTE 应该继承用户数据映射的权限位。

## 实际行为

VS-stage dump 显示：

```json
{
  "nodes": [
    {
      "level": 2,  # 中间节点
      "entries": [
        {"idx": 2, "value": "0x20000401", "flags": "V"}  # ← 只有 V，没有 U
      ]
    },
    {
      "level": 1,  # 中间节点
      "entries": [
        {"idx": 1, "value": "0x20000801", "flags": "V"}  # ← 只有 V，没有 U
      ]
    },
    {
      "level": 0,  # 叶子节点
      "entries": [
        {"idx": 0, "value": "0x200800df", "flags": "VRWXUAD"}  # ← 正确
      ]
    }
  ]
}
```

## Spike 错误日志

```
[WALK] level=2 idx=2 pte_paddr=0x90000010 pte=0x24001401 ppn=0x90005
[WALK] TABLE: next base=0x90005000
[WALK] level=1 idx=0 pte_paddr=0x90005000 pte=0x24001801 ppn=0x90006
[WALK] TABLE: next base=0x90006000
[WALK] level=0 idx=0 pte_paddr=0x90006000 pte=0x240010f7 ppn=0x90004
[S2XLATE] SUCCESS: gpa=0x80000010 -> pa=0x90004010  # G-stage 成功
[PTE_LOAD] paddr=0x90004010 pte=0x0 (from DRAM/MMIO)
[WALK] level=2 idx=2 pte_paddr=0x90004010 pte=0x0 ppn=0x0 s_mode=0 sum=1 mxr=1
[WALK] FAULT: U bit check (U=0 s_mode=0 type=0 sum=1)  # ← VS-stage U 位检查失败
```

## 根因分析

PTG 在创建 VS-stage 页表树时，中间节点（level > 0）的 PTE 只设置了 `V` 位，没有继承用户数据映射的权限位（U/A/D 等）。

**RISC-V 规范要求**：
- 叶子 PTE：包含完整的权限位（R/W/X/U/A/D）
- 中间节点 PTE：只需要 `V` 位，指向下一级页表

**但 Spike 的实现**：
- 在 VS-stage 转译时，如果 `s_mode=0`（S-mode 访问），会检查所有 PTE 的 U 位
- 如果中间节点 PTE 的 U=0，Spike 认为这是 M-mode 页表，拒绝 S-mode 访问

## 建议修复

### 方案 A：中间节点继承叶子节点的 U 位

在 `PageTableTree::add_mapping` 中，创建中间节点 PTE 时，继承叶子节点的权限位：

```cpp
// 创建中间节点 PTE 时，继承叶子节点的 U/A/D 位
uint64_t intermediate_flags = PTE_V;
if (mapping.perm_u) intermediate_flags |= PTE_U;
if (mapping.flag_a) intermediate_flags |= PTE_A;
if (mapping.flag_d) intermediate_flags |= PTE_D;
```

### 方案 B：文档说明 VS-stage 页表需要特殊处理

如果这是 Spike 的特殊要求，需要在文档中说明 VS-stage 页表的中间节点也需要设置 U 位。

## 影响

- 无法使用 PTG 生成的 VS-stage 页表进行 HLV/HSV 指令测试
- Spike 会拒绝所有 VS-stage 转译请求

## 环境

- PTG version: master branch (post-fix)
- FORCE-RISCV version: feature/hypervisor-phase3 branch
- Spike version: standalone-v2 (with H-extension patches)
