# Checked Allocation / Placement：FORCE 独立验收反馈

## 1. 结论

后续 [placement 生产适配](PTG_PLACEMENT_PRODUCTION_INTEGRATION.md) 已完成 Python 绑定
与代表性模板接入；本篇保留此前独立候选验收阶段的证据和范围。

**后续证据修订：** [trace v2 复核](HANDCAR_TRACE_V2_VALIDATION.md) 发现旧 FPIX ISA
缺 H，初始化提前异常也被 runner 计为 SUCCESS。因此本文历史 `990/990 ISS` 仅保留为
runner 计数，撤回其完整 ELF 场景重放含义。独立 allocation、placement native ISS 和
生成期测试分别有自身证据；本项是 FORCE/FPIX 验收缺口，不归因于 PTG。
后续修复及新 990 ELF 语义审计见 [FPIX 重放验收](FPIX_ELF_REPLAY_ACCEPTANCE.md)，
不把新结果回填到本文旧归档。

**当前候选通过本轮限定合同验收。** B003/B004 的修复及 R003 的串行 checked-allocation、
placement、公开 C ABI 和 stage 失败边界可接受。没有据此扩大到通用宿主 RAM、多 hart、
IOMMU/MPT、并发/parallel batch、自动迁移或回收。

| 项目 | 本轮状态 |
| --- | --- |
| B003 | 原复现现返回对齐的 G root `0xA0004000`；独立检查同时验证 padding 不被重新发放 |
| B004 | 4 KiB 池创建 G root 返回 `PTG_ERR_NO_SPACE (-9)`，不发布零根；追加空间后可重试 |
| R003 | 新 placement ABI 与 checked 串行消费者的限定合同通过；不将增量 mapping/backfill 宣称为全局事务 |
| A001 | 仍部分完成：FORCE 专用池合同保持，未自动解除单 context 等生产限制 |
| A003 | 仍开放：本轮范围以外的 legacy wrapper、OOM、并发及硬件协调未统一验收 |

候选已有的 Query/Strict Export 合同继续通过。FORCE full、真实预留池用例、placement
产物交给隔离 Handcar 的检查均通过。PTG stress 仍有两项已披露失败，不是 PTG 全局全绿。

## 2. 最新候选身份

使用外部 PTG 仓库中的
`.omo/evidence/ptg-checked-allocation-placement/maintainer-response.md`、`task-13.txt` 和
`final-review-summary.md`，以及公共头、`docs/ALLOCATION_AND_PLACEMENT.md`。

**采用回函明确 supersede 后的最新身份**，没有使用旧 `2df08a5c...` 或旧 API 40-check 结论。

| 输入 | SHA-256 |
| --- | --- |
| `build/libptg.so` | `dfee221f7417e950ee1ca93c9a8df697148c5ed50359590e5a82148f0646b082` |
| `build/libptg.a` | `59f9b3671ab5af5b461e634acf1fe6f0cea5a5c8e5af42d917cda9b1c1bcd8f0` |
| `include/ptg/ptg_allocation.h` | `952121074807457f167a126864599a769e8f060fdce3a683a2e7358bbf28fe30` |
| `include/ptg/ptg_status.h` | `c8e87b1262a219892aa071f403f58718d8b93862d5e76c6ad7a86cfee3c6ef95` |
| 隔离 Handcar | `a1013545508251676b63ec93686cd305a7c7140a1795887193a11061e3529224` |

PTG base HEAD 仍为 `1cdf8415efe36533744411d9c7798b036f1fbc76`，候选含未提交和未跟踪的
实现，HEAD/普通 patch 均不能单独充当完整来源证明。当前主库与静态库哈希在验收前后
保持一致，且匹配回函。本轮没有在 PTG 仓库重建或覆盖它们。
候选的冻结副本已随 M1 保存于：
`output/ptg-allocation-acceptance/full-f7y3alcy/m1/m1-xrqod6oe/inputs/bin/ptg/libptg.so`。

## 3. 独立下游验收

新增 `tests/riscv/ptg_allocation_placement_acceptance.py`，按公共头独立声明 placement
ctypes，复用 FORCE 自己已有的独立 Query/Export 检查基础，不导入维护者测试 helper。
预期分配地址来自固定注册池/窗口，状态、CSR、原始 PTE、索引和 layout 前后对比提供
交叉证据，不用待测分配结果生成期望地址。

最终 **39/39**：20 项 allocation/placement 检查，19 项既有独立 query/export 检查。

主要覆盖：

