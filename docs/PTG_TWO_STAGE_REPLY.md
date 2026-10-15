# PTG 两阶翻译问题回复

**日期**: 2026-06-20  
**问题**: `validate()` 返回 `all_ok=0`，`translate_sequential()` 返回 `fault_code=5`  
**结论**: **非 PTG bug**，需启用 `gs_inherit=1` 参数

---

## 1. 问题根因

FORCE-RISCV 的 `generate_random()` 调用未启用 `gs_inherit` 参数：

```python
# 当前代码（有问题）
vs_result = ptg.generate_random(ctx, "VS", va, va + size, va, va + size, "Sv39", 1, seed=123)
g_result  = ptg.generate_random(ctx, "G",  va, va + size, va, va + size, "Sv39x4", 1, seed=456)
# ← 缺少 gs_inherit=1
```

**问题**：VS-stage 页表节点（PGD/PMD/PT）的 GPA 没有被自动映射到 G-stage。当 `translate_sequential()` 执行两阶翻译时，G-stage walk 无法翻译 VS 中间节点的 GPA，导致 `fault_level=1`（PMD 层）的 Guest Fault。

---

## 2. 修复方法

在 G-stage 的 `generate_random()` 调用中添加 `gs_inherit=1`：

```python
# 修复后
vs_result = ptg.generate_random(ctx, "VS", va, va + size, va, va + size, "Sv39", 1, seed=123)
g_result  = ptg.generate_random(ctx, "G",  va, va + size, va, va + size, "Sv39x4", 1, seed=456,
                                 gs_inherit=1)  # ← 添加此行
```

### 2.1 `gs_inherit=1` 的作用

当 `gs_inherit=1` 时，PTG 在 G-stage 随机生成前会：

1. 遍历 VS-stage 所有节点（root PGD + 中间 PMD + leaf PTE 页）
2. 收集每个节点的 GPA（`node->base_addr()`）
3. 为每个 GPA 在 G-stage 创建映射（GPA → SPA）
4. 将 VS 节点 GPA 区域排除在随机生成范围外（避免冲突）

这确保了 `translate_sequential()` 的 G-stage walk 能命中所有 VS 节点。

### 2.2 PtgBackend.py 参数支持

`PtgBackend.py:666` 已支持此参数：

```python
cfg.gs_inherit = kwargs.get("gs_inherit", 0)  # 默认 0 = 关闭
```

只需在 `generate_random()` 的 `**kwargs` 中传入 `gs_inherit=1`。

---

## 3. 文档参考

PTG USAGE.md §6 已有完整说明：

> **G-stage VS 节点继承**（仅 G-stage 生效）：
> - `gs_inherit=1`：生成前回填 VS 节点 GPA→SPA 映射。`ptg_remember_vs_mappings` 记录的 pin 表优先；无 pin 表时 walk 当前 G-stage 补充；无 walk hit 则从 allocator 分配新 SPA。回填后自动排除 VS 节点 GPA 区域。

文档位置：`/home/guoshibo/page_table_generator/docs/USAGE.md` 第 644-651 行。

---

## 4. 诊断建议

### 4.1 使用 `validate()` 定位问题

`validate()` 返回的 `PtgValidateResult` 包含 `gpa_unreachable` 字段，表示 VS 节点 GPA 在 G-stage 不可达的数量：

```python
result = ptg.handle.validate(ctx)
print(f"gpa_unreachable: {result.gpa_unreachable}")  # >0 表示有节点未被 G-stage 覆盖
```

当前代码返回 `all_ok=0` 正是因为 `gpa_unreachable > 0`。

### 4.2 使用 `check_vs_tree_integrity()` 获取详细 GPA 列表

C++ API 提供更详细的诊断：

```cpp
std::vector<uint64_t> invalid_gpas = ctx->check_vs_tree_integrity();
// 返回所有在 G-stage 不可达的 VS 节点 GPA
```

此函数检查每个 VS 节点的 GPA 是否在 G-stage 有 Read（和可选的 Write）映射。

---

## 5. 进阶用法：Pin 表机制

如果需要在 G-stage 重建时保留 VS 节点映射，可使用 pin 表：

```python
# 1. 生成初始 G-stage
ptg.generate_random(ctx, "G", ...)

# 2. 记录 VS 节点 GPA→SPA 映射到 pin 表
n = ptg.handle.remember_vs_mappings(ctx)
print(f"Pinned {n} VS node mappings")

# 3. 清除 G-stage（模拟 HFENCE.GVMA）
ptg.handle.context_clear(ctx, "G")

# 4. 重建时继承旧映射
ptg.generate_random(ctx, "G", ..., gs_inherit=1)
```

`ptg_remember_vs_mappings()` 将当前 VS 节点 GPA→SPA 映射保存到 context 内部的 pin 表。后续 `gs_inherit=1` 会优先使用 pin 表中的映射，确保一致性。

---

## 6. 预期修复后输出

启用 `gs_inherit=1` 后：

```
[notice]Front-end: Step 4: validate()
[notice]Front-end:   all_ok=1, total_nodes=6, leaf_ptes=2       ← all_ok=1
[notice]Front-end: Step 5: translate_sequential(0x80000000)
[notice]Front-end:   SPA=0x80000000, fault_code=0, fault_level=0 ← 翻译成功
[notice]Front-end: RESULT: PASS
```

---

## 7. 总结

| 项目 | 说明 |
|------|------|
| **问题** | VS-stage 节点 GPA 未被 G-stage 覆盖 |
| **根因** | 未启用 `gs_inherit=1` 参数 |
| **修复** | `generate_random(ctx, "G", ..., gs_inherit=1)` |
| **文档** | USAGE.md §6 "G-stage VS 节点继承" |
| **诊断** | `validate().gpa_unreachable > 0` 表示覆盖缺失 |

此问题已在 PTG 设计中考虑并提供解决方案，非实现 bug。
