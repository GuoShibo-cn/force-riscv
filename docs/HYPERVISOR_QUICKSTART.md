# Hypervisor 新对话快速上手

**新 clone 请先按 [源码构建与验收入口](HYPERVISOR_BUILD_FROM_SOURCE.md) 操作。**
下文的 output/friscv-v5 等路径是本机历史候选，Git checkout 不包含这些构建产物。
交付前已完成[暂存源码树冷构建验证](SOURCE_DELIVERY_VALIDATION.md)，包括正式配置下的 full。

**最新日志修订与验收边界：** [trace v2 说明](HANDCAR_TRACE_V2_VALIDATION.md) 记录
PC/机器码错位和缺失 trap 事件的修复，新隔离 Handcar 为 `3af0cb33...`。
历史 `990/990 ISS` 是 runner 计数；后续已修复缺 H、ELF 缺页表及提前退出误判，
**新的 990/990 独立 ELF 语义审计通过**，见 [FPIX 重放验收](FPIX_ELF_REPLAY_ACCEPTANCE.md)。
旧 ELF 必须重生成，旧 PASS 记录不自动升级。

## 先读这些

1. `AGENTS.md`：语言、工作区保护和命令约束。
2. [迁移状态](HANDCAR_UPSTREAM_REBASE_STATUS.md)：已验收的库、证据与未支持范围。
3. [工作流手册](HYPERVISOR_WORKFLOW_GUIDE.md)：预检、M1、Fault V2、日志复审。
4. [依赖手册](HANDCAR_DEPENDENCY_GUIDE.md)：官方源码锁定、构建、历史快照及安装门禁。
5. `docs/plans/CURRENT_HYPERVISOR_DEVELOPMENT_PLAN.md`：M2 及后续开发范围。
6. [PTG 集成需求台账](PTG_FORCE_INTEGRATION_REQUIREMENTS.md)：已确认的 PTG-first 路线、
   现有 API 和交给 PTG 维护者的需求/问题。
7. [PTG v1 生产适配](PTG_V1_PRODUCTION_INTEGRATION.md)：当前 Python API、布局生命周期、
   已迁移模板和验证范围。M1 预检现要求 Query/Strict Export v1 符号，旧 PTG 不会静默回退。
8. [PTG 地址池适配](PTG_RESERVED_POOL_INTEGRATION.md)：首期 FORCE 预留池合同，以及
   PTG 根表对齐/容量问题 B003/B004/R003。
9. [Checked allocation/placement 验收](PTG_ALLOCATION_PLACEMENT_ACCEPTANCE_FEEDBACK.md)：
   最新候选为 `dfee221f...`，B003/B004 修复通过。
10. [Placement 生产适配](PTG_PLACEMENT_PRODUCTION_INTEGRATION.md)：Python 绑定与代表性
    模板已接入，52 ctypes/106 M1/990 ELF 审计通过；更广生命周期和 C++ Mapper 尚待完成。
11. [GenThread 托管 PTG 上下文](PTG_MANAGED_CONTEXT_INTEGRATION.md)：受约束数据映射、
    两阶段结构查询、发布/激活和双地址空间切换；full 已加入 12 项合同与 3 个 ELF 专项。
12. [C++ PTG 数据 mapper](PTG_CPP_MAPPER_INTEGRATION.md)：genVA/genVAforPA 已接入已发布
    RW 数据映射，带 native reload/失效绑定保护；完整 Mapper/动态映射仍待扩展。

**当前主线是基于 PTG 集成 FORCE Hypervisor，不是扩展另一套 C++ 页表生成器。**
PTG 负责页表生成与相应能力演进；FORCE 负责 adapter、约束/上下文、内存同步和 CSR/fence
指令。此前 native Mapper 工作保留为历史验证，不作为新 M2 的完成证据或默认后端。
PTG 不足先核对接口并提交需求文档，由用户交给维护者；不静默改走 native 后端。

维护 Spike 定制分支时另读 [分支与 rebase 手册](HANDCAR_BRANCH_WORKFLOW.md)。
`handcar/dev-spike` 是独立开发仓库，`master` 跟踪官方、`handcar/force-integration` 承载定制。
构建与验收仍使用 FORCE 的固定 lock，不会因为开发分支移动而自动升级。

