# PTG / FORCE Hypervisor 集成需求台账

## 已确认的架构

用户确认：**尽可能应用并发展 PTG，由 PTG 支撑 FORCE Hypervisor 页表能力**。
FORCE 不再发展另一套 native Hypervisor 页表生成器；既有 native 改动和证据保留为历史，
不能据此继续该路线或在 PTG 缺少能力时静默回退。

| 组件 | 职责 |
| --- | --- |
| PTG | VS/G 页表构造、映射/重映射、软件查询、故障注入及相关能力演进 |
| FORCE adapter | 生成器约束、上下文/地址所有权、Mapper 接口、错误传播及 PTG 调用 |
| FORCE 内存/指令 | 预留与同步 PTG 页表、数据初始化、CSR 和 fence 指令 |
| Handcar | 实际翻译、访存、权限、trap 和 fence 行为的执行 oracle |

当前执行顺序以[当前计划的 M2](plans/CURRENT_HYPERVISOR_DEVELOPMENT_PLAN.md)为准。

## 交付规则

每项发现先区分以下类型，不把适配器错误或尚未调查的 API 当成 PTG bug：

- **PTG bug**：独立最小复现已证明库行为违反明确合同/规范。
- **PTG API 需求**：现有合同不足以服务 FORCE 场景；列出现有 API、缺口和期望语义。
- **FORCE adapter bug**：PTG 已返回正确结果/错误，FORCE 未正确处理。
- **待验证假设**：只有源码线索或设计疑问，尚无足够执行证据。

文档须包含：版本/库哈希、最小复现或明确未复现状态、预期与实际、影响、现有接口核对、
建议方向及验收标准。原始失败证据不得改写成通过。
**由用户将文档交给 PTG 维护者**；未经明确授权不修改外部 PTG 仓库、不创建远程 issue、
不推送 PTG 或 FORCE，也不安装新库。需求状态按“待调研 → 待用户转交 → 维护者反馈 →
候选可用 → FORCE 独立验收”记录，不能仅因收到答复就标记关闭。

## 本次核对的基线

**源码交付更新：** PTG 已发布固定 commit
`addd85d973dd5bac9d0e0580e0ade7c32888b48c`，独立 clone 冷构建重现 dfee 库哈希。
FORCE 暂存源码树及正式配置的 full 通过，见[交付验证](SOURCE_DELIVERY_VALIDATION.md)。
下面旧“未提交候选”文字保留其历史阶段含义。

**日志/验收修订：** [trace v2 复核](HANDCAR_TRACE_V2_VALIDATION.md) 修复 FORCE/Handcar
PC 错位和 trap 诊断缺失；历史 990 ISS 只保留 runner 计数含义。随后 FPIX 缺 H、页表
未进入 ELF、提前退出误判均已修复，新 990 ELF 通过语义审计，见
[FPIX 重放验收](FPIX_ELF_REPLAY_ACCEPTANCE.md)。这些问题不归因于 PTG。

**最新 checked-allocation/placement 候选：** 回函已 supersede 旧 `2df08a5c...`，当前共享库
`dfee221f7417e950ee1ca93c9a8df697148c5ed50359590e5a82148f0646b082`、静态库
`59f9b3671ab5af5b461e634acf1fe6f0cea5a5c8e5af42d917cda9b1c1bcd8f0` 已完成 FORCE 独立
限定验收，详见[分配与 placement 验收反馈](PTG_ALLOCATION_PLACEMENT_ACCEPTANCE_FEEDBACK.md)。
B003/B004 修复通过，R003 串行 API 交付可接受；候选仍未提交，不能仅用 base HEAD 表示。
后续 [placement 生产适配](PTG_PLACEMENT_PRODUCTION_INTEGRATION.md) 已完成：正式绑定、
owned pool/代表性模板接入、52 ctypes、106 M1 和新 990 ELF 语义审计通过。
下面 `8a56...`、`9eea...` 均保留为各自历史阶段身份，不将其 PASS 套用到新库。

