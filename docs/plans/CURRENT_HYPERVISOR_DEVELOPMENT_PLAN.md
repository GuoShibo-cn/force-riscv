# FORCE-RISCV Hypervisor 当前开发状态与后续计划

> 最新 C++ 增量：[PTG 数据 mapper](../PTG_CPP_MAPPER_INTEGRATION.md) 已接入普通数据
> genVA/genVAforPA、组合 range 与 native reload/失效绑定保护。新三 seed 自动选址 ELF、
> 原三 seed context ELF、12 合同及 106/990 均通过。当前只复用已发布 RW 映射；通用
> PageInfo/权限约束、动态建图更新和隐式操作数选址仍未完成，M2 总体不勾选。

> 最新 GenThread 闭环：[托管 PTG 上下文](../PTG_MANAGED_CONTEXT_INTEGRATION.md) 已接入
> 受约束数据 SPA 分配、两阶段 CURRENT 正反向/交集 range 和发布/CSR-fence 激活。
> 12 项合同、3 seed 双地址空间 ELF（每例 64 轮交替激活）及原有 106/990 通过。
> C++ VmMapper/genVA 自动接入与 native root reload 协调仍待完成，M2 整体不勾选。

> 最新复核：[trace v2](../HANDCAR_TRACE_V2_VALIDATION.md) 修复了日志 PC/指令错位和
> trap 诊断事件缺失，并通过新隔离库 M1/汇编核对。另已发现 FPIX 缺 H、初始化提前
> 异常仍报 SUCCESS，历史 990 ISS 计数不再作为完整 ELF 重放证据。该缺口现已修复，
> 新生成的 990 ELF 通过独立场景审计，见 [重放验收](../FPIX_ELF_REPLAY_ACCEPTANCE.md)。
> placement v1 生产绑定现已接通，见 [集成说明](../PTG_PLACEMENT_PRODUCTION_INTEGRATION.md)：
> owned pool/access/guest-scope 模板、52 ctypes、106 M1、990 ELF 审计通过。下一步接入更通用
> 的上下文/地址约束及 CSR/fence 生命周期；单 context 限制不自动放宽，旧记录保留原始结果。

> 基准分支：`feature/hypervisor-phase3`
> 基准提交：`48f8514`
> 核对日期：2026-07-16
> 文档性质：当前唯一状态基线；其他 Phase 1/2/3 和早期两阶段计划仅作为历史设计输入

> **用户确认的当前路线：PTG-first。** Hypervisor 页表生成统一采用 PTG，FORCE 负责
> adapter、生成器约束/上下文、内存同步及 CSR/fence 指令，Handcar 负责真实执行验证。
> 依据 FORCE 使用需求优先应用和扩充 PTG，不再发展独立 native Hypervisor 页表生成器。
> 所有 PTG 需求/问题形成可转交文档，由用户提交给 PTG 维护者。当前工作顺序以修订后的
> M2 为准；下面 native 路线的实现和 PASS 均为历史证据，不等同 PTG 集成完成。
> 接口盘点、问题归属与交付规则见 [PTG 集成需求台账](../PTG_FORCE_INTEGRATION_REQUIREMENTS.md)。

> 2026-09-06 后续增量：M2 第 1 项已在 **RV64 Sv39/Sv39x4、单 hart 0、VS 页表 backing
> 恒等映射、宿主显式初始化 RAM** 的合同下完成 native 验收。真实分配器和内存字节 walk、
> 102 seeds 的隔离 Handcar HLV/HSV 检查通过；C++ suite 44/44 与原有 full 回归通过。
> 新发现并修复的问题位于 FORCE 内部，不是外部 PTG。下一项为 M2 第 2 项 CSR/fence
> 序列；完整 Mapper/自动生成模板、非恒等页表 backing、通用 RAM 声明接入仍未完成。
> 证据及限制见下文“真实分配与隔离 ISS”。仍未安装、未提交、未推送。
>
> 2026-09-06 首轮增量（历史，状态由上段覆盖）：在 FORCE `97e01c3` 工作区保留全部既有改动，以已验收隔离 Handcar
> 运行 quick 基线后，开始 M2 第 1 项。`SetupFullTranslation()` 已有显式 VS/G 映射请求
> 协调、逐 granule PA 更新、冲突预检及失败保护；新增 12 项 C++ 定向测试通过。
> 修改后 full 通过，C++ suite 43/43 通过。分配环节在新单测中使用替身，尚未验收真实
> 内部分配器生成的完整 guest 页表，因此 M2 第 1 项仍为部分实现，不能跳过其剩余工作。
> 本轮未安装、未提交、未推送；详细边界和证据见下文 M2 进度。

> 2026-09-05 增量：Handcar 已移植到官方 Spike
> `4ffd6ba860f4190ceac2716fa3c2cf139e85538f`。使用版本化 pin + patch 的正式工具从
> 干净源码冷构建并通过 106/106 M1、990/990 generation 和 990/990 ISS，含局部 ASan。
> 默认安装库未替换，用户选择保留隔离版；不是完整 Hypervisor/多 hart/全部 ABI 验收。
> 最新库哈希、原始证据和限定合同以
> [Handcar 上游迁移状态](../HANDCAR_UPSTREAM_REBASE_STATUS.md) 为准。
> 新任务先读 [Hypervisor 快速上手](../HYPERVISOR_QUICKSTART.md)。以下旧日期段落保留历史。

> 2026-08-15 增量更新：PTG Fault Injection V2 已通过 native 验收，并完成 FORCE ctypes
> 集成及 S/VS/G direct、guest-implicit、guest-explicit 的真实 Handcar trap 核心矩阵。
> 2026-08-16 增量更新：causes 2-9 的 S/U/VS/VU/G-stage 矩阵及 ctypes 负向状态矩阵完成。
> 2026-08-25 增量更新：C++ unit runner 已传播失败退出码；受控失败返回 1、真实 42/42
> 通过。Fault V2 runner 也会将启动它的 Python 解释器目录置于子进程 PATH 首位，避免
> `forrest_run.py` 通过 shebang 误选不兼容的 Python。
> 2026-08-27 增量更新：HLV.D、HSV.D、HLVX.WU 的 4 KiB 强断言矩阵，以及 HLV.D 的
> 2 MiB/1 GiB 哨兵场景通过三组固定 seed。HSV.D 结果同时由 HLV.D 和 M-mode 物理地址
> LD 验证；1 GiB 场景观测到 GVA `0x40123450` 到 SPA `0x100123450` 的真实访存轨迹。
> HLV.D 跨 4 KiB 页访问及 VS 4 KiB/G 2 MiB、VS 2 MiB/G 4 KiB 组合也通过三组 seed。
> Handcar `hvip` 名称映射源码已修正；`build_v2.sh` 已在隔离目录重建修复版
> `handcar_cosim.so`，并以该库完成 CSR/HLV/HSV 三 seed 和 HLV.D seed `1..100` 验收。
> 仓库内已安装的既有脏 `.so` 未被覆盖，安装修复版仍待显式确认。
> HLV.D/HSV.D 的 VS-stage page fault 与 G-stage guest-page fault 也已用 L0 V=0 leaf 完成
> 三组固定 seed 强断言，覆盖 causes `13/15/21/23`、trap CSR、精确 PTE mutation 和无副作用。
> 详细能力、边界和后续工作见
> [PTG Fault Injection V2 FORCE Integration Status](../PTG_FAULT_INJECTION_V2_FORCE_STATUS.md)。

