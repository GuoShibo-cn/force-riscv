# PTG 映射查询：索引一致性与 Mapper 合同

## 结论与归属

**2026-09-19 更新：** 维护者候选共享库 `8a56c462...` 已通过 FORCE 限定独立验收，
B001/B002 修复通过，R002 的 Mapping Query v1 元数据合同可接受。随后已完成首批
[Python 生产适配](PTG_V1_PRODUCTION_INTEGRATION.md)，C++ Mapper 仍待接通。
下面版本与数据保留旧库问题复现，候选证据见[验收反馈](PTG_MAPPING_EXPORT_V1_ACCEPTANCE_FEEDBACK.md)。

本报告供用户转交 PTG 维护者。**没有修改 PTG 仓库或库文件。**

| ID | 分类 | 结论 | 状态 |
| --- | --- | --- | --- |
| B001 | PTG 索引同步问题，旧库已复现 | `ptg_context_clear` 清除 leaf 后，正反向索引仍返回原映射 | 新候选修复已验收 |
| B002 | PTG 索引同步问题，旧库已复现 | `ptg_remap_va` 接受页内 VA 并更新 PTE，但页首索引和旧反向索引未更新 | 新候选修复已验收 |
| R002 | PTG API 需求 | 明确区分有效 PA=0、未命中与失败；为 FORCE 提供当前映射的 range/size/perm/stage 查询合同 | Query v1 已验收，待生产适配 |

B001/B002 的页表字节与索引不一致已通过纯 C ABI 独立复现。按“查询当前映射”的用途
判定为缺陷，不将其说成 RISC-V 翻译算法错误。如果维护者有意将该索引定义为历史记录，
请明确该合同，并提供当前映射查询；FORCE 不能把历史记录作为访问目标或权限依据。

## 版本

- PTG 工作区 HEAD：`1cdf8415efe36533744411d9c7798b036f1fbc76`。
- 实测库：`/home/guoshibo/page_table_generator/build/libptg.so`。
- 库 SHA-256：`9eeac7b2f69c25f9a778974c1ab1ba71f47fc29c50749070e48e2d77f1eabb29`。
- `include/ptg/ptg.h` SHA-256：`3f7fff2ce6e86a9aeb987c3e61cd4cfa63f9d17a74cf623d9290402a5281fc73`。
- `include/ptg/ptg_types.h` SHA-256：`15ef52056054cee9bcdff5c53a405b2969b264d2933aad71237550f9ccbbc62f`。

HEAD 是源码参照，不作为该二进制可验证构建来源的替代。所有复现结果绑定上述实际库哈希。

## 最小复现

脚本：`tests/riscv/ptg_mapping_query_probe.py`，只使用 Python 标准库和 PTG C ABI，
不使用 FORCE wrapper、C++ Mapper 或 Handcar。脚本调用查询和 mutation，并通过
`ptg_dump_binary_blocks` 读取原始 PTE 字节；其中的 Sv39 walk 只用于诊断，不是生产后端。

```bash
source ./setenv.bash
export PYTHONDONTWRITEBYTECODE=1
python3.12 tests/riscv/ptg_mapping_query_probe.py \
  --ptg-lib /absolute/path/to/libptg.so
```

观察到已知问题/合同限制时退出 1 并输出 JSON，未观察到时退出 0；退出 0 不代表新查询
合同已全面验收。此诊断不加入默认 full 作为预期通过测试，也不把已知缺陷写成正确行为。
初步输出为 `output/ptg-query-integration/query-probe.json`；加入独立 raw PTE 检查后的
输出为 `output/ptg-query-integration/query-probe-raw.json`。

### B001：Clear 后保留旧索引

创建 Sv39 S-stage context，加入两个 4 KiB alias：
`VA 0x4000 → PA 0x84000000`、`VA 0x8000 → PA 0x84000000`，调用
`ptg_context_clear(h, ctx, 0)` 后重新查询。

| 观察 | Clear 前 | Clear 后 |
| --- | --- | --- |
| `find_pa(ctx,S,0x4000)` | `0x84000000`，status=0 | **仍为 `0x84000000`，status=0** |
| `find_vas(ctx,S,0x84000000)` | `[0x4000,0x8000]` | **仍为同一列表** |
| 槽 `0x80002020` 的原始 PTE | `0x210000cf` | **0** |
| `ptg_translate(ctx,0x4000,Read)` | 健康映射 | PA=0、fault_code=2（PTG LoadPF，不是 mcause） |

预期：如果索引表示当前映射，清空后应移除目标 context/stage 的记录，不能再将其报告
为当前映射；其他 context/stage 必须不受影响。若需要保留历史规划记录，应与当前查询
分离。FORCE 使用该索引选择地址时，否则会把已失效映射当成可用。

源码线索：`src/api/ptg_api.cpp:707-729` 清除 leaf PTE，却不更新 mapping table；
`:2467-2499` 的查询读取该表并返回 OK。复现以库输出和原始 PTE 为准，不仅是源码判断。