**2026-09-19 候选更新：** 维护者已交付 B001/B002 修复及 Mapping Query v1 / Strict
Export v1。共享库 SHA-256 为
`8a56c462624b3cf7b1636b0021913ba0bf8e10a863910fef4c224997c05bcca0`，通过本次 FORCE
独立限定验收；完整结论与仍未覆盖项见[验收反馈](PTG_MAPPING_EXPORT_V1_ACCEPTANCE_FEEDBACK.md)。
候选 base HEAD 仍是 `1cdf8415efe36533744411d9c7798b036f1fbc76`，但含未提交源码，不能
用 HEAD 代替候选身份。下面保留首次发现问题时的旧基线，不将不同哈希的证据混用。

- PTG 工作区 HEAD：`1cdf8415efe36533744411d9c7798b036f1fbc76`。
- PTG 库：`/home/guoshibo/page_table_generator/build/libptg.so`。
- PTG SHA-256：`9eeac7b2f69c25f9a778974c1ab1ba71f47fc29c50749070e48e2d77f1eabb29`。
- PTG `include/ptg/ptg.h` SHA-256：`3f7fff2ce6e86a9aeb987c3e61cd4cfa63f9d17a74cf623d9290402a5281fc73`。
- Handcar 仍使用已验收的隔离 `output/handcar-pinned-build-v2/handcar_cosim.so`，SHA-256
  `a1013545508251676b63ec93686cd305a7c7140a1795887193a11061e3529224`。

PTG 工作区存在既有文档/配置改动，全部只读保留；HEAD 与库哈希并列记录，不将 HEAD
冒充该二进制的可验证构建来源。没有更新外部源码、构建或替换依赖。

## 现有接口盘点

以下来自上述公共 C 头和现有 FORCE wrapper，不是臆测 PTG 缺少这些能力：

| 用途 | 已有接口 | FORCE 后续工作 |
| --- | --- | --- |
| PA/GPA 池 | `ptg_register_pa_region`、`ptg_register_gpa_region` | 首期由 FORCE 预留专用池；动态排除/宿主 allocator 合同进一步核对 |
| 上下文/根 CSR | `ptg_context_create`、`*_vs_stage`、`*_gs_stage`、`*_vsatp`、`*_hgatp` | 生命周期、失败处理、CSR 指令与 Mapper 上下文绑定 |
| 映射策略 | `ptg_add_mapping`、`ptg_generate_deterministic`、`ptg_random_generate`、`ptg_random_batch` | 从生成器约束驱动，而非另外生成 PTE |
| 正反向查询 | legacy `ptg_mapping_find_pa/find_vas`；候选新增 `ptg_mapping_query_v1` | Query v1 已接 Python wrapper/正常模板，C++ Mapper 待接；legacy 精确键/零值限制仍存在 |
| 软件翻译 | `ptg_translate`、`ptg_translate_sequential` | 明确 fault、stage、A/D 副作用与生成器查询语义 |
| 映射元数据 | `PtgMappingEntry` post hook、JSON/walk report 导出 | 评估能否提供 Mapper 所需 size/perm/range；不够再请求 typed query |
| 重映射/上下文维护 | `ptg_remap_va`、`ptg_context_clear`、SFENCE/HFENCE、ASID/VMID invalidation | 同步 FORCE/ISS，不能把软件 invalidation 当成真实 fence 指令 |
| 稀疏导出 | legacy blocks/write；候选新增 `ptg_export_layout_create/read/free_v1` | 新 pull 已接入生产封装和首批模板；其他 legacy 调用待迁移，旧 GPA fallback 仍存在 |
| Fault V2 | 已接入的 request/result、VM config、two-call、dry-run/commit | 继续按真实 Handcar trap 扩展覆盖 |
| 并发池/handle | global pool、thread-safe handle、publish/refresh G-stage API | 现阶段仍验收单 hart；不能从存在 API 推断多 hart 已支持 |

## 活跃台账

