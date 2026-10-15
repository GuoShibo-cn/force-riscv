# 回复：add_mapping 两阶转译问题 — 确认 Bug 并已修复

**日期**: 2026-06-20  
**问题**: `ptg_add_mapping(stage="VS")` 不会自动为 VS-stage 页表节点创建 G-stage 映射  
**结论**: **PTG Bug，已修复**

---

## 1. 问题确认

你说得对。`ptg_add_mapping` 添加 VS-stage 映射时，VS 页表树会创建中间节点（PGD/PMD/PT），这些节点位于 GPA 空间。硬件 walk 时必须经过 G-stage 翻译这些 GPA，但 `add_mapping` 没有自动创建对应的 G-stage 映射。

这是 `gs_inherit` 逻辑只在 `generate_random` 中生效、未在 `add_mapping` 中生效的遗漏。

---

## 2. 修复内容

**文件**: `src/api/ptg_api.cpp` — `ptg_add_mapping()`

**修复逻辑**: 当 `stage == 1`（VS-stage）且存在 G-stage 树时，自动遍历所有 VS-stage 节点，为未覆盖的 GPA 创建 G-stage 映射。

```cpp
// Two-stage: auto-create G-stage mappings for VS-stage page table nodes
if (stage == 1 && ctx->gs_stage()) {
    auto* gs_tree = ctx->gs_stage();
    ctx->vs_stage()->for_each_node([&](const ptg::PageTableNode* node) {
        uint64_t gpa = node->base_addr();
        ptg::WalkResult wr = gs_tree->walk(gpa, ptg::AccessType::Read);
        if (!wr.hit) {
            uint64_t spa = handle->ctx_mgr.pa_allocator().allocate_page(0x1000);
            if (spa == 0) return;
            ptg::MappingEntry gm;
            gm.va = gpa; gm.pa = spa; gm.size = 0x1000;
            gm.leaf_level = 0;
            gm.perm_r = true; gm.perm_w = true; gm.perm_x = false;
            gm.perm_u = true; gm.perm_g = true;
            gm.flag_a = true; gm.flag_d = true;
            gs_tree->add_mapping(gm);
        }
    });
}
```

**自动创建的 G-stage 映射属性**:
- `perm_u = true` (U=1)
- `perm_g = true` (G=1)
- `flag_a = true` (A=1)
- `flag_d = true` (D=1)
- `perm_r = true, perm_w = true` (RW，支持 A/D 硬件写回)

**验证**: 1991 passed, 0 failed

---

## 3. 使用示例

现在可以直接用 `add_mapping` 进行两阶转译：

```python
ptg = PtgBackend()
ctx = ptg.create_two_stage_context(
    vs_mode="Sv39", gs_mode="Sv39x4",
    asid=1, vmid=1,
    gpa_base=0x80000000, gpa_limit=0x90000000,
    pa_base=0x90000000, pa_limit=0xA0000000,
)

# 添加用户数据映射
ptg.handle.add_mapping(ctx, "VS", gva, gpa, 0x200000, 0, 0x7F)
ptg.handle.add_mapping(ctx, "G", gpa, spa, 0x200000, 0, 0x7F)

# VS-stage 页表节点的 G-stage 映射已自动创建
# 两阶转译应该成功
spa, fault_code, fault_level = ptg.handle.translate_sequential(ctx, gva, 0)
# fault_code == 0
```

---

## 4. 与 `gs_inherit` 的关系

| 方式 | 自动创建 VS 节点 G-stage 映射 |
|------|:---:|
| `add_mapping(stage="VS")` | ✅ 自动（本次修复） |
| `generate_random(stage="G", gs_inherit=1)` | ✅ 自动 |
| `generate_random(stage="G", gs_inherit=0)` | ❌ 不自动 |

两种方式不冲突——`gs_inherit` 在 `generate_random` 中会检查已有映射，不会重复创建。

---

## 5. 感谢

感谢你的持续反馈。这个问题确实是 `gs_inherit` 逻辑覆盖不全的遗漏——只考虑了 `generate_random` 场景，忽略了 `add_mapping` 场景。

---

**修复版本**: 请重新编译 PTG 库后测试。