## 1. 结论

Hypervisor/PTG 已完成主要数据结构、指令定义、CSR 基础和测试模板，但尚未达到
“完整 Hypervisor 支持”的验收标准。

当前最重要的事实是：

- FORCE 基础构建通过，42/42 个现有 C++ 单元测试通过。
- PTG 软件侧可以创建两阶段上下文、生成页表并执行软件翻译。
- Handcar 已完成 HLV.D、HSV.D、HLVX.WU 的 GVA→GPA→SPA→数据闭环；HLV.D 页尺寸、
  跨页和混合页尺寸矩阵已通过 seed `1..100`。
- Handcar CSR 名称表中的 `hvip` 覆盖错误已在源码修复；隔离重建库已证明 `hvip=0x645`
  端到端全绿，旧安装二进制仍可稳定复现错误映射且未被覆盖。
- 旧有 29 个根目录 PTG 测试仍未接入正式回归；Fault V2 核心矩阵已单独接入专项
  `_fctrl.py` 和统一回归入口。
- 29 个 PTG 测试中只有 2 个包含强失败机制；其余测试打印 FAIL 后仍可能退出 0。

因此当前成熟度应定义为：**M1 限定范围与自动化入口已闭环，完整 Hypervisor 支持仍未闭环**。
M2 PTG-backed Mapper 集成、其他指令/异常语义及多 hart 等工作仍按下文推进。

### 1.1 2026-08-16 Fault V2 状态增量

上述结论保留 2026-07-16 的全局 Hypervisor 基线。此后 Fault Injection 子系统已经取得
以下可独立验收的进展：

- PTG `1cdf841` 通过第四轮 native 验收，独立复现六项计数全部为 0。
- FORCE 已接入 V2 ctypes ABI、two-call 协议、dry-run/commit 和结果记录校验。
- V2 ctypes 负向矩阵覆盖 invalid argument、unsupported combination、exact target miss、
  unsuitable target 和 insufficient candidates；dry-run/commit 均断言页表不变，8/8 通过。
- S/VS/G direct 及 guest-implicit/guest-explicit 的真实 trap 矩阵通过；guest-implicit 覆盖全部
  VS walk/G target level 对，VS L0/L1 覆盖全访问，VS L2 覆盖可达的 execute 路径。
- Guest-explicit execute/load/store 在 G target level 0/1/2 均完成 GVA/GPA 双 dry-run result
  parity、两种 request commit 及真实 Handcar trap，除 `requested_address` 外的结果字段必须
  完全一致。
- 真实 CSR 强断言覆盖 `mcause/mepc/mtval/mtval2/mtinst/mstatus`。
- 专项入口以固定 seed 集 `0x15c0ffee/0x5eed1234/0xc001d00d` 完成 990/990 generation、
  990/990 ISS，并检查每个 `regression_summary.log` 的 generation/ISS 数量与失败数。
- Causes 2-9 已完成 S-stage S/U、VS-stage VS/VU、G-stage VS、execute/read/write 和全部 Sv39
  合法 target level，逐项强断言 PTE mutation、单槽修改、stage tree 隔离及
  `mcause/mepc/mtval/mtval2/mtinst/mstatus`。
- 三组 seed 的 900 份 S/U/VS/VU/G-stage cause/access/level `sim.log` 已逐份直接审计，300
  个 execute、300 个 load、300 个 store 场景全部观测到预期 fault 指令、trap CSR 值和
  Handcar 成功退出；G-stage 观测到 `mcause=20/21/23` 和精确 `mtval2=GPA>>2`，VU 路径
  额外观测到 VS trampoline 的 `sepc` 设置和 `sstatus.SPP` 清零。
- 三组 seed 的 63 份 guest-implicit level/access `sim.log` 已逐份审计，27 个 execute、18 个
  load、18 个 store 均观测到精确 VS PTE GPA 对应的 `mtval2` 和 `mtinst=0x3000`。VS root
  load/store 会被同一 root 页的更早 instruction fetch fault 遮蔽，因此不作为可达场景。
- 三组 seed 的 18 份 guest-explicit GVA/GPA/level `sim.log` 已逐份审计，54/54 个
  access/address-kind/level 场景通过；成对结果解析到相同 GPA、`pte_pa` 和 old/new PTE。

这关闭了“Guest fault 只有 PTG 返回码、没有真实 Handcar trap”的子项，但不代表委托、
Virtual Instruction、HLV/HSV 全指令语义、nested trap 或完整 Hypervisor 支持已经完成。

## 2. 状态判定规则

本文使用以下状态：

- **已实现**：代码存在，并且有自动化强断言验证关键语义。
- **部分实现**：接口、数据结构或测试外壳存在，但缺少真实执行、强断言或完整覆盖。
- **未实现**：计划目标对应的核心逻辑或测试不存在。
- **阻塞**：其他功能的可信验证必须先解决的问题。

仅满足以下条件不能判定为已实现：

- 指令能够生成。
- CSR 可以写入再读回。
- PTG 自身的 `translate_sequential()` 返回正确。
- 日志中打印 PASS。
- 进程退出码为 0，但测试没有强断言。

## 3. 当前实现矩阵