| ID | 分类/状态 | 说明 | 交付 |
| --- | --- | --- | --- |
| R001 | 新 API 已验收，首批生产迁移完成 | 正常访存及 guest-scope 已用严格装载；其他 legacy 用例仍待迁移，旧 callback fallback 未改变 | [生产适配](PTG_V1_PRODUCTION_INTEGRATION.md)、[验收反馈](PTG_MAPPING_EXPORT_V1_ACCEPTANCE_FEEDBACK.md) |
| B001 | 候选 `8a56c462...` 修复验收通过 | Clear 移除目标索引，其他 context 保留 | [原报告](PTG_MAPPING_QUERY_CONTRACT_REPORT.md)、[验收反馈](PTG_MAPPING_EXPORT_V1_ACCEPTANCE_FEEDBACK.md) |
| B002 | 候选 `8a56c462...` 修复验收通过 | 页内 remap 更新整页正反向关联，共享路径 alias 一致 | [原报告](PTG_MAPPING_QUERY_CONTRACT_REPORT.md)、[验收反馈](PTG_MAPPING_EXPORT_V1_ACCEPTANCE_FEEDBACK.md) |
| B003 | 候选 `dfee221f...` 修复验收通过 | S 后 G root 正确对齐，padding 不被重新发放 | [原报告](PTG_ALLOCATOR_ALIGNMENT_EXHAUSTION_REPORT.md)、[验收反馈](PTG_ALLOCATION_PLACEMENT_ACCEPTANCE_FEEDBACK.md) |
| B004 | 候选 `dfee221f...` 修复验收通过 | 不足容量返回 NO_SPACE，不发布池外根；失败保留旧 stage 状态 | [原报告](PTG_ALLOCATOR_ALIGNMENT_EXHAUSTION_REPORT.md)、[验收反馈](PTG_ALLOCATION_PLACEMENT_ACCEPTANCE_FEEDBACK.md) |
| R003 | 串行 API 已验收，首批 Python 生产绑定完成 | typed policy、PA/GPA 窗口、GENERAL、负状态域、owned pool 与模板/ELF 验证；通用 Mapper 待接 | [生产适配](PTG_PLACEMENT_PRODUCTION_INTEGRATION.md)、[原验收](PTG_ALLOCATION_PLACEMENT_ACCEPTANCE_FEEDBACK.md) |
| R002 | 新 API 已验收，Python 生产封装已接入 | 正常模板消费 Query v1，C++ Mapper/生成器约束尚未接通；不执行权限授权 | [生产适配](PTG_V1_PRODUCTION_INTEGRATION.md)、[原报告](PTG_MAPPING_QUERY_CONTRACT_REPORT.md) |
| F001 | FORCE adapter bug，已修复并通过 full 回归 | ctypes writer 异常被吞；导出错误被空 blocks 掩盖 | 下节，修改与负向测试均在 FORCE |
| F002 | FORCE 预检诊断 bug，已修复 | 旧库缺少 v1 符号时，真正异常被 LD_DEBUG shutdown 尾部挤出错误摘要 | 下节；工具单测、旧库负向实跑及 quick 通过 |
| F003 | FORCE/Handcar 日志 bug，隔离候选已修复 | POST-PC 错配指令、实际 trap 事件缺失；新双 PC/事件日志和汇编核对通过 | [trace v2](HANDCAR_TRACE_V2_VALIDATION.md) |
| F004 | FORCE/FPIX，当前矩阵已修复验收 | H profile、页表 ELF 镜像同步、自环判定、独立场景审计；新 990 ELF 通过，旧证据保留 | [修复与证据](FPIX_ELF_REPLAY_ACCEPTANCE.md) |
| F005 | FORCE C++ adapter 开发期错误，已修复 | 混用了输入 perm 和 Query raw_perm 的 U 位；已按输出域解码并完成正负对照 | [C++ mapper 验收](PTG_CPP_MAPPER_INTEGRATION.md) |
| F006 | FORCE 配置错误，冷构建验收已修复 | 正式生成配置缺 V、FPIX 含 V，mstatus.VS 重放不一致；对齐 ISA 并新增检查，未放宽审计 | [源码交付验证](SOURCE_DELIVERY_VALIDATION.md) |
| A001 | 受限表/数据所有权已接 GenThread，整体未关闭 | 独立 handle/context 的表池、FORCE 数据 SPA 预留和会话 VMID 保留；通用 RAM/MMIO/回收仍开放 | [托管上下文](PTG_MANAGED_CONTEXT_INTEGRATION.md) |
| A002 | C++ published-data 子集已接入，完整 Mapper 开放 | 普通 genVA/genVAforPA 使用 PTG CURRENT 组合范围；受限 RW 筛选、reload 保护，无 native fallback | [C++ mapper](PTG_CPP_MAPPER_INTEGRATION.md) |
| A003 | 部分接入，整体开放 | placement 启用路径的 stage/add_mapping/random 等已检查状态；其余 legacy mutation/OOM/并发边界待核对 | [placement 错误边界](PTG_PLACEMENT_PRODUCTION_INTEGRATION.md) |

