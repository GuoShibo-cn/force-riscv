# 回复：`ptg_validate()` 错用 allocator 校验 VS-stage 节点

**日期**: 2026-08-02

**对应报告**: `PTG_VALIDATE_VS_GPA_ALLOCATOR_BUG_REPORT.md`

**状态**: 已确认并修复

---

## 结论

报告属实，这是 PTG 的 validation 实现缺陷。

在 GPA 与 PA 注册区间不重叠时，`ptg_validate()` 确实会错误地使用全局 PA allocator 校验 VS-stage 页表节点，使合法的 VS 节点被计入 `invalid_addr_nodes`，进而导致 `all_ok=0`。该问题只影响 validation 结果，不影响实际两阶段翻译。

我们使用报告中的原生 C API 用例，在干净重建 `407dfecb3f35c31bc4b876fdd7bcc8a2d11898a8` 后复现了完全相同的结果：

```text
invalid_addr_nodes=3 all_ok=0
translate: spa=0xa0200000 fault=0
```

## 根因

报告给出的根因分析正确。

S-stage 和 G-stage 页表节点由全局 PA allocator 分配，而 VS-stage 页表节点由对应 G-stage context 的 GPA allocator 分配。原 `ptg_validate()` 却把同一个 PA allocator 传给三棵树：

```cpp
auto& pa_alloc = handle->ctx_mgr.pa_allocator();
if (ctx->s_stage())  check_tree(ctx->s_stage(), pa_alloc);
if (ctx->vs_stage()) check_tree(ctx->vs_stage(), pa_alloc);
if (ctx->gs_stage()) check_tree(ctx->gs_stage(), pa_alloc);
```

因此，只要 GPA 与 PA 区间不重叠，VS-stage 节点就会被误判为地址非法。

## 修复

修复采用“由页表树提供其实际绑定的 allocator”的方式，而不是在 validation 层根据 stage 再次推断 allocator。

`PageTableTree` 增加只读 allocator 访问接口：

```cpp
const PageTableAllocator* allocator() const { return allocator_; }
```

`ptg_validate()` 的 `check_tree()` 直接使用待校验树实际绑定的 allocator：

```cpp
auto check_tree = [&](ptg::PageTableTree* tree) {
    if (!tree || !tree->root_node()) return;
    const ptg::PageTableAllocator* alloc = tree->allocator();
    // ...
    if (!alloc || !alloc->is_valid_region(node->base_addr(), node_size))
        vr.invalid_addr_nodes++;
};

if (ctx->s_stage())  check_tree(ctx->s_stage());
if (ctx->vs_stage()) check_tree(ctx->vs_stage());
if (ctx->gs_stage()) check_tree(ctx->gs_stage());
```

这样 S-stage/G-stage 仍使用 PA allocator，VS-stage 自动使用 GPA allocator；共享页表树也会按其实际分配来源进行校验。

## 回归测试

`tests/verify.cpp` 新增了不重叠 GPA/PA 区间的原生 C API 回归场景，明确断言：

- 两阶段翻译继续返回 `SPA=0xA0200000`、`fault=0`
- `invalid_addr_nodes=0`
- `all_ok=1`

该测试在修复前稳定得到：

```text
2094 passed, 2 failed
```

失败项正是 `invalid_addr_nodes` 和 `all_ok` 两个断言。修复后：

```text
2096 passed, 0 failed
NodeRegistry: 39 passed, 0 failed
```

报告中的独立复现程序修复后输出：

```text
nodes=7 ptes=5120 valid=10 leaf=5 nonleaf=5 orphans=0 invalid_addr=0 invalid_pte=0 missing_flags=0 gpa_unreachable=0 gpa_overlap=0 all_ok=1
invalid_addr_nodes=0 all_ok=1
translate: spa=0xa0200000 fault=0
```

## FORCE-RISCV 侧建议

修复版本接入后，可以恢复对 `PtgValidateResult.all_ok == 1` 的直接断言，无需再忽略 `invalid_addr_nodes`。

感谢报告中提供的最小复现、根因定位和验收条件，它们均与本次实际修复结果一致。