不要假设“默认库就是最新版”。本机已验收的新版库尚未安装，原库有既有未提交修改。
不要执行安装、git 清理/回退或提交；除非用户明确授权。
不要运行根 `make tests`，它会删除 `output/` 中的源码、库和验收记录。

## 现有库的一条命令验收

以下在 Bash、仓库根目录执行。新机器需先替换 `HANDCAR_SO/PTG_LIB` 的实际绝对路径，
没有库时按下一节构建。Python 必须与 FORCE/seedgen ABI 匹配，本工作流使用 3.12。

```bash
source ./setenv.bash
export PYTHONDONTWRITEBYTECODE=1
HANDCAR_SO="$PWD/output/handcar-trace-v2-build/handcar_cosim.so"
PTG_LIB="$(realpath ../page_table_generator/build/libptg.so)"
python3.12 utils/regression/hypervisor_workflow.py \
  --profile quick --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB" --jobs 8 \
  --friscv "$PWD/output/ptg-cpp-mapper/friscv-v5" \
  --fpix-bin "$PWD/output/fpix-replay-validation/fpix-checked" \
  --m1-config "$PWD/output/handcar-trace-validation/rv64.config" \
  --generator-config "$PWD/output/handcar-trace-validation/twostage.config"
```

| profile | 门槛 |
| --- | --- |
| `quick` | 工具单测、预检、3 个 M1 smoke |
| `m1` | 预检、106 个 M1 用例与逐指令语义审计 |
| `full` | quick、106 M1、990 Fault V2、12 项上下文合同、3 seed 上下文 ELF、3 seed C++ 自动选址 ELF 审计 |

总入口默认使用两份 `_handcar.config`，显式开启 Zicclsm；不修改默认配置、不构建、不安装。
`--preflight-only` 只做预检，不是所选 profile 的完整通过。
失败即停止，后续阶段记录 skipped；`workflow.json` 记录命令、返回码、库哈希和子报告路径。
每轮输出新目录，重跑失败用例见工作流手册，不能复用旧日志冒充新执行。

## 没有候选库时

prepare 从官方 Git pin 和版本化 patch 构造源码，不需要旧 ignored `standalone-v2`。
父目录必须存在，source/build 输出目标必须不存在，以下示例只执行一次；重试换新名字。

```bash
source ./setenv.bash
mkdir -p output
python3.12 handcar/tools/upstream.py prepare \
  --output-dir "$PWD/output/handcar-source-new"
python3.12 handcar/tools/upstream.py build \
  --source-dir "$PWD/output/handcar-source-new" \
  --output-dir "$PWD/output/handcar-build-new" --jobs 8 --asan
HANDCAR_SO="$PWD/output/handcar-build-new/handcar_cosim.so"
```

需要 Git/GCC/G++/make/binutils、Boost 开发依赖、DTC 和 native Linux/glibc。
构建不下载/安装系统软件，不执行 `make install`；`--asan` 只插桩 wrapper 和 ABI caller。
`handcar/upstream.lock.json` 是版本事实来源，不能随意把 master 新 HEAD 当成当前验收版本。

## 单项入口

```bash
python3.12 utils/regression/run_hypervisor_m1.py --help
python3.12 utils/regression/run_ptg_fault_v2.py --help
python3.12 handcar/tools/upstream.py --help
python3.12 handcar/tools/manage.py --help
```

M1 的 `--seed` 会替换整个默认 seed 集；自定义种子通过不等于默认 106 项安装门槛。
Fault V2 的 `--handcar-so` 同时影响 FORCE 生成和 FPIX 独立执行，并检查两个进程实际加载证据。
`manage.py` 用于历史源码快照及显式授权后的安装/回滚，不是新版 upstream 构建入口。

## 可直接给新对话的任务说明

> 请先读 AGENTS.md、docs/HYPERVISOR_QUICKSTART.md、
> docs/HANDCAR_UPSTREAM_REBASE_STATUS.md 和当前开发计划。
> 检查 git status，保留全部既有修改。默认不安装、不提交、不清理 output。
> 用显式 Handcar/PTG 库路径跑 quick，记录 workflow.json；
> 然后执行指定开发任务，修改后按影响范围跑 m1 或 full。
> 报告要区分模板断言、外部审计、standalone ISS 与尚未覆盖的语义。

本轮支持合同：单 hart 0、RV64；宿主须先声明/初始化非默认 RAM；未实现的 vector/event、
PMP 属性和多 hart 功能不能从 M1/Fault V2 通过推断为支持。