旧 PTG fault/allocator 报告保留原状态，不因本次台账建立而批量标记重新验收或关闭。

本轮单 leaf API 被误当作整段映射的初版调用错误已归属 FORCE adapter，复现、
修复和验收见 [上下文集成报告](PTG_MANAGED_CONTEXT_INTEGRATION.md)。没有新增 PTG bug
或 API 请求，不转交为 PTG 缺陷。现有接口已满足本轮结构查询/映射与发布范围。

### 待调研项的关闭条件

以下须区分旧库问题与新候选验收。A001/A003 的通用合同仍未建立完整独立验收，
不将其余疑问混作已确认缺陷：

- A001：已验证首期专用池：调用者提供认可的 RAM 范围，FORCE 锁内 genPA/预留，严格
  装载限原 writer/bank 与池内 SPA，销毁 PTG 后不释放仍可能使用的 backing。真实模板
  验证既有 reservation 排除、邻居哨兵及销毁后 genPA 拒绝。动态 MMIO、跨 context/
  多 hart与回收仍未闭环；后续增加受限数据 SPA 分配和独立 handle 的双上下文验证，
  不等于通用池/多 hart 生命周期完成。B003/B004 已在 dfee 候选验收修复。
- A002：旧索引缺陷已记录并在新候选验收修复。Query v1 已验证零地址、页内/反向/枚举、
  logical/current、A/D=0 无写回及参数/容量保护。它返回结构元数据，不是访问授权；
  FORCE 仍需将其接入上下文/约束/权限模型，不必用 JSON/post hook 绕过新的查询接口。
- A003：期望写入/配置失败能够被 FORCE 调用点可靠检测。实际看到多个 void wrapper 未
  自动消费 `last_error`，但部分模板主动检查，不能直接认定所有调用点是假绿。影响是错误
  context/参数可能延迟暴露；逐一构造 invalid context/stage/资源不足复现并核对 caller，
  验收失败非成功且不错误推进上下文，PTG 正确报错则修 FORCE 而非给 PTG 报 bug。

## F001：适配器失败传播

**归属：FORCE，不是 PTG。** 最小复现使用真实库创建一个 S-stage 4 KiB 映射：

1. `writePhysicalMemory()` 在第二个 block 抛 `OSError`。原 `load_to_force()` 将写入放在
   ctypes 回调中，异常打印 `Exception ignored on calling ctypes callback function` 后被吞掉。
2. 用不存在的 context 调用导出，PTG 已给出 `last_error=-2`，原 wrapper 未检查，返回空列表。

预期是向调用者传播失败，不把不完整页表装载报告成功。修复后先在回调内收集 snapshot，
将回调异常带回 Python 抛出并检查 PTG error；成功导出后才在普通 Python 调用栈写 FORCE
内存，writer 出错立即停止。已成功写入的 block 不回滚，不能宣称原子装载。
去除同步导出回调的长期保留，避免每次装载累计持有 callback/gen-thread。
代价是临时保存整份稀疏 snapshot；其内存消耗与导出大小成正比，不是零拷贝流式装载。

复现和测试入口：`tests/riscv/ptg_fault_v2_ctypes_test.py` 的三个 `test_force_*` 测试。
首个失败记录：`output/ptg-first-integration/ctypes-before.log`，新增两项测试均失败；
后续增加收集回调 `MemoryError` 传播检查。该修复不能检测 R001 中 PTG 返回 OK 的危险
回退，R001 仍开放；现有故障注入测试依赖的旧导出行为没有被静默改写。

