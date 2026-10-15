# PTG 两阶翻译问题 — 根因澄清

**日期**: 2026-06-20
**原始报告**: PTG_TWO_STAGE_BUG_REPORT.md (已废弃)
**结论**: ❌ 非 PTG bug ✅ 是 FORCE 集成侧使用问题

---

## 1. 问题回顾

FORCE-RISCV 在集成 PTG 两阶翻译时，`validate()` 返回 `all_ok=0`，`translate_sequential()` 返回 `fault_code=5`。我们误判为 PTG 库 bug 并提交了报告。

## 2. 真实根因

**G-stage `generate_random()` 调用缺少 `gs_inherit=1` 参数。**

VS-stage 页面树在创建时，其所有内存节点（包括中间 PGD/PMD 页表节点）的 GPA 必须被 G-stage 覆盖，才能让硬件 MMU walk 成功。

PTG 提供 `gs_inherit=1` 参数来自动完成这个操作：
1. 遍历 VS-stage 所有节点，收集每个节点的 GPA
2. 为每个 VS 节点 GPA 在 G-stage 创建 identity 映射 (GPA → GPA 或 GPA → 分配的 SPA)
3. 将 VS 节点区域排除在 G-stage 随机生成范围外

文档位置：`/home/guoshibo/page_table_generator/docs/USAGE.md` §6 (第 644-651 行)

## 3. 修复方法

```python
# ❌ 错误用法
g_result = ptg.generate_random(ctx, "G", va_start, va_end, pa_start, pa_end,
                               "Sv39x4", 1, seed=123)

# ✅ 正确用法
g_result = ptg.generate_random(ctx, "G", va_start, va_end, pa_start, pa_end,
                               "Sv39x4", 1, seed=123, gs_inherit=1)
```

## 4. 诊断教训

我们本应更早发现这个问题：
1. **未查阅 `validate()` 完整字段**: `PtgValidateResult.gpa_unreachable` 直接告诉我们"VS 节点 GPA 在 G-stage 不可达"
2. **未查阅 USAGE.md**: 完整的参数说明已存在
3. **源码追踪不够深入**: `context.cpp::translate_sequential()` 中 GS-walk 失败的根因是 VS 节点不在 G-stage，但未进一步检查为何缺失

## 5. FORCE 侧变更

已修复的测试文件：
- `tests/riscv/ptg_two_stage_minimal_force.py` — 添加 `gs_inherit=1`，验证通过
- `tests/riscv/ptg_two_stage_force.py` — 修复中
- `tests/riscv/ptg_csr_timing_force.py` — 修复中
- `tests/riscv/ptg_translate_test_force.py` — 修复中

Phase 2 实施计划已恢复：
- Phase 2.4 不再是"PTG bug 阻塞"状态
- Phase 2.5-2.7 继续进行

## 6. 后续改进

为避免类似问题再次发生：
1. 在 `PtgBackend.py` docstring 中强调 `gs_inherit=1` 在两阶场景的必要性
2. 在 Phase 2 实施计划中加入"VS/G-stage 参数说明"章节
3. 考虑在 `generate_random()` wrapper 中加入默认 `gs_inherit=1` 检测（当 stage="G" 时）

## 7. 对 PTG 团队的致谢

感谢 PTG 团队快速、准确的回复：
- 明确指出根因是我们未正确使用 `gs_inherit` 参数
- 引用 USAGE.md §6 的具体行号
- 提供进阶用法（Pin 表机制）作为后续扩展选项
- `validate()` 的 `gpa_unreachable` 字段是非常好的诊断工具

这份误报的责任完全在 FORCE 集成侧。

---

**报告结束**