| 领域 | 状态 | 已有内容 | 尚缺内容 |
|---|---|---|---|
| 基础构建 | 已实现 | `make -j4` 通过；42 个既有 C++ 单元测试通过；unit runner 失败返回非零；Fault V2 runner 保持父子进程 Python 一致 | 构建仍需显式选择 Python 3.12；继续修复旧 PTG 测试假绿 |
| 分页枚举/XML | 已实现 | Sv39x4、Sv48x4、Guest Page Fault 枚举和分页 XML | Sv57x4 的 FORCE 内部完整路径仍需专项验证 |
| PTG ctypes 后端 | 已实现（Fault V2） | V2 request/result/VM config ABI、two-call、dry-run/commit、状态与 guard；负向状态及无 mutation 断言在内的独立 ctypes 8/8 通过，并作为专项回归生成前 ABI preflight | PTG 公共接口尚无 semantic-mismatch/apply-failure 测试 hook；继续扩展 cause 10-12 与跨 stage/access/control 覆盖 |
| FORCE 两阶段 Mapper | 部分实现 | `TwoStageVmMapper` 可串联两次翻译 | 多个接口只转发 VS-stage；缺少专用单元测试 |
| TwoStageTranslationUnit | 部分实现 | 显式 VS/G 映射及 VS 页表恒等 backing 已通过真实分配、内存 walk 和 102 seeds 隔离 HLV/HSV；12 项协调器单测保留 | `GenerateSetupInstructions()` 仍为空实现；非恒等页表 backing、通用 RAM 声明及模板接入未完成 |
| G-stage AddressSpace | 部分实现 | x4 根表 16 KiB、unsigned GPA 范围及跨 stage 根表 alias 拒绝已接入；Sv39x4 高 GPA native/ISS 验证通过 | G-stage 专用约束函数仍为空壳；通用 U-bit/helper、VMID 隔离和其他模式仍需核验 |
| Handcar 两阶段执行 | 部分实现 | 普通 VS execute/load/store、G-stage fault、HLV.D、HSV.D 和 HLVX.WU 的真实执行矩阵通过；4 KiB/2 MiB/1 GiB、跨页和混合页尺寸成功路径已覆盖；隔离修复版 Handcar 的 HLV.D 矩阵 100 seed 通过；HLV.D/HSV.D 的 VS/G L0 invalid leaf trap 通过 | 经确认后安装已验收的 Handcar 二进制，并扩展其他 PTE fault 类型和层级 |
| Hypervisor 指令定义 | 部分实现 | XML/树中已有 HFENCE、HINVAL、HLV、HLVX、HSV 共 17 条；HLV.D、HSV.D、HLVX.WU 有成功路径强断言，HLV.D/HSV.D 有 L0 invalid leaf 异常强断言 | 缺少逐条语义矩阵；其他尺寸、异常类型及 HFENCE/HINVAL 语义尚未完成 |
| Hypervisor CSR | 部分实现 | hstatus、hedeleg、hideleg、hgatp、hvip、htimedelta、vscounteren 等已定义；hvip reset、CSR choice 和 Handcar 名称映射源码已修正，隔离重建库的 hvip 语义断言通过 | 安装已验收的 Handcar 修复版；hstateen0-3、vsstateen0-3、hvipr1-12 缺失；部分字段/WPRI 行为未验证 |
| Guest 异常 | 部分实现 | 真实指令已覆盖 12/13/15/20/21/23；S/VS/G direct 与 guest implicit/explicit 均有 CSR 强断言；guest implicit 已覆盖全部 VS/G level 对；causes 2-9 已覆盖 S-stage S/U、VS-stage VS/VU 和 G-stage VS 全访问、Sv39 全层级 | Virtual Instruction 22、HS/VS 委托、nested trap、xRET 返回链与 cause 10-12 尚未完成 |
| VS 虚拟中断 | 未实现 | hideleg/hvip CSR 定义和读写测试 | VS software/timer/external 触发、委托、handler 进入与返回均无语义测试 |
| HS/VS/VU 特权切换 | 部分实现 | Solver 读取 SPV/SPVP/virtual 字段；Fault V2 已真实执行 MRET→VS trampoline→SRET→VU 入链 | 完整 M↔HS↔VS↔VU 往返、异常返回和状态恢复仍未验证 |
| VMID | 部分实现 | per-GenThread 分配/释放 API；PTG 上下文可编码 VMID | 未证明 Handcar TLB/地址空间隔离；跨 Hart/迁移语义未验证 |
| 多 Hart | 未实现 | API 形参中存在 `hart_id` | 两阶段分支实际未按 `hart_id` 写目标 Hart；无 2/4/8 Hart 测试 |
| Stress | 部分实现 | 10K mapping、500 ASID switch、1000 VM switch 测试代码存在 | 主要验证 PTG 软件翻译；无强断言、无实际访存、无性能门槛 |
| 正式回归 | 部分实现 | Fault V2 专用 `_fctrl.py` 每 seed 330 个任务；三组固定 seed 共 990/990 generation 和 ISS 通过，失败退出和 ELF/S/log 独立归档已验证 | 仓库无项目 CI 配置；外部 CI 尚未挂接；旧 PTG 测试仍未纳入 |

## 4. 已确认的问题

### 4.1 P1：HLV/HSV 成功路径验收完成，异常矩阵待完成

强断言测试：`tests/riscv/ptg_two_stage_fixed_force.py` 和
`tests/riscv/ptg_hypervisor_access_matrix_force.py`、
`tests/riscv/ptg_hypervisor_fault_matrix_force.py`

2026-07-16 基线曾得到：

```text
expected: 0xDEADBEEFCAFE1234
actual:   0x0000000000000050
```

该结果由测试权限模型和执行上下文配置错误造成，不是 Handcar 数据后端错误。2026-08-27
重新验收后，2 MiB HLV.D 哨兵值稳定读回 `0xDEADBEEFCAFE1234`；1 GiB VS/G level-2 leaf
场景将 GVA `0x40123450` 翻译到 SPA `0x100123450`，并稳定读回
`0x0123456789ABCDEF`；4 KiB 矩阵验证了 HLV.D、HSV.D 后 HLV.D 回读、M-mode 物理地址
LD 和 HLVX.WU。三组固定 seed 均通过，G-stage walk 显示 `levels=3` 和非 Bare
`ptbase`。跨页 HLV.D 日志显示访问被拆分到相邻的两个 4 KiB VS/G leaf；VS 4 KiB/G
2 MiB 和 VS 2 MiB/G 4 KiB 两种组合均读回独立哨兵。修复测试消费点前的 x1/x8
装载后，seed `1..100` 全部观测到五个预期寄存器哨兵、六条预期物理访存轨迹和
`Executed 34 instructions, exit status (SUCCESS)`。修复版 Handcar 隔离库也完成同一组
seed `1..100` 复验，审计产物位于 `/tmp/opencode/handcar-fixed-two-stage-100`。