最终验证：`output/ptg-first-integration/ctypes-final.log` 为 11/11 通过；
`output/ptg-first-integration/full-_0pto9vu/workflow.json` 为 rc=0，包含 145 工具单测、
预检、3 smoke、106/106 M1、11 项 ctypes 及 990/990 generation、990/990 独立 ISS。
M1 原始归档为 `full-_0pto9vu/m1/m1-9m98hpvr`，Fault V2 原始归档为
`full-_0pto9vu/fault_v2/run_rg1kpq33`，均相对上述证据根目录。前后 Handcar/PTG 哈希一致。
这些结果证明适配器改动未破坏现有矩阵，不代表 PTG-backed C++ Mapper 或 R001 已完成。

## 旧查询接口阶段证据（历史）

新增 `mapping_index_pa` / `mapping_index_vas` 的用途只限显式诊断索引，不能据此把
live Mapper 标为完成。反向查询检查两次 C 调用的状态和数量，拒绝截断或数量变化；
没有用软件翻译或 native 后端偷偷替代索引查询。

- 纯 C ABI 复现：`tests/riscv/ptg_mapping_query_probe.py`。
- 原始结果：`output/ptg-query-integration/query-probe-raw.json`，包含 raw PTE 槽地址及值，
  无 FORCE/ISS 回调或外部文件修改。诊断退出 1 是复现命中，不作为预期通过回归。
- ctypes：`output/ptg-query-integration/ctypes-1.log`，15/15；新四项测试覆盖健康精确键、
  全部 alias、64 位和 canonical 地址、context/stage 隔离、错误传播及数量变化拒绝。
- full：`output/ptg-query-integration/full-jkp9icg4/workflow.json`，rc=0；145 工具单测、
  预检、3 smoke、106 M1、15 ctypes、990 generation 和 990 独立 ISS。
- M1 归档：`full-jkp9icg4/m1/m1-f6_kcqoo`；Fault V2 归档：
  `full-jkp9icg4/fault_v2/run_0wl0gldl`，均相对上述 `output/ptg-query-integration/`。

已核对库哈希仍与本台账基线一致。新问题已形成文档，待用户转交；未修改、安装或发布
PTG，也未宣称 B001/B002 因 wrapper 回归通过而修复。地址池所有权 A001 和其他 void
API 错误合同 A003 可继续推进；R001/R002 的严格导出/当前查询合同仍需与维护者协调。

## 2026-09-19 新候选验收

回函在外部 PTG 仓库 `.omo/evidence/ptg-mapping-query-strict-export/maintainer-response.md`。
本轮没有重建或改动外部依赖，在 FORCE 输出目录运行了清单复跑、独立 19 项下游检查、
新严格导出产物的 9 条 Handcar 架构指令，以及完整 FORCE 回归。

- 下游新合同：`output/ptg-contracts-acceptance/downstream-final.json`，19/19。
- Strict Export → Handcar：`strict-iss-loader.log`（同一证据根目录），实际加载证据及
  跨页/2 MiB 读写、结构有效但无读权限 cause 13、冻结布局同步 G fault 后 cause 21 均通过。
- 兼容回归：`full-azkh8dfv/workflow.json`，106 M1、15 旧 ctypes、990 generation/ISS。
- PTG stress 仍为 1026 passed / 2 failed；不宣称整个 PTG 全绿。

验收时旧 `load_to_force()` 仍调用 legacy callback 导出，后续首批迁移如下；未迁移用例
仍显式使用旧方法。不可用新 API 时明确失败，不回退到 native 页表生成器。

## 2026-09-19 首批生产迁移与 F002

已实现 `query_mappings`、`capture_export_layout`、`load_export_layouts` 和可关闭的
`PtgExportLayout`，数据检查及生命周期见[生产适配说明](PTG_V1_PRODUCTION_INTEGRATION.md)。
正常访存 fixed/access 模板与 guest-scope 共享装载路径（implicit/explicit）已迁移，
实际执行 marker 对应 103 个 M1 用例和 81 个 guest-scope generation 用例。