- ABI 40/32 字节自然布局、关键偏移、带未知尾部的初始化、负状态码、同步复制输入。
- B003 的 S root→G root 对齐，以及已消耗 alignment padding 不可重新分配。
- B004 的 NO_SPACE、未发布根、追加 region 后重试、失败不消耗原 4 KiB 区域。
- 合法零根地址；Sv32 的 `2^34` 与 Sv39/48/57 的 `2^56` PPN payload 上界，越界候选
  被跳过并能使用后续 region。不是这些模式的全面 ISA/ISS 验收。
- 重叠/重复/包含 region 拒绝，合法相邻 region，16 KiB 请求不能拼接两个 8 KiB region。
- 注册顺序 first-fit、定制 alignment、按 level 匹配的窗口优先及 GENERAL 回退；同层
  多窗口尊重 caller 顺序，不按地址重新排序；GENERAL 不偷用其他 level 的窗口。
- all-owned 与 explicit GENERAL view 对追加 region 的不同语义。
- 在线 policy 更新不移动旧 CSR/PTE、tree/query 信息或已捕获 layout；切回旧 policy
  不重新发放已占用地址。
- PA 与不同 VMID 的 GPA policy 隔离；未注册 ownership 返回 NOT_INITIALIZED。
- 非法版本/字段/窗口/stride/范围失败且保留旧树；未对齐、扩展、合法重叠只读输入被接受。
- S、VS、G 已有树 replacement 耗尽时保留旧 CSR、PTE 和 layout；VS 需要已有匹配
  G-stage 环境，GPA 所有权注册不替代 context 的 G-stage 绑定。
- deterministic 在分配失败后停止后续工作并保留先前成功提交；非分配型 duplicate
  兼容行为保留。random 分配失败返回零数量且不改写调用者输出。
- VS source 已发布、随后 SPA backfill 耗尽时返回 NO_SPACE；不能误报完全成功或全局回滚。

最终证据是 `output/ptg-allocation-acceptance/downstream-accepted.json` / `.log`。
报告绑定共享库前后哈希和两个测试源哈希，errors/failures 为空。

### 保留的测试开发记录

`downstream-v1.*` 是先期 36 项通过。扩展 stage/backfill 检查时，`downstream-v2.*`
发现夹具只注册 GPA 池、建立 VS，却没有把 G-stage 绑定到 context；补齐显式绑定后，
相关 numerical/state 断言保留。随后 `downstream-final.*` 的一个期望过严：backfill
在 G PTE 图实体化之前就耗尽，Strict Export 返回 TREE_NOT_FOUND (4)，不是已有 G 图
但缺 backing 的 BACKING_UNAVAILABLE (7)。最终增加 raw G 图为空的检查，并按合同
精确断言 `(4, layout_id=0)`。这些文件没有被覆盖，**名称含 final 不代表通过**，以
`downstream-accepted.json` 为最终结论。没有为上述问题修改候选库或弱化 NO_SPACE 断言。

## 4. Placement → 严格导出 → 独立 Handcar

扩展现有独立消费者 `tests/riscv/ptg_strict_export_iss.cc`，仅在编译定义
`PTG_CHECK_ALLOCATION_PLACEMENT` 时启用新测试；默认旧场景保留。

先设置已知 PA/GPA level windows，独立断言 G root=`0xA0010000`、VS root GPA=
`0x50010000`。完成映射与严格 capture 后，在线更换 PA/GPA policy，验证旧 CSR 和
snapshot 不变，再由宿主显式装载到 Handcar。

**9 条架构指令通过**：跨 4 KiB/双 2 MiB HLV→HSV→HLV 及独立 SPA 物理读回；
execute-only VS leaf 虽然 query 结构有效，HLV 仍产生 cause 13；G data leaf 故障后
按原 layout pull 当前 bytes，再执行 HFENCE.GVMA 与 HLV，产生 cause 21 和精确 trap CSR。
这验证了 placement 的实际消费者，不把 policy 更新当成硬件根切换或权限授权。

日志 `placement-iss.log` 含 `calling init:`，确认实际加载当前 `libptg.so` 和指定隔离
Handcar。它不是生产 placement wrapper 已接入、完整 ELF 重放或所有 paging mode 的 ISS 验收。

## 5. 回函清单与回归复跑

所有本轮证据位于 `output/ptg-allocation-acceptance/`。