同日新增的 HLV/HSV fault 矩阵通过 seed `1`、`0xdeadbeef`、`0x123456789`：Fault V2
分别精确清除四个 VS/G L0 leaf 的 V 位，并独立 walk 验证目标 `pte_pa`、仅目标 8 字节
发生变化且另一 stage 不变。真实 HLV.D/HSV.D 分别观测到 `mcause=13/15/21/23`、精确
`mepc/mtval`、G-stage 的 `mtval2=GPA>>2`、`mtinst=0` 及 M-mode trap 后的
`MPP=M/MPV=0/GVA=1`；HLV 目的寄存器和 HSV 目标 SPA 均保持原哨兵。三份 `sim.log`
也确认 fault instruction 直接跳到对应 `mtvec` handler。修复版 Handcar 的复验产物位于
`/tmp/opencode/handcar-fixed-fault-*`。该矩阵只关闭 L0 V=0 leaf 场景，其他 PTE fault
类型、层级和 HLV/HSV 尺寸仍待扩展。

### 4.2 P0：Handcar CSR 名称映射错误

2026-09-05 状态：本项在隔离候选上已解决。新版采用 `handcar/upstream.lock.json` 与
`handcar/tools/upstream.py`，不再依赖被忽略的 `build_v2.sh` 或旧 generated 源码。
下面描述旧问题定位过程，不表示需要继续覆盖旧安装库才能开展 M2。

`handcar/standalone-v2/spike_main/spike_lib.cc` 先将 `hvip` 映射到 `0x645`，随后又映射到
`0x600`，后一次赋值会覆盖正确值。源码中的重复 `hgeie`、`hip`、`hie` 和错误 `hvip`
条目已删除；RV64 `hvip` 物理寄存器 reset 和 system-register choice 也已补齐。隔离单元
测试确认源码映射为 `hvip=0x645`、`hie=0x604`、`hip=0x644`、`hgeie=0x607`。仓库中
已有未提交修改的安装二进制未被覆盖。

隔离重建进一步确认此前的 `_Z18fast_rv32e_mop_r_4P11processor_t6insn_tm` 链接错误来自
Spike generation 错配：源树 `insn_list.h` 声明具体 `mop_r_4`，configure 生成列表及对象
只提供通用 `mop_r_N`。`handcar/build_v2.sh` 现将 generated `processor.cc` 与同一 build 的
`insn_list.h` 成对编译，并在链接后只允许 FORCE 提供的 `update_generator_memory` 和
`update_generator_register` 两个强 undefined callback；其他未解析符号会使构建失败。
隔离产物 `/tmp/opencode/handcar-build-v2-hvip-fixed/handcar_cosim.so` 的 SHA-256 为
`f57ccfbb3de95a9da8df62c051f5ee6cf31c4601a7a12470dc7d9b75a8a93081`，不含
`mop_r_4` 且定义 `mop_r_N`。该库经临时配置实际加载后，三组固定 seed 的 HLV.D、HSV.D、
HLVX.WU 和 `hvip=0x645` 语义矩阵全部通过，HLV/HSV fault 矩阵三组 seed 通过，two-stage
成功路径 seed `1..100` 通过。仓库安装 `.so` 仍保持原样，待显式确认后再替换。

### 4.3 P0：旧 PTG 测试仍可能假绿

`utils/regression/unit_tests.py` 固定 `sys.exit(0)` 的问题已于 2026-08-25 修复。受控失败
夹具确认返回 1，真实 C++ unit suite 42/42 通过并返回 0。

多数旧版 PTG 测试只调用 `notice("FAIL")`，没有 `self.error()`、异常或断言。例如：

- Guest fault 场景
- nested/double fault 场景
- VMID 隔离
- 10K mappings
- ASID/VM context switch
- CSR 和 privilege 测试

### 4.4 P1：核心 C++ 类仍有空实现

- `TwoStageTranslationUnit::SetupFullTranslation()` 的真实映射创建及恒等页表 backing 已按
  限定合同验收；非恒等页表 backing 和通用宿主 RAM-range 接口仍未闭环。
- `TwoStageTranslationUnit::GenerateSetupInstructions()` 没有生成任何指令。
- `VmGpaAddressSpace::SetupGStageConstraints()` 只打印日志。
- `TwoStageVmMapper` 多个查询和约束接口只转发 VS-stage，不能表达完整两阶段状态。

### 4.5 P1：测试名称大于实际覆盖

- `ptg_hs_vs_switch_force.py` 只测试 hstatus.SPV/SPVP 读写。
- `ptg_hedeleg_hideleg_force.py` 对中断只检查 CSR bit，并注明“CSR verification only”。
- nested exception 测试使用 PTG fault API并打印“would enter VS trap handler”，没有执行真实 trap。
- VM switch/ASID stress 使用 PTG 软件翻译判断结果，不是 Handcar 中的实际访存。

## 5. 新实施计划

### Milestone 0：建立可信测试基线（P0，2-3 天）

目标：任何 FAIL 都必须使命令返回非零，后续状态可以被自动判定。

工作项：

1. 修复 `unit_tests.py`，失败数大于 0 时退出非零。
2. 扩展现有 Fault V2 `_fctrl.py`，逐步纳入其他稳定的离线 PTG 测试和端到端基线。
3. 给现有测试增加统一断言辅助函数，逐步替换 `notice("FAIL")`。
4. 扩展已固定的三组端到端 seed，并保持每个 seed 和模板的生成目录隔离。
5. 固化 Python 3.12、编译器、`PTG_LIB_PATH` 环境检查。
6. 区分三类测试标签：`ptg-unit`、`force-generation`、`handcar-semantic`。

验收标准：

- [x] 人为制造一个失败，单元测试脚本返回非零。
- [x] Fault V2 回归控制文件能执行并汇总测试，且任务失败会转换为非零退出。
- [x] 当前纳入 Fault V2 专项回归的测试都包含强断言。
- [x] 基础 smoke 和 42 个 C++ 单元测试继续通过。

### Milestone 1：修复 Handcar 两阶段数据路径（P0，5-8 天）

目标：完成 GVA→GPA→SPA→数据的端到端闭环。

工作项：

1. 修复 Handcar `hvip` CSR 映射覆盖问题并扫描全部 CSR 重复映射。
2. 跟踪 hgatp CSRRW 后的 MODE、VMID、PPN 和 MMU `levels/ptbase`。
3. 核对 FORCE sparse memory、Spike DRAM/MMIO 与 HLV load 使用的存储后端。
4. 验证 VS 页表节点 GPA 经 G-stage 后写入的 SPA 与读取地址一致。
5. 修复 HLV.D 哨兵读取。
6. 增加 HSV.D 写入后物理内存/HLV.D 回读测试。
7. 增加 4KB、2MB、1GB 页和跨页边界测试。