### B002：页内 Remap 留下旧页首和 Reverse Alias

在独立 context 中创建 `VA 0x200000 → PA 0x85000000` 的 4 KiB 页，调用：

```c
ptg_remap_va(h, ctx, 0, 0x200008, 0x86000000);
```

该调用返回后 `last_error=0`：

| 检查 | 实际 |
| --- | --- |
| `find_pa(ctx,S,0x200000)` | **旧 PA `0x85000000`** |
| `find_pa(ctx,S,0x200008)` | 新索引键对应 `0x86000000` |
| 旧 PA 的 reverse aliases | **仍含 `0x200000`** |
| 新 PA 的 reverse aliases | 只有 `0x200008` |
| 槽 `0x80005000` 原始 PTE | `0x218000cf`，有效，PPN 解码为 **`0x86000000`** |
| 页首软件翻译 | `0x86000000`，fault=0 |

预期必须是以下两种明确合同之一：

1. 接受页内地址：定位实际 leaf，更新整页的当前索引和 reverse aliases；不能保留旧页首
   指向旧 PA 的记录。
2. 只接受页首地址：在任何 mutation 前拒绝此输入，PTE 和索引均保持原样。

不能同时“PTE 改为新物理页”而“页首查询返回旧物理页”。FORCE 如据索引同步数据或处理
反向映射，会选错物理页或产生错误 alias。
源码线索：`src/core/page_table_tree.cpp:791-811` 定位 leaf 后更新 PTE，却使用输入的
页内 `va` 调用 mapping-table remap，而非原 leaf 的记录键。

### R002：零值、页内地址及只读查询

同一健康 context 的额外观察：

- 合法 `VA 0x10000 → PA 0` 与未映射 `VA 0x60000` 的 `find_pa` 均为 `(0, status=0)`。
- `VA 0x4008` 的实际翻译为 `0x84000008`，但 `find_pa` 返回 `(0, status=0)`。
- `include/ptg/ptg_types.h:789-837` 当前 mapping table 仅存精确地址键，没有范围/页尺寸。

精确键本身可以是有效的低层接口设计，但不足以直接实现 FORCE `VmMapper`。不能通过
看到 0 就推断“没有映射”，也不能在 FORCE 中另写一套 walk/影子映射表补足 PTG 状态。
现有 JSON/walk-report、post hook 是可评估的补充接口，尚未证明其满足当前有效性、
原子快照和无副作用查询合同；请维护者建议优先扩展现有接口还是提供版本化 typed query。

## 建议验收标准

1. 查询结果区分 found、未命中、错误，合法 PA=0/VA=0 不被 sentinel 混淆。
2. 清空、重映射、重新添加、故障 mutation 后，当前页表与查询结果保持定义明确的一致性；
   如果故障页需要保留逻辑映射，结果必须区分逻辑存在与访问有效性。
3. 明确页首/页内输入合同，覆盖 4 KiB、superpage、跨页边界和 canonical 正负地址；
   重映射若不支持页内输入必须原子拒绝。
4. Reverse 查询返回全部合法 alias、准确计数和容量语义，且正确隔离 context/stage；
   支持 caller 先查数量再分配，不默默截断。需要并发快照时说明 generation/lifetime 合同。
5. 支持 Mapper 所需的 VA 范围、页尺寸、权限、stage 与地址域信息，明确这些信息是
   当前 PTE、历史规划还是经过访问检查的结果。
6. 生成器只读查询不得隐式写 A/D、修改 PTE 或触发外部内存写回。应专门测试 A/D=0，
   而不是仅在 A/D 已为 1 时比较结果。
7. 使用静态已知映射、原始 PTE 前后比较与独立执行 oracle 验收；不以待测索引或同一
   错误缓存生成 expected。修复后由 FORCE 使用新库独立复验，旧库 full PASS 不可继承。

## FORCE 侧处置

已绑定已有 C API，提供低层 `PtgHandle.mapping_index_pa()` / `mapping_index_vas()`。
方法名和文档明确其为**诊断索引**，不用于 VmMapper 有效性、权限或完整地址翻译。
正向保留 C ABI 的零值语义，不伪造 found 状态；反向用数量/填充两次调用取得完整列表，
逐次检查 PTG error，数量改变即失败。调用者必须串行访问 handle；这不是并发快照保证。

测试覆盖健康精确键、12 个 alias、64 位/负 canonical 地址、S/VS/G 与 context 隔离、
错误 handle/context/tree、数量变化拒绝以及 S-stage 查询前后 PTE 字节不变。
这些 wrapper 测试不把 B001/B002 的错误结果当作正确语义，也不宣称验证了 A/D=0 查询。
初次报告时，15/15 ctypes 和原有 full 回归通过，但 B001/B002/R002 尚未关闭。
现在候选修复与新 API 合同已按顶部增量验收；PTG-backed C++ Mapper 仍未接通，
旧索引 API 的零值/精确键限制仍不能用于一般 Mapper 有效性判定。