| 项目 | 实际结果 | 记录 |
| --- | --- | --- |
| 六组 allocation native | `96 + 50 + 69 + (51+8) + 42 + 82 = 398`，无失败 | `vendor-test_*.log` |
| allocation public probe | `formal_contract_pass=true`，9 proof groups，六个 real-source mutation 均命中并被区分，`candidate_objects=56` | `vendor-allocation-probe.log` |
| 新 C99 示例 | 39 checks，通过 | `vendor-c-allocation.log` |
| 原 mapping/export native | 八组共 690 checks，无失败 | `vendor-test_mapping*`、`vendor-test_export*`、graph log |
| 原 mapping public probe | 49 checks，通过 | `vendor-mapping-probe.log` |
| FORCE full | rc=0，146 工具单测、预检、3 smoke、106 M1、40 ctypes、990 generation/ISS | `full-f7y3alcy/workflow.json` |
| M1 原始归档 | 106/106 | `full-f7y3alcy/m1/m1-xrqod6oe` |
| Fault V2 原始归档 | 990/990 两执行阶段 | `full-f7y3alcy/fault_v2/run_218fklw9` |
| FORCE 实际预留池 | 3/3 seeds，通过 | `force-pool-y7dnx35e/pool-contract.json` |
| 原 B003/B004 探针 | 对齐修复、NO_SPACE 修复命中 | `original-reproducer.json` |
| Stress | **1026 passed，2 failed** | `vendor-stress.log` |

没有直接运行会改写外部 build 的 make 目标：六/八组使用现有 binary 复跑，C99 示例
在 FORCE 输出目录重新编译并链接指定共享库。按回函的 public `--all` probe 实际执行
了临时 real-source mutations，只改 `/tmp/opencode` 内副本并链接私有 `.so`，未修改
真实源码/objects/candidate；control relink 与主库行为一致。没有将这些操作描述为本轮
全量冷构建证明，也未重做全部 ASan/LSan/Catch2/Z3 或维护者全部 F1–F4。

Stress 的两个失败为 `at least 90% two-stage translations OK` 和 `Sv32x4 walk`，与回函
一致；另有 `IOMMU verify: 0/10 passed` 诊断，不据此宣称 IOMMU 支持。输出保存在本轮
隔离 `build/`，不覆盖维护者旧 stress 文件。本轮未重建 base HEAD 做字节级对照，前存
定位来源仍是维护者证据。

## 6. 独立验收复现

在 FORCE 根目录 Bash，选择新输出文件，保留旧报告：

```bash
source ./setenv.bash
export PYTHONDONTWRITEBYTECODE=1
PTG_ROOT="/absolute/path/to/page_table_generator"
PTG_SO="$PTG_ROOT/build/libptg.so"
HANDCAR_SO="$PWD/output/handcar-pinned-build-v2/handcar_cosim.so"

python3.12 tests/riscv/ptg_allocation_placement_acceptance.py \
  --ptg-lib "$PTG_SO" --report "$PWD/output/new-allocation-acceptance.json"

g++ -std=c++17 -Wall -Wextra -Werror -DPTG_CHECK_ALLOCATION_PLACEMENT \
  -I"$PTG_ROOT/include" -I"$PWD/utils/handcar" \
  tests/riscv/ptg_strict_export_iss.cc "$PTG_SO" \
  -Wl,-rpath,"$PTG_ROOT/build" -Wl,--export-dynamic -ldl \
  -o "$PWD/output/new-placement-iss"
LD_DEBUG=libs "$PWD/output/new-placement-iss" "$HANDCAR_SO"

python3.12 utils/regression/run_ptg_pool_contract.py \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_SO"
python3.12 utils/regression/hypervisor_workflow.py --profile full \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_SO" --jobs 8
```

## 7. 后续与限制

B003/B004 可按 `dfee221f...` 记为候选修复验收通过；R003 的本次串行 allocation/placement
交付可接受。下一步在 FORCE 正式绑定 placement v1，正确使用其 **负值 PtgStatus 域**，
再评估扩展 owned pool 的 context/阶段配置限制，不能只因 PTG 修复就自动撤掉宿主生命周期约束。

stage failure 的强原子性与增量 mapping/backfill 的部分提交必须分开处理。PA/GPA policy
在线更新只影响以后分配，不释放既有 payload/padding，不迁移页表，也不提供硬件 CSR/fence
事务。A001 宿主 RAM/MMIO、数据所有权、回收，多 hart 及 A003 剩余 legacy 边界继续开放。

候选仍未提交，正式可复现版本需维护者提供不可变源码和构建身份。验收仅绑定此哈希，
未自动为下一份二进制背书。原安装 Handcar 仍为 `8ebad970...`，本轮没有安装、提交、推送，
也未修改外部 PTG 源码/旧证据或 FORCE 生产 adapter。