验收标准：

- [x] HLV.D 稳定读取哨兵值，固定 seed `1..100` 全过并完成逐日志审计。
- [x] G-stage 日志显示正确 `levels` 和 `ptbase`，不再退化为 Bare。
- [x] HSV.D 写入可由物理读和 HLV.D 回读同时验证。
- [x] 4 KiB、2 MiB 和 1 GiB 成功路径均有真实 Handcar 访存与数据强断言。
- [x] 跨 4 KiB 页和 VS/G 不同页尺寸组合均有真实访存与数据强断言。
- [x] HLV.D/HSV.D 的非法 VS/G L0 leaf 分别产生预期 fault，且无寄存器/内存副作用。

### Milestone 2：以 PTG 后端集成 FORCE Hypervisor（P1，工期重新评估）

目标：让 FORCE 的映射、查询、上下文和执行准备由 PTG 后端一致驱动，而不只是测试模板
手工配置 PTG/Handcar；不在 FORCE 重复实现页表构造、walk 或故障注入算法。

工作项（用户确认路线后的当前顺序）：

1. 盘点现有 PTG C/ctypes 接口，定义 handle/context 生命周期、GVA/GPA/SPA、地址分配
   所有权及失败语义；能力缺口形成文档，不默认转回 native 生成器。
2. 接通可信 PTG 导出和 FORCE/Handcar 内存同步，写入失败必须抛出；预留地址避免与
   FORCE 分配冲突，明确 snapshot/dirty 更新、故障页表导出与 RAM/MMIO 边界。
3. 实现 PTG-backed Mapper adapter：正向/反向映射、page info、translation range、权限、
   上下文及约束查询从 PTG 获得；优先接现有 API，不足再向 PTG 提出需求。
4. 从 PTG 返回的 CSR/root/context 值生成 vsatp/hgatp/hstatus 和 fence 序列，验证真实
   指令与模板接入；避免 FORCE 自有根表或 CSR 更新覆盖 PTG 上下文。
5. 对新增映射、重映射、权限/fault mutation、A/D 写回、上下文切换建立一致性测试，
   独立 Handcar 断言验证 PTG adapter 行为，而非用 PTG 自身结果作为唯一 oracle。
6. 持续执行“FORCE 用例 → PTG 需求/bug 文档 → 用户转交 → PTG 修复 → FORCE 独立
   验收”流程；记录接受的版本、库哈希和不支持范围，不擅自修改外部 PTG 仓库。

验收标准：

- [ ] PTG adapter 单元测试覆盖正向、反向、缺页、权限、superpage 和失败传播。
- [ ] FORCE 内部映射状态、PTG 导出及 Handcar 实际访存一致；错误不能被空结果或后端回退掩盖。
- [ ] 模板通过 PTG-backed Mapper 自动生成并使用两阶段页表，不手写 PTE，也不构造另一套 native 根表。
- [ ] PTG 外部需求与 bug 均可追溯到版本、复现、用户转交状态和独立验收结果。

PTG-first 首轮进度：已盘点公共 C API，修复 FORCE 导出错误/ctypes writer 异常传播，
11/11 ctypes 和原有 full 回归通过，证据为
`output/ptg-first-integration/full-_0pto9vu/workflow.json`。已独立复现 VS 导出失败后
回退 GPA 的旧 API 风险，形成待用户转交的 R001 严格导出需求。地址池/查询合同仍待进一步
核对，PTG-backed C++ Mapper 尚未接通；继续从上面第 1/2 项推进，不回到 native 路线。

PTG-first 查询阶段增量：已接入已有 `ptg_mapping_find_pa/find_vas`，仅作为明确标记的
诊断索引，不作为有效地址/权限 oracle。15/15 ctypes、原有 full 通过，证据为
`output/ptg-query-integration/full-jkp9icg4/workflow.json`。纯 C ABI 和 raw PTE 复现发现
Clear 与页内 remap 后索引不同步（B001/B002），以及 PA=0、页内 range/metadata 查询合同
缺口（R002），详见[查询合同报告](../PTG_MAPPING_QUERY_CONTRACT_REPORT.md)。三项均待
用户转交维护者，不能以 FORCE 影子映射表补洞；地址所有权 A001 和 void 错误处理 A003
继续核对，R001 导出需求仍开放。上述 M2 验收框继续保持未完成。

**2026-09-19 候选验收增量：** 用户转交后，PTG 提供了索引同步修复、Mapping Query v1
和 Strict Export v1，实际共享库哈希 `8a56c462...` 与回函一致。FORCE 独立 19/19 新合同
检查、新严格导出产物的 9 条 Handcar 指令以及原有 106/990 full 回归通过。B001/B002
修复已验收，R001/R002 的新 API 交付可接受，详见[验收反馈](../PTG_MAPPING_EXPORT_V1_ACCEPTANCE_FEEDBACK.md)。
PTG stress 仍有两项已披露失败，不宣称全局全绿。生产 `PtgBackend` 尚未绑定新合同，
下一步按第 2/3 项将 legacy callback/index 路径迁移到新接口，正确处理 current/logical、
结构元数据与权限、冻结 placement 与 stale；A001/A003 继续开放，不回退 native 后端。

**2026-09-19 首批生产适配增量：** `PtgBackend.py` 已正式封装 Query/Strict Export v1，
提供独立状态异常、调用者拥有的查询结果和受控 layout 生命周期；能力缺失/stale 均明确
失败，不重建、不回退。已迁移 fixed/access 正常访存模板及 guest-scope 共享装载路径，
在健康时 capture、故障注入后 pull 当前 bytes 到冻结 SPA。32/32 ctypes、独立 19/19
合同检查、106/106 M1 和 990/990 generation/ISS 通过，证据为
`output/ptg-v1-production/full-isp_35fv/workflow.json`。后续预检诊断修复经
`quick-erj9n5oo` 验证，未改写 full 记录。详细 API、覆盖数量和边界见
[生产适配说明](../PTG_V1_PRODUCTION_INTEGRATION.md)。第 2/3 项仍未整体完成：其余 legacy
装载、A001 宿主池所有权、PTG-backed C++ Mapper 和生成器约束尚待接通。

