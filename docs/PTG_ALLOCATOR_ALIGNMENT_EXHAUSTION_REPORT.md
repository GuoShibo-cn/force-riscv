# PTG 地址池：G 根表对齐、容量失败与 checked allocation

## 结论与归属

**回函验收更新：** 候选共享库 `dfee221f...` 的 B003/B004 修复和 R003 串行分配/placement
合同已通过 FORCE 独立限定验收，见[验收反馈](PTG_ALLOCATION_PLACEMENT_ACCEPTANCE_FEEDBACK.md)。
下文保留 `8a56c462...` 上的原始复现数据，不表示新候选仍有相同行为。

2026-09-20 FORCE 在推进 A001 地址池所有权时，通过独立 C ABI 探针确认下列行为。
本报告交由用户提交 PTG 维护者；没有修改外部 PTG 源码或库。

| ID | 分类 | 观察 | 状态 |
| --- | --- | --- | --- |
| B003 | PTG 根表分配问题，旧库已复现 | 先分配 S 根表，再配置 G 根表，16 KiB G root 返回未对齐的 `0xA0001000` | 新候选修复已验收 |
| B004 | PTG 容量/错误状态问题，旧库已复现 | PA 池仅 4 KiB 时，G-stage 配置仍报 OK，hgatp.MODE=8、PPN=0，根地址不在注册池 | 新候选修复已验收 |
| R003 | PTG API/allocator 合同需求 | 需要明确对齐、容量失败、有效零地址和失败后状态；优先修复/扩充现有 PTG 分配器与 C API | 串行交付已验收，生产适配待完成 |

这些问题属于 A001/A003 分配和 legacy 配置边界，不是此前 Query v1 / Strict Export v1
限定验收的失败。不能据新查询/导出通过推断整个 allocator 已具备可靠失败合同。

## 输入身份

- 工作区 base HEAD：`1cdf8415efe36533744411d9c7798b036f1fbc76`，含维护者未提交候选实现。
- 实测共享库：`/home/guoshibo/page_table_generator/build/libptg.so`。
- SHA-256：`8a56c462624b3cf7b1636b0021913ba0bf8e10a863910fef4c224997c05bcca0`。
- 此探针不加载 FORCE wrapper/Handcar，也不向任何宿主目标内存写入。

## 最小复现

脚本：`tests/riscv/ptg_pool_contract_probe.py`。每个场景在独立子进程运行，关闭 core dump，
超时 20 秒；父进程保留 stdout/stderr/返回码，避免把 legacy C 异常逃逸混入其他检查。

```bash
source ./setenv.bash
export PYTHONDONTWRITEBYTECODE=1
python3.12 tests/riscv/ptg_pool_contract_probe.py --ptg-lib /absolute/path/to/libptg.so
```

父脚本退出 0 仅表示收集完成，**不是验收 PASS**。结论应读取 JSON 场景字段。
最终原始记录：`output/ptg-pool-integration/allocator-probe-final.json`。

### 对照：恰好容纳一个 G root

注册 PA 区域 base=`0xA0000000`、limit=`0xA0004000`，创建 context，再配置 Sv39x4 G-stage。
返回 `last_error=0`，`hgatp=0x80001000000a0000`，root=`0xA0000000`，整个 16 KiB 根表落在
注册的半开区间内。这也是 limit 为 exclusive 的源码/行为核对。

### B003：4 KiB 分配后的 G root 未对齐

1. 注册 base=`0xA0000000`、limit=`0xA0100000`，基址本身是 16 KiB 对齐。
2. 同一 handle/context 配置 S-stage Sv39，读取 root=`0xA0000000`。
3. 配置 G-stage Sv39x4，立即读取状态和 hgatp。

实际：`last_error=0`，`hgatp=0x80001000000a0001`，G root=`0xA0001000`，仍在池内但不满足
16 KiB 对齐。

预期：Sv39x4 根表为 2048 个 8-byte PTE，大小及基址对齐都要求 16 KiB。分配器应选择
池内满足对齐的区间（例如 `0xA0004000`），或明确失败。不能要求 FORCE 在每次 PTG
分配后自行猜测并补齐 padding，否则会形成另一套分配算法。
影响：生成的 G root/CSR 不能作为合法硬件根表使用；未在此探针中把错误根表送入 ISS，
因此不声称已复现具体 Handcar trap。结论来自明确的 x4 对齐规则和实际分配地址。

### B004：池不足时启用池外零根地址

1. 新 handle 注册 base=`0xA0000000`、limit=`0xA0001000`，仅有 4 KiB。
2. 创建 context 并配置 Sv39x4 G-stage，需要 16 KiB。

实际：调用正常返回、`last_error=0`，`hgatp=0x8000100000000000`，root=0，且该根表区间
不在唯一注册 PA 池内。

预期：返回明确分配失败状态，不能向消费者交付“MODE=8 + 池外 PPN=0”的成功配置。
这个场景的 0 不存在“合法零 SPA”歧义，因为注册池从 `0xA0000000` 开始。
Query/Strict Export v1 已验证的合法零地址能力不应因此撤回，两者是不同合同。

影响：只检查配置返回状态的消费者会继续使用无效根；后续行为可能进一步暴露于旧
stage/registration 的异常边界。此最小复现没有执行后续 mapping，不能把潜在异常写成
本轮已复现的崩溃。

## 源码线索与建议验收

`src/core/page_table_tree.cpp` 的 `PageTableAllocator::allocate_page()` 按 `next_free`
连续递增，不按请求大小对齐；空间不足返回 0。legacy stage 配置没有把这个结果可靠地
转成失败。本定位辅助解释执行结果，不用源码判断替代复现。

建议优先扩展既有接口，具体 ABI 由维护者决定：

1. 分配器明确 `(size, alignment)`，所有加法/对齐取整检查溢出；4 KiB 下级节点与 16 KiB
   G root 在多个 region、交错 context/stage 分配时始终满足各自约束。
2. `base/limit`、重叠 region、耗尽和合法地址 0 的规则明确；成功/失败不要仅用地址 0
   作为唯一信号。
3. stage 初始化、节点分配失败经 C ABI 返回明确状态，不逸出异常、不交付池外根。
   说明失败时是否保持旧 context/tree/allocator cursor，不能产生半成功状态。
4. 验收至少包含：恰好容纳、差 1 byte/一页、先 4 KiB 后 16 KiB、多个区域、边界溢出、
   重叠注册、合法零地址以及失败前后已有树/CSR/索引状态比较。
5. 为 FORCE 后续动态分配/排除区需求先核对已有 region/placement 能力；不以本请求要求
   立即新增通用宿主 RAM/MMIO allocator。PTG 仍不负责替 FORCE 声明硬件 RAM。

## FORCE 当前处理

首期 `with_reserved_table_pool()` 选择一个由 FORCE 预留、基址/大小为 16 KiB 对齐的
非零专用池，限制一个 VMID/VS-G context、一次配置；G root 返回后再检查 MODE、对齐与
边界。不会调整 PTG 根表地址、改写 PTE 或回退 native 后端。失败池不得继续严格装载。
这只建立受限集成合同，**不是 B003/B004 修复**。PTG 端修复现已按顶部更新验收；
FORCE 的初期限制仍保留，更多上下文、动态扩容/回收及完整失败恢复需要继续设计和验证。