- `output/ptg-v1-production/ctypes-final.log`：32/32，其中 17 项新封装测试。
- `independent-v1.json`：19/19 原独立 ABI/合同检查，未以生产声明替代独立 oracle。
- `full-isp_35fv/workflow.json`：106/106 M1、32 ctypes、990 generation/ISS，通过。
- 上述后三个相对路径均在 `output/ptg-v1-production/` 下。

F002 的归属是 FORCE 预检工具，不是 PTG：对旧 `9eeac7b2...` 库新增 v1 能力检查后，
预期显示缺失符号/能力信息，实际原错误摘要仅截取 stderr 尾部，被大量 loader fini 日志
淹没（`old-candidate-preflight.log`）。修复仅改变错误文本渲染，保留完整原始 loader 数据
用于验证；工具测试在长 shutdown trace 前放入异常，确保摘要保留它。
`old-candidate-preflight-final.log` 已实际显示缺失 `ptg_mapping_query_v1_init` 和
`lacks Mapping Query/Strict Export v1`；`quick-erj9n5oo/workflow.json` 的 146 工具单测、
预检、3 smoke 通过。验收标准是能力缺失非成功且诊断可见，正常加载证据不被过滤。

首个生产单测失败来自空树 fixture：只有 context/stage 没有映射，capture 正确返回
TREE_NOT_FOUND；修正夹具后通过，没有新增 PTG bug。A001 地址池所有权、A003 其他
legacy void 错误合同、剩余旧装载路径及 C++ Mapper 仍继续推进。

## 2026-09-20 地址池阶段

新增 `with_reserved_table_pool()`，采用已有 FORCE/ PTG 接口建立受限单 VS/G context
页表池，M1 access matrix 已迁移。40/40 ctypes（新增 8 项池测试）、独立 19/19 合同
检查、106/106 M1 和 990/990 generation/ISS 通过：
`output/ptg-pool-integration/full-xdidtvut/workflow.json`。
专项真实模板三 seed 通过，最终报告为
`output/ptg-pool-integration/force-pool-q4zeazbl/pool-contract.json`。

纯 C ABI allocator 探针结果在 `output/ptg-pool-integration/allocator-probe-final.json`：
16 KiB exact-fit 对照通过，B003/B004 命中。该行为不是 FORCE wrapper 引入，也未通过
改动 PTG 或额外 native 分配器绕过。当时 R003 尚待反馈；后续回函验收和生产接入见上方最新状态。
当前新 handle/单 VMID/context/一次配置、池内根校验和写入范围限制不构成底层缺陷修复。
具体约束、失败日志与复现命令见[地址池适配](PTG_RESERVED_POOL_INTEGRATION.md)。

## Checked-allocation / placement 回函验收

回函位于外部 PTG `.omo/evidence/ptg-checked-allocation-placement/maintainer-response.md`。
采用最新 dfee 共享库，而非已被 supersede 的 2df 产物。生产 adapter 本轮未改动，只新增
下游验收并扩展独立 ISS 消费者的编译时测试模式。

- 独立下游：`output/ptg-allocation-acceptance/downstream-accepted.json`，39/39，含 20 项
  新 allocation/placement 检查及 19 项已有 query/export 检查。
- 维护者清单复跑：allocation 398 checks、mapping/export 690 checks；public `--all`
  probe 的 ABI、六个真实源码变异验证和 C99 示例 39 checks 均通过。
- placement → Handcar：`placement-iss.log`，九条架构指令与实际库加载记录通过；证明
  指定根位置可执行，在线 policy 更新不等于根切换/迁移。
- 原始 B003/B004 探针：`original-reproducer.json`，对齐根 `0xA0004000` 与 NO_SPACE 已确认。
- FORCE full：`full-f7y3alcy/workflow.json`，106 M1、40 ctypes、990 generation/ISS，通过。
- 实际预留池：`force-pool-y7dnx35e/pool-contract.json`，3/3 seeds。
- 上述相对路径均在 `output/ptg-allocation-acceptance/`。stress 仍有两项已披露失败。

stage 创建失败的强原子性不应外推为整个 deterministic/random/backfill 事务回滚。
已提交的映射可能保留，而随后分配失败必须报告并停止。本轮受限验收不覆盖通用 OOM、
并发/IOMMU/MPT、宿主 allocator 或硬件协调，A001/A003 继续开放。