**2026-09-20 A001 首期增量：** 新增 FORCE 预留的 PTG 专用池，锁内选择可用 PA 并预留，
严格装载检查原 writer/bank 与 SPA 边界，PTG 销毁不提前释放 reservation。已迁移 M1
access 模板，40/40 ctypes、独立 19/19、106 M1、990 generation/ISS 及三 seed 真实
reservation 合同检查通过。证据与 API 见[地址池适配](../PTG_RESERVED_POOL_INTEGRATION.md)。
独立复现 PTG 根表对齐和容量失败问题 B003/B004，形成
[分配器报告与 R003](../PTG_ALLOCATOR_ALIGNMENT_EXHAUSTION_REPORT.md)，待用户转交维护者。
当前仅新 handle 的单 VS/G context 专用池，A001 的通用分配、回收和 MMIO/数据所有权
没有关闭；不通过 FORCE 自行补齐 PTG allocator padding 扩展该限制。

**Checked-allocation 回函验收增量：** 最新 `dfee221f...` 候选已复验 B003/B004 修复，
R003 的串行 checked allocation/placement API 可接受。39 项独立下游检查、placement
产物的九条 Handcar 指令、三 seed 实际 owned-pool 与原有 full 均通过：
`output/ptg-allocation-acceptance/full-f7y3alcy/workflow.json`。详细证据、开发期测试
前提修正和仍有两项失败的 stress 边界见
[验收反馈](../PTG_ALLOCATION_PLACEMENT_ACCEPTANCE_FEEDBACK.md)。本轮不改变生产
wrapper/池限制；下一步正式绑定 placement v1，再在宿主所有权与生命周期合同下评估
更多 context/stage 配置。stage 失败原子性不等于增量 mapping/backfill 全局回滚。

以下两节保留此前 native 实验原始过程；其中“下一工作项”和“第 1 项验收”只适用于
已停止扩展的旧路线，不覆盖上面的当前顺序。

#### 2026-09-06 第 1 项首轮进度（历史）

本次实现限定为在同一 Generator 已准备好的两个地址空间中建立连续映射请求：

- 先预检两个 stage 的整段范围，拒绝零长度、溢出、低 12 位 offset 不一致、地址越界、
  address-error Page 和已有地址映射冲突；预检失败不改变原映射或 enable 状态。
- 按 G-stage `GPA→HPA`、VS-stage `GVA→GPA` 的顺序执行，每个 4 KiB granule 更新 PA。
  分配期间关闭自动串联，避开旧 `MapAddressRange()` 将 GVA 当 GPA 的路径。
- 新请求明确 VS supervisor / G user-accessible、V/A/D、读写或读执行属性和非 global；
  已有 leaf 只做地址一致性检查，不更改或宣称已验证其访问权限。
- `VmAddressSpace::CreatePage()` 在物理分配之前拒绝指定 PA 与所选页尺寸 offset 不一致，
  允许原 page-size 选择器回退到可兼容的较小页。
- 不把 `MapAddressRange()` 的 false 当失败，因为它表示没有新分配；返回后检查实际 Page。
  全段成功才 enable；分配中途失败会保留已提交页供诊断、清除旧 cache 并保持 composition
  disabled，`ValidateTranslationChain()` 不再把这种单 stage 状态报成成功。

定向测试：`unit_tests/tests/riscv/TwoStageTranslationUnit/TwoStageTranslationUnit_test.cc`。
12 项覆盖非恒等跨三 granule 映射、指令请求、重复创建、已有混合尺寸 superpage、两 stage
后部冲突、原链保留、非法参数、地址错误和分配故障。测试替换 `MapAddressRange()` 的分配
行为，使用真实 `GenPageRequest`、Page 查找与 `VmAddressSpaceRISCV` 组合/cache 翻译；另有
真实 `CreatePage()` 的分配前 offset 拒绝检查。它不是 native 页表 walk 或 Handcar 语义测试。

本机证据均在仓库根目录 `output/hypervisor-m2-entry/` 下：

| 验证 | 证据 | 结果 |
| --- | --- | --- |
| 修改前 quick | `quick-afic79av/workflow.json` | 145 工具单测、预检、3 smoke，rc=0 |
| 定向 C++ 构建/执行 | `unit-build-final.log`、`unit-final.log` | 12/12，含 `PICKY=1` 编译 |
| 完整 C++ suite | `cpp-units.log` | 43/43，rc=0，包含新测试模块 |
| 修改后 full | `full-4ggnyfiy/workflow.json` | 145 工具单测、预检、3 smoke、106 M1、990 generation/ISS，rc=0 |
| M1 原始归档 | `full-4ggnyfiy/m1/m1-2atmvffr` | 106/106，生成期逐指令审计 |
| Fault V2 原始归档 | `full-4ggnyfiy/fault_v2/run_ywxv9fo7` | ctypes 8/8、默认三 seed、990/990 两执行阶段 |

Handcar/PTG 绝对路径、哈希与配置在上述 workflow 中，库身份见
[迁移状态](../HANDCAR_UPSTREAM_REBASE_STATUS.md)。旧失败开发日志原样保留，不作为通过证据。
上述 M1/Fault V2 验证的是原有 PTG/Handcar 路径无回归，不是新协调器的端到端验收。

首轮交接要求（已由下面的后续增量推进）：建立使用真实 VS/HS control block、物理分配器和
内存写入的 C++ fixture，验证实际 leaf/table descriptor 及 GPA/SPA 隔离。当前 VS 页表
节点仍由通用宿主物理分配/`WriteDescriptor()` 路径管理，须明确节点 GPA 经 G-stage 后
对应的 SPA，并接入宿主 RAM-range 声明或显式初始化；不能把任意 CPU store 自动建 RAM
作为修复。之后才可升级“不依赖手写 PTE 的可执行页表”状态。CSR/fence 序列、完整 G-stage
约束、反向/权限语义、PTG 同输入比对及生产调用入口仍属于后续未完成工作。

定向命令（在仓库根目录 Bash 中；Python 3.12 与现有构建 ABI 一致）：

```bash
source ./setenv.bash
export PYTHONDONTWRITEBYTECODE=1 FORCE_CC=g++ FORCE_PYTHON_VER=3.12
export FORCE_PYTHON_INC="$(python3.12 -c 'import sysconfig; print(sysconfig.get_path("include"))')"
export FORCE_PYTHON_LIB="$(python3.12 -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')"
make -C unit_tests/tests/riscv/TwoStageTranslationUnit -j4 PICKY=1
unit_tests/tests/riscv/TwoStageTranslationUnit/bin/TwoStageTranslationUnit_test -p
```

此 Makefile 定向构建 FORCE `bin/friscv` 并链接其对象，另用 UNIT_TEST 版 Logger 将 FAIL
转为可断言异常；不调用 `riscv all`、不构建/安装 Handcar、不清理 output。它也已由
`utils/regression/unit_tests.py` 自动发现。构建应先完成，再运行 quick/m1/full。

#### 2026-09-06 真实分配与隔离 ISS

