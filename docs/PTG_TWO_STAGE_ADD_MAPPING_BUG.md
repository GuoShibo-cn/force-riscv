# PTG Bug Report: add_mapping 不支持两阶转译的 VS-stage 页表节点映射

## 问题描述

使用 `ptg_add_mapping` 手动添加 VS-stage 和 G-stage 映射时，VS-stage 页表本身（位于 GPA 空间）没有对应的 G-stage 映射，导致两阶转译失败。

## 复现步骤

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

# 加载到 FORCE
ptg.load_to_force(ctx, "VS", genThread)
ptg.load_to_force(ctx, "G", genThread)
```

## 预期行为

VS-stage 页表节点（位于 GPA 空间）应该有对应的 G-stage 映射，使得两阶转译可以成功。

## 实际行为

VS-stage 转译成功，但访问 VS-stage 页表节点时 G-stage 转译失败：

```
[S2XLATE] SUCCESS: gpa=0x80000010 -> pa=0x90000010  # 第一次成功
...
[PTE_LOAD] paddr=0x90004400 pte=0x0  # 找不到 G-stage 映射
[S2XLATE] FAULT: V=0 R=0 W=0 (invalid)
```

## 根因分析

`ptg_add_mapping` (ptg_api.cpp:317-343) 只添加用户指定的映射，不会自动为 VS-stage 页表节点创建 G-stage 映射。

而 `ptg_random_generate` (ptg_api.cpp:549-589) 有 `gs_inherit` 逻辑，会自动为 VS-stage 页表节点创建 G-stage 映射：

```cpp
// G-stage inherit: backfill VS node GPA→SPA mappings
if (stage == 2 && c.gs_inherit) {
    auto* vs_tree = ptg::get_tree(ctx, 1);
    if (vs_tree) {
        auto vs_ranges = vs_tree->node_address_ranges();
        // ... 为每个 VS 节点页创建 G-stage 映射
    }
}
```

## 建议修复

1. **方案 A**：在 `ptg_add_mapping` 中也支持 `gs_inherit` 参数
2. **方案 B**：添加新 API `ptg_generate_gs_inherit(ctx_id)` 手动触发 G-stage 映射生成
3. **方案 C**：文档说明 `add_mapping` 需要手动管理 VS-stage 页表节点的 G-stage 映射

## 临时解决方案

使用 `generate_random` 并设置 `gs_inherit=1`：

```python
ptg.generate_random(ctx, "VS", ...)
ptg.generate_random(ctx, "G", ..., gs_inherit=1)
```

## 影响

- 无法使用 `add_mapping` 进行确定性两阶转译测试
- 必须使用 `generate_random` + `gs_inherit=1` 才能正确测试两阶转译

## 环境

- PTG version: master branch (commit 5ead18e)
- FORCE-RISCV version: feature/hypervisor-phase3 branch
