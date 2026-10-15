# PTG Bug Report: add_mapping 两阶转译自动映射顺序问题

## 问题描述

PTG 修复代码在 `stage == 1`（VS-stage）时触发自动创建 G-stage 映射，但实际使用中调用顺序是先 VS 后 G，当添加 VS-stage 映射时 G-stage 树还不存在。

## 复现步骤

```python
ptg = PtgBackend()
ctx = ptg.create_two_stage_context(...)

# 先添加 VS-stage 映射
ptg.handle.add_mapping(ctx, "VS", gva, gpa, 0x200000, 0, 0x7F)
# 此时 ctx->gs_stage() == nullptr，不会触发自动创建

# 后添加 G-stage 映射  
ptg.handle.add_mapping(ctx, "G", gpa, spa, 0x200000, 0, 0x7F)
# 此时 stage == 2，不会触发自动创建逻辑
```

## 预期行为

VS-stage 页表节点（GPA 0x80000000, 0x80001000, 0x80002000）应该有对应的 G-stage 映射。

## 实际行为

G-stage 只映射了 GPA 0x80000000（1页），VS-stage 页表节点的其他页没有 G-stage 映射。

```
# G-stage dump 显示：
{
  "nodes": [
    {"base_addr": "0x90009000", "entries": [
      {"idx": 0, "ppn": "0x90000"}  # 只映射了 GPA 0x80000000
    ]}
  ]
}
```

## 根因分析

`ptg_api.cpp:317-343` 的修复代码：

```cpp
// Two-stage: auto-create G-stage mappings for VS-stage page table nodes
if (stage == 1 && ctx->gs_stage()) {  // <-- 问题1：此时 gs_stage() == nullptr
    auto* gs_tree = ctx->gs_stage();
    ctx->vs_stage()->for_each_node([&](const ptg::PageTableNode* node) {
        // ...
    });
}
```

**问题1**：当 `add_mapping(stage="VS")` 被调用时，G-stage 树还没有创建（用户还没有调用 `add_mapping(stage="G")`），所以 `ctx->gs_stage()` 返回 nullptr。

**问题2**：即使先调用 `add_mapping(stage="G")` 再调用 `add_mapping(stage="VS")`，修复代码在 `add_mapping` 开始时执行，但 VS-stage 的 mid/leaf 节点是在 `add_mapping` 过程中动态创建的。所以 `for_each_node` 只能遍历到 root 节点，漏掉了 mid/leaf 节点。

**证据**：
- VS-stage dump 显示 3 个节点：GPA 0x80000000, 0x80001000, 0x80002000
- G-stage dump 只显示 GPA 0x80000000 的映射（root 节点）
- 缺少 GPA 0x80001000 和 0x80002000 的 G-stage 映射

## 建议修复

### 方案 A：在 `stage == 2` 时也触发

```cpp
// Two-stage: auto-create G-stage mappings for VS-stage page table nodes
if (stage == 2 && ctx->vs_stage()) {
    auto* vs_tree = ctx->vs_stage();
    vs_tree->for_each_node([&](const ptg::PageTableNode* node) {
        uint64_t gpa = node->base_addr();
        ptg::WalkResult wr = tree->walk(gpa, ptg::AccessType::Read);
        if (!wr.hit) {
            // ... create G-stage mapping
        }
    });
}
```

### 方案 B：延迟到 load_to_force 时

在 `load_to_force` 时检查是否需要自动创建 G-stage 映射。

## 影响

- 无法使用 `add_mapping` 进行确定性两阶转译测试
- 必须先 `add_mapping(stage="G")` 再 `add_mapping(stage="VS")` 才能触发自动创建

## 环境

- PTG version: master branch (post-fix)
- FORCE-RISCV version: feature/hypervisor-phase3 branch