新增 `unit_tests/tests/riscv/TwoStageAllocation/`，不使用分配替身或手写 PTE：创建真实
Generator、VS/HS control block 和 address space，调用生产分配/`WriteDescriptor()` 路径。
单元测试默认 `--noiss`，只检查 native 模型；显式提供 `FORCE_M2_HANDCAR_SO` 后另行
加载该候选，将 FORCE 页表内存复制为宿主初始化的 RAM，执行独立 ISS 检查。

本轮确认的问题均属于 **FORCE**，没有确认新的外部 **PTG** bug：

- `VmasControlBlockHS` 原先使用普通 Sv39 的 4 KiB 根表和 signed VA 范围；现在根索引
  增加两位，根表大小/对齐为 16 KiB，低层表保持 4 KiB，GPA 使用 unsigned 范围。
  实测验证 Sv39x4 的 GPA bit 40、`2^41-1` 上界以及 `2^41`/全 1 地址拒绝。
- `VmAddressSpace::CompatiblePageTableContext()` 原来恒为 true；现在拒绝不同 stage
  或不同 control block 类型的根表 alias。没有因此宣称同 stage VMID/ASID 隔离完成。
- 数据 leaf 已建成时，真实 guest walk 仍因 VS 页表节点缺少 G-stage backing 而失败。
  `SetupFullTranslation()` 现在把 VS PageTable constraint 中的节点按 GPA=SPA 恒等映射，
  要求 U/R/W/A/D/V，并检查实际 PA 和 memory bank。冲突会失败，不覆盖既有映射、不搬迁节点。

已验证的 native 场景为非恒等 GVA/GPA/SPA 跨三个 4 KiB granule、GPA bit 40、双 stage
2 MiB leaf，以及 VS 页表 backing 重映射拒绝。独立 walk 直接读取 FORCE 内存字节，
对每个 VS PTE 地址也执行 G-stage walk，检查非 leaf 保留位、leaf 权限和 superpage 对齐。

隔离 ISS 对三个映射分别执行 HLV.D、HSV.D、HLV.D，断言 PC 无意外 trap、前后寄存器
哨兵以及目标 SPA 物理读回；两个访问在页内 offset `0xffc`，跨越 4 KiB 边界。再执行
一个 M-mode SD 到未声明 RAM，断言 cause 7、mepc、mtval 且不能物理读回，证明没有把
未知 CPU store 改成自动创建 backing。页表和数据均由宿主显式初始化，回调不反馈到 FORCE。
这是 native 模型的独立 ISS 消费测试，不是 Python 模板生成、CSR 序列生成或完整 ELF 重放。

证据根目录为 `output/hypervisor-m2-native/`：

| 验证 | 证据 | 结果 |
| --- | --- | --- |
| 原根表大小错误 | `run-1.log` | `Sv39x4 root must be 16 KiB` |
| 原 backing 缺失 | `run-3.log` | 独立 guest walk 报 `invalid descriptor` |
| 定向构建及协调器 | `build-final.log`、`coordinator-build.log`、`coordinator.log` | 构建通过、原 12/12 单测通过 |
| native + 候选 ISS | `batch2-seed-*.log` | `1..100`、`0xdeadbeef`、`0x123456789` 共 102/102 seeds，每 seed 9 HLV/HSV + 1 未声明 RAM store 检查 |
| C++ suite | `cpp-units.log` | 44/44，native 模块默认不加载 ISS |
| 原有 full 回归 | `full-0lo3w8qg/workflow.json` | rc=0，145 工具单测、预检、3 smoke、106 M1、990 generation/ISS |
| M1 归档 | `full-0lo3w8qg/m1/m1-jmwucujl` | 106/106，生成期语义审计 |
| Fault V2 归档 | `full-0lo3w8qg/fault_v2/run_0xeuzr6a` | 原 PTG 矩阵无回归，不是新的 PTG 同映射比对 |

首次批量 `seed-*.log` 在 seed 41 因 unit runner 同时重新链接测试二进制而出现
`Permission denied`，未作为完整通过。构建/单元套件结束后，全部种子重新执行到
`batch2-seed-*.log` 并逐文件核对 PASS。失败日志保留；不要并行执行该二进制的链接与测试。
定向测试开启 `PICKY=1`，仅在包含已锁定的 `SimLoader.h` 时局部屏蔽其既有 `-Weffc++`
初始化警告，未修改该 ABI 头或 Handcar lock。

候选 Handcar/PTG 哈希保持原值。此次 FORCE `bin/friscv` SHA-256：
`f20bf18b81c862b3faed4cd99f5b39ddef531a21c85e5616b6e9cf6fc0b769eb`。
native 测试源 SHA-256：`50e171630258def5a5aa993ab2b11aece8e4b71e49ed162bd2bbbcf27108d0ee`；
批量重跑时测试二进制 SHA-256：`3d61d439c39fdb18f64086863d6583815c6a0ce80c421695d7a4456e2d52695b`。
这些 native 日志不是 M1 式不可变输入归档；不同构建产物需要重新执行，不能沿用旧 PASS。

接续上节 Bash/Python 构建环境，独立执行：

```bash
make -C unit_tests/tests/riscv/TwoStageAllocation -j4 PICKY=1
unit_tests/tests/riscv/TwoStageAllocation/bin/TwoStageAllocation_test
FORCE_M2_SEED=1 \
FORCE_M2_HANDCAR_SO="$PWD/output/handcar-pinned-build-v2/handcar_cosim.so" \
  unit_tests/tests/riscv/TwoStageAllocation/bin/TwoStageAllocation_test
```

本阶段只建立 RV64 Sv39/Sv39x4、单 hart 0、页表 GPA=SPA、宿主显式初始化 RAM 的合同。
不支持任意 VS 页表重定位；不代表 GPA/SPA 独立分配池、通用 RAM-range API、live generator
store-only/CBO.ZERO 路径已接通。其他 paging mode、完整权限/反向映射和同 stage VMID
隔离仍需专项验证。下一工作项为 M2 第 2 项 `GenerateSetupInstructions()`；模板入口及
CSR/fence 序列就绪之前，M2 整体验收项仍不勾选。

### Milestone 3：Hypervisor 指令与 CSR 完整性（P1，5-7 天）

目标：从“指令可生成、CSR 可读写”提升到语义验证。

工作项：

1. 为 17 条现有 Hypervisor 指令建立逐条测试矩阵。
2. 验证 HLV/HLVX 的尺寸、符号扩展和 execute permission。
3. 验证 HSV.B/H/W/D 的写掩码和 fault 行为。
4. 验证 HFENCE/HINVAL 的 VMID、ASID、地址选择性失效。
5. 补齐或明确排除 hstateen0-3、vsstateen0-3、hvipr1-12。
6. 完成 vscounteren WPRI 和 henvcfgH 的 RV32/RV64 定义策略。

验收标准：

- [ ] 每条指令至少有成功与异常两个强断言场景。
- [ ] fence 前后可观察到旧/新翻译差异。
- [ ] CSR 清单与目标 H-extension/AIA 范围一致，未支持项有明确范围声明。

### Milestone 4：异常、委托和特权切换（P1，7-10 天）

目标：验证真实 trap 流程，而不是只验证 PTG fault code 或 CSR bit。

工作项：

1. 执行 instruction/load/store Guest Page Fault 和 Virtual Instruction。
2. 验证 mcause/scause/vscause、mtval/stval/vstval、htval、htinst。
3. 验证 hedeleg 设置与清除时分别进入 VS 或 HS/M handler。
4. 实现并验证 nested fault 的真实 handler 链。
5. 扩展 privilege switch，覆盖 M→HS→VS→VU 及反向返回。
6. 验证 MRET/SRET 对 SPV、SPVP、V 和 privilege 内部寄存器的影响。

验收标准：

- [ ] 四类异常均通过真实指令触发并进入预期 handler。
- [ ] 委托开关改变实际 trap 目标。
- [ ] M↔HS↔VS↔VU 完整链可执行并返回原上下文。
- [ ] nested fault 日志和寄存器值由强断言验证。

### Milestone 5：虚拟化中断（P2，5-8 天）

目标：支持 VS software、timer、external 三类中断的注入和委托。

工作项：

1. 实现/接通 hvip→vsip pending 语义。
2. 实现 hideleg 对 10/12/14 中断目标的控制。
3. 验证 htimedelta 与 timer interrupt。
4. 建立 external interrupt 的可控注入入口。
5. 验证 WFI、屏蔽、pending、清除和 xRET。

验收标准：

- [ ] 三类 VS 中断均可独立触发、屏蔽、清除。
- [ ] hideleg 改变实际 handler 目标。
- [ ] 中断处理后能恢复原 VS/VU 执行流。

### Milestone 6：VMID、多 Hart 与 Stress（P2，7-10 天）

目标：在真实 Handcar 执行路径验证隔离、迁移和压力场景。

工作项：

1. 修复 `setupPtgCSRsForHart()`，确保 two-stage 分支真正作用于指定 Hart。
2. 建立 2/4/8 Hart 独立 vsatp/hgatp/VMID 测试。
3. 验证相同 GVA 在不同 VMID/Hart 下映射到不同 SPA。
4. 验证 VMID 回收前后的 HFENCE.GVMA 要求。
5. 将 10K mappings 测试改成强断言，并增加 Handcar 实际抽样访存。
6. 将 500 ASID/1000 VM switch 的软件翻译检查改成真实访存检查。
7. 增加耗时统计和 `<100 ms/switch` 性能门槛。

验收标准：

- [ ] 8 Hart CSR 与地址空间互不污染。
- [ ] VM 迁移前后地址和数据一致。
- [ ] 10K mappings 验证全部映射，Handcar 抽样覆盖边界和多种页尺寸。
- [ ] 1000 次 VM switch 无 fault、无错误数据，并满足性能门槛。

### Milestone 7：回归与发布收口（P2，3-5 天）

目标：形成可重复、可合并、可维护的交付。

工作项：

1. 运行 RV64 主回归、Hypervisor 专项回归和 C++ 单元测试。
2. 至少运行 100 个常规 seed；关键 two-stage/VMID 场景运行 1000 seed。
3. 增加 CI，保存 ELF、S、gen.log、sim.log 失败证据。
4. 移除 PTG 绝对路径，提供显式依赖发现和版本检查。
5. 更新 README/用户指南，删除“退出 0 即完成”的旧口径。
6. 整理工作树中的实验脚本、日志和预编译二进制来源。

验收标准：

- [ ] 主回归相对基线无新增失败。
- [ ] Hypervisor 专项回归全部强断言通过。
- [ ] CI 能从干净 checkout 构建并运行关键测试。
- [ ] 文档中的每个 PASS 都能映射到自动化测试命令。

## 6. 推荐执行顺序与工期

| 顺序 | Milestone | 预计工作量 | 前置依赖 |
|---|---|---:|---|
| 1 | M0 可信测试基线 | 2-3 天 | 无 |
| 2 | M1 Handcar 两阶段数据路径 | 5-8 天 | M0 |
| 3 | M2 PTG-backed Mapper 集成 | 待接口盘点评估 | M1 基线、PTG 合同与能力 |
| 4 | M3 指令与 CSR | 5-7 天 | M1 |
| 5 | M4 异常与特权切换 | 7-10 天 | M1、M3 |
| 6 | M5 虚拟化中断 | 5-8 天 | M3、M4 |
| 7 | M6 VMID/多 Hart/Stress | 7-10 天 | M1、M3 |
| 8 | M7 回归与发布 | 3-5 天 | 全部 |

旧路线的单人串行估算为 **39-59 个工作日**，PTG-first 调整后需依据接口盘点和维护者
反馈重新评估，不能继续作为当前承诺。M2、M3 与部分 M6 可在 M1 稳定后协调推进。

## 7. 当前 Definition of Done

只有同时满足以下条件，才能将 Hypervisor Phase 3 标记为完成：

1. HLV/HSV 端到端数据正确，不只是无异常执行。
2. VS/G fault、委托、中断和 xRET 都由真实 Handcar 执行验证。
3. M/HS/VS/VU 状态链和多 Hart/VMID 隔离有强断言。
4. 所有专项测试接入正式回归且失败返回非零。
5. 关键路径有 C++ 单元测试，常规路径有多 seed 回归。
6. 干净环境无需开发者绝对路径即可构建和运行。

## 8. 旧计划的使用方式

以下旧文档已恢复并保留，用作需求来源和设计历史：

- `Phase1_IMPLEMENTATION_PLAN.md`
- `Phase2_IMPLEMENTATION_PLAN.md`
- `Phase3_IMPLEMENTATION_PLAN.md`
- `PTG_INTEGRATION_FEASIBILITY.md`
- `hypervisor-extension-gap-analysis.md`
- `hypervisor-extension-implementation-plan.md`
- `two-stage-address-translation-plan.md`
- 根目录 `two-stage-translation-plan.md`

旧文档中的状态、PASS 数量和预计周期不再作为当前结论；发生冲突时以本文和带强断言的
自动化测试结果为准。
