# Hypervisor 中文工作流手册

**最新 full 增量：** 现另含 `ptg_cpp_mapper` 三 seed 自动 genVA/genVAforPA ELF 审计，
需使用含 C++ bridge 的 friscv（本机 `output/ptg-cpp-mapper/friscv-v5`），详见
[C++ mapper](PTG_CPP_MAPPER_INTEGRATION.md)。旧 friscv 不会静默绕过新路径。

**最新 full 增量：** Fault V2 后新增 `ptg_context_contracts`（12 项真实 PTG 合同）与
`ptg_context`（三 seed 的双地址空间生成/独立 ELF/语义审计）。详见
[托管上下文](PTG_MANAGED_CONTEXT_INTEGRATION.md)。990 仍专指原 Fault V2 矩阵；新增
三个 ELF 单独归档在工作流 `contexts/`，不把它们混入原 330 tasks/seed 的计数。

**最新修订：** [trace v2](HANDCAR_TRACE_V2_VALIDATION.md) 已区分指令 PC 与执行后 PC，
并记录真实 trap。本文历史 FPIX `990/990` 为 runner 计数；已确认缺 H 的配置可能在
初始化提前异常后仍报 SUCCESS，不能作为目标场景独立重放证明。后续已修复并对新生成
990 ELF 完成语义审计，见 [FPIX 重放验收](FPIX_ELF_REPLAY_ACCEPTANCE.md)，含隔离二进制命令。

本文按 `handcar/tools/upstream.py`、`utils/regression/run_hypervisor_m1.py`、`utils/regression/run_ptg_fault_v2.py` 的实际代码与 `--help` 编写。新会话从官方 pin 加版本化 patch 构建 Handcar，或显式选择已有候选，再执行预检、冒烟、完整矩阵和审计。详细来源、构建 manifest、历史快照与授权安装/回滚见 [Handcar 依赖手册](HANDCAR_DEPENDENCY_GUIDE.md)。

当前 Hypervisor 开发采用用户确认的 **PTG-first** 路线：优先应用/扩充 PTG，FORCE 负责
adapter、约束/上下文、内存同步和 CSR/fence。本文现有矩阵通过不代表 PTG-backed C++
Mapper 已接通。接口需求及问题先形成[交接文档](PTG_FORCE_INTEGRATION_REQUIREMENTS.md)，
由用户提交维护者；不默认扩展独立 native 页表后端。

2026-09-19 已完成首批 Query/Strict Export v1 生产迁移，参见
[生产适配说明](PTG_V1_PRODUCTION_INTEGRATION.md)。当前 M1 预检还检查六个 v1 符号，
缺失即失败；这只是能力检查，不替代下游 ABI/语义测试。`full` 的 Fault V2 ctypes 集
后续已扩展为 52 项（含 placement 生产封装）；历史计数仍按当时版本解释。M1 预检
现在还要求四个 placement v1 符号，见 [生产适配](PTG_PLACEMENT_PRODUCTION_INTEGRATION.md)。

## 1. 先明确验收对象

| 入口 | 实际执行内容 | 不能据此宣称 |
| --- | --- | --- |
| `upstream.py prepare/build` | 官方固定 commit 加锁定 patch；源树外 configure/make，native MMU/ABI 检查，可选局部 ASan | 不是 106/990 回归入口，不安装 |
| `run_hypervisor_m1.py --preflight` | Python/文件/XML/ELF/加载器/导出符号/PTG ctypes 预检 | 没有执行 Handcar 指令，不代表语义通过 |
| `--profile smoke` | 三个现有模板各 seed 1，生成期 Handcar 执行及逐指令审计 | 不代表完整 M1，不可用于安装 |
| `--profile m1`，不指定 seed | 106 个生成期 Handcar 用例及审计 | 不是独立 ELF 重放，也不是完整 Hypervisor 支持 |
| `--audit-only RUN_DIR` | 重新检查既有 M1 归档，不生成、不加载库 | 不是在新库或新环境中重新执行 |
| `run_ptg_fault_v2.py` | ctypes 检查，然后每 seed 330 个 FORCE 生成任务及 330 个独立 FPIX ISS 任务 | 不替代 M1 专用语义审计，也不自动满足安装门禁 |

这里的“生成期/独立 ISS 两阶段”指两个执行进程，不要与地址翻译的 VS-stage/G-stage 两级混淆。

当前推荐来源已改为 `handcar/upstream.lock.json` 中的官方 commit 加 `handcar/patches/spike-4ffd6ba-handcar.patch`。锁、patch、工具和测试是非 ignored 的源码交付输入；包含它们的干净 checkout 可以重新 prepare 源码，**不再必须取回 ignored standalone/snapshot**。旧 `handcar/standalone-v2` 仍是无独立 Git 身份的历史混合来源，旧 `manage.py snapshot/build` 只用于兼容及保存历史。新 clone 不携带本机 output 证据，非 ignored 文件也需实际包含在交付提交中。

### 1.1 已有验收与当前重建

官方 pin 为 `4ffd6ba860f4190ceac2716fa3c2cf139e85538f`，不是动态跟随 master。revision2 已完成实际 **106/106 M1、990/990 generation 和 990/990 独立 ISS**：

| 对象 | 仓库根目录下的实际位置 |
| --- | --- |
| 候选库 | `output/spike-rebase-4ffd6ba/revision2-build/handcar_cosim.so` |
| SHA-256 | `aefc29258af888744e5308941cd0a43ea9bcba2a354625114b4ea17beaf12030` |
| M1 归档 | `output/spike-rebase-4ffd6ba/revision2-full-m1/m1-c9te7r64` |
| Fault V2 归档 | `output/spike-rebase-4ffd6ba/revision2-fault-v2/run_yyliol5e` |

随后正式 `upstream.py` 已从 clean prepare 完成 `output/handcar-pinned-build-v2` 冷构建和局部 ASan。该库 SHA-256 为 `a1013545508251676b63ec93686cd305a7c7140a1795887193a11061e3529224`，独立完成 106/106 M1、990/990 generation/ISS 及同哈希复审，具体目录见 [迁移状态](HANDCAR_UPSTREAM_REBASE_STATUS.md)。首次 `output/handcar-pinned-build` 的 GCC 探针失败证据保留，不作为可用库。用户继续选择**不安装**；这些候选和工具都不取代旧安装库。

独立 Handcar fork/submodule 尚无 remote，未完成接入。当前官方 URL 已知和“独立 Handcar fork 已发布”是两回事；现阶段以官方 pin 加版本化 patch 交付，不伪造 fork 或 submodule 状态。

本地开发分支已在 `handcar/dev-spike` 建立并提交：官方 `master` 与定制
`handcar/force-integration` 分开维护。后续不定期 rebase 见
[分支维护手册](HANDCAR_BRANCH_WORKFLOW.md)，不要在 FORCE 自己的 master 上运行这些操作。

## 2. 环境准备

使用 Linux/glibc 和 Bash。M1 生成与安装复审明确要求 Python **3.12**，不是任意 Python 3，也不是“至少 3.12”。本工作流统一使用 3.12；Fault V2 自身没有相同版本硬检查，但 `friscv`、`seedgen.so` 与 Python 扩展的 ABI 必须匹配。

如果当前终端是 zsh，先执行 `bash`，再执行下列命令。替换仓库/PTG 绝对路径；已有候选时设置其实际路径，没有候选的新 clone 按第 2.2 节构建后自动设置 `HANDCAR_SO`。不要将其他任务尚未完成的 build 当作可用库。

```bash
FORCE_ROOT="/absolute/path/to/force-riscv"
HANDCAR_SO=""
PTG_LIB="/absolute/path/to/page_table_generator/build/libptg.so"

cd "$FORCE_ROOT"
source ./setenv.bash
set -eo pipefail
PYTHON="$(command -v python3.12)"
test -x "$PYTHON"
"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 12); print(sys.executable, sys.version)'
test "$FORCE_SOURCED" = True
test -f "$PTG_LIB"
export PATH="$(dirname "$PYTHON"):$PATH"
export FORCE_PATH="$FORCE_ROOT"
export PTG_LIB_PATH="$PTG_LIB"
export PYTHONDONTWRITEBYTECODE=1

ls "$FORCE_ROOT"
mkdir -p "$FORCE_ROOT/output"
SESSION="$FORCE_ROOT/output/hypervisor-session-$(date -u +%Y%m%dT%H%M%SZ)-$$"
test ! -e "$SESSION"
mkdir "$SESSION"
```

必须在仓库根目录 **source** `setenv.bash`，不能直接执行它，也不能先在其他目录 source：该脚本按当前工作目录组装 `PYTHONPATH`。若提示环境已经设置但路径属于另一 checkout，请换一个干净的 Bash 会话。它并不选择 Python 版本，也不自动设置本节显式导出的所有变量。

路径建议全部使用无空格、无引号、无 `%` 的真实绝对路径。Fault V2 会拒绝含这些字符的仓库及运行目录；其旧回归执行器还会拼接命令字符串，统一简单路径最稳妥。

`SESSION` 是长期证据目录，不是临时缓存。重复整轮工作时新建 SESSION，不复用 case 输出。不推荐把最终资料放在 `/tmp`。

### 2.1 FORCE 二进制缺失时

M1 需要可执行的 `bin/friscv`、选定 Handcar、带 Fault V2 ABI 的 `libptg.so`、三个模板及完整 XML/Python 依赖。Fault V2 还检查 `bin/SimApiHANDCAR.so`、`fpix/bin/fpix_riscv`、`utils/regression/seedgen/bin/seedgen.so`。

以下是按当前 Makefile 准备 FORCE 与 seedgen 的命令，不会构建或安装所选 Handcar。已有正确二进制时跳过；构建会更新 FORCE 的构建产物，不要与正在运行的验收并行操作。

```bash
export FORCE_PYTHON_VER=3.12
export FORCE_PYTHON_INC="$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_path("include"))')"
export FORCE_PYTHON_LIB="$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')"
BUILD_JOBS=4
make -C "$FORCE_ROOT" -j"$BUILD_JOBS"
make -C "$FORCE_ROOT/utils/regression/seedgen" -j"$BUILD_JOBS" all
```

需要相应 Python 开发头文件/库及 C++ 工具链。切换 Python ABI 后，仅改变量不保证旧对象自动失效；应由维护者在受控构建环境重建不兼容产物，不能靠 `LD_LIBRARY_PATH` 将 Python 3.11 扩展冒充为 3.12。

**不要运行 `make -j && make tests`。当前根 Makefile 的 `tests` 目标首先执行 `rm -fr output`，会删除本手册所有默认验收目录以及隔离 rebase！**它还生成/安装指令模板，不是只运行 C++ 单元测试。Fault V2 的现有 330 任务矩阵不需要为此重生成全部指令模板；缺 seedgen 时用上面的定向构建。runner 的旧错误提示已修正。C++ 单元测试使用第 7 节入口。

### 2.2 获取新版 Handcar

新 clone 推荐按源码中 `handcar/upstream.lock.json` 运行已固化入口，需要 Git、Linux/glibc native GCC/G++/make/binutils/dtc、Boost/开发库及静态 libstdc++/libgcc；`--asan` 还需 libasan。以下从官方 URL 获取精确 pin 加 patch，不使用旧 snapshot。SESSION 已存在，两个输出目录必须尚不存在，不能提前 mkdir。

```bash
PREPARED_DIR="$SESSION/pinned-source"
BUILD_DIR="$SESSION/pinned-build"
test -f "$FORCE_ROOT/handcar/upstream.lock.json"
test ! -e "$PREPARED_DIR"
test ! -e "$BUILD_DIR"
"$PYTHON" "$FORCE_ROOT/handcar/tools/upstream.py" prepare \
  --output-dir "$PREPARED_DIR"
"$PYTHON" "$FORCE_ROOT/handcar/tools/upstream.py" build \
  --source-dir "$PREPARED_DIR" --output-dir "$BUILD_DIR" --jobs 8 --asan
HANDCAR_SO="$BUILD_DIR/handcar_cosim.so"
test -f "$HANDCAR_SO"
sha256sum "$HANDCAR_SO"
```

`--source-dir` 指 prepare 输出父目录，里面有 `source.json` 和 `source/`，不是 `source/` 本身。upstream jobs 默认 8，仅控制 make；没有 `--cc/--cxx`、`--timeout` 或 `--seed`。prepare 可用 `--mirror /absolute/path/to/official-clone` 离线替代联网，镜像必须有精确官方 origin URL 与固定 commit，且不会被改动。详细参数/路径保护见依赖手册。

`--asan` 默认关闭；这里显式开启，只额外插桩 wrapper 和 ABI caller，不插桩 upstream 五个静态库，不意味着全 Spike/MMU ASan 覆盖。build 会运行 native MMU/ABI 与 hart 拒绝测试，但不跑 M1/Fault V2。后续使用正常的 `handcar_cosim.so`，不是 `handcar_cosim_asan.so`。

本机若只需使用或复审第 1.1 节已有 revision2，可跳过重新构建并明确选择它；新 clone 没有该 output 时不能使用此捷径：

```bash
HANDCAR_SO="$FORCE_ROOT/output/spike-rebase-4ffd6ba/revision2-build/handcar_cosim.so"
test -f "$HANDCAR_SO"
printf '%s  %s\n' \
  aefc29258af888744e5308941cd0a43ea9bcba2a354625114b4ea17beaf12030 \
  "$HANDCAR_SO" | sha256sum --check -
```

这两个选择不要混用：完成新 build 后不要又将 HANDCAR_SO 切回 revision2，却声称测试了新工具产物。任何候选都无需安装即可执行后续验收。

### 2.3 显式 Zicclsm profiles

新版 wrapper **不再隐式追加 Zicclsm**。本矩阵包含跨页和非对齐 load，需要生成期 ISA 显式包含 `_zicclsm`。使用本轮提供的两个 profile，它们分别只在原配置 ISA 后增加 `_zicclsm`，不手工编辑原配置、不改变其他参数：

```bash
M1_CONFIG="$FORCE_ROOT/config/riscv_rv64_handcar.config"
FAULT_CONFIG="$FORCE_ROOT/config/riscv_rv64_twostage_handcar.config"
FPIX_CONFIG="$FORCE_ROOT/fpix/config/riscv_rv64_hypervisor.config"
test -f "$HANDCAR_SO"
test -f "$M1_CONFIG"
test -f "$FAULT_CONFIG"
test -f "$FPIX_CONFIG"
```

两份 profile 已随本轮源码提供，通过 import 继承基础配置并显式覆盖 ISA。若交付 checkout 缺少它们应停止，不要静默改回未声明 Zicclsm 的配置。本文不要求用户手工编辑 XML。

### 2.3 分层总入口

也可直接调用薄封装 `utils/regression/hypervisor_workflow.py`，保留同样的显式库参数：

```bash
"$PYTHON" utils/regression/hypervisor_workflow.py \
  --profile quick --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB" \
  --artifact-root "$SESSION/workflow" --jobs 8
```

`quick` 运行工具单测、预检和三个 smoke；`m1` 运行预检及 106 用例；`full` 运行 quick、
完整 M1 及默认 990-task Fault V2。`--preflight-only` 不代表 profile 全通过。
默认使用两份 `_handcar.config` 和原 FPIX 配置；可通过 `--m1-config`、
`--generator-config`、`--fpix-config` 显式覆盖。该入口不构建、不安装、不复制审计逻辑。
阶段失败立即停止，记录 skipped 后续阶段、各阶段日志、返回码、输入哈希、子报告目录到
`workflow.json`。2026-09-05 总入口 quick 和 full 均已真实通过；最终 full 证据为
`output/handcar-workflow-validation/full-7m1yahyx/workflow.json`，含 143 项工具单测、
预检、smoke、106 M1 及 990 generation/ISS。

FPIX 现在使用显式 Hypervisor profile。revision2 原非 H 配置的 990 ISS 只有历史 runner
PASS，不能视为目标场景重放证明。历史配置和结果保留，修复后必须重新生成 ELF 并实跑审计。

## 3. M1 从预检到完整验收

以下命令接续第 2 节变量，工作目录仍为仓库根目录。每一步失败即停止排查，不安装、不修改源 XML。

### 3.1 查看参数并预检

```bash
"$PYTHON" "$FORCE_ROOT/utils/regression/run_hypervisor_m1.py" --help
"$PYTHON" "$FORCE_ROOT/utils/regression/run_hypervisor_m1.py" \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB" \
  --config "$M1_CONFIG" \
  --preflight | tee "$SESSION/preflight.json"
```

两个库参数在生成和预检模式下都是必填项，没有已安装库或 `PTG_LIB_PATH` 回退。runner 默认 `--config` 仍是 `config/riscv_rv64.config`；新版命令必须显式覆盖为上述 `M1_CONFIG`，不能因为默认仍可运行预检就省略 Zicclsm profile。

预检执行 `friscv --help` 并要求 glibc 加载器证据，以 `RTLD_LAZY` 打开 Handcar 检查五个基本导出函数，并创建/销毁 PTG handle。它不 step Handcar，也不检查全部指令与 trap 语义。成功输出 JSON 中有四项输入的绝对路径、SHA-256 和 XML 依赖数量；预检不会创建 `m1-*` 用例目录。

### 3.2 冒烟

```bash
RUN_JOBS=4
"$PYTHON" "$FORCE_ROOT/utils/regression/run_hypervisor_m1.py" \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB" \
  --config "$M1_CONFIG" \
  --profile smoke --jobs "$RUN_JOBS" --timeout 120 \
  --artifact-root "$SESSION/smoke" | tee "$SESSION/smoke.console.log"
```

预期是 **3/3**，只有 access、fault、two_stage 各一个 seed 1。即使全绿，也不能提交给安装工具充当完整验收。

### 3.3 完整 M1

```bash
"$PYTHON" "$FORCE_ROOT/utils/regression/run_hypervisor_m1.py" \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB" \
  --config "$M1_CONFIG" \
  --profile m1 --jobs "$RUN_JOBS" --timeout 120 \
  --artifact-root "$SESSION/m1" | tee "$SESSION/m1.console.log"

M1_RUNS=("$SESSION"/m1/m1-*)
test "${#M1_RUNS[@]}" -eq 1
M1_RUN="${M1_RUNS[0]}"
test -f "$M1_RUN/manifest.json"
printf 'M1_RUN=%s\n' "$M1_RUN"
```

上面的自动选择只用于本轮全新 SESSION 中的一次完整运行。若自行在同一父目录运行多次，应按终端 `Artifacts:` 行明确选择对应目录，不要拿“最新文件”猜测验收对象。

| 模板标识 | 模板文件，均位于 `tests/riscv/` | 默认完整 seed | 用例数 |
| --- | --- | --- | --- |
| `access` | `ptg_hypervisor_access_matrix_force.py` | `1`、`0xdeadbeef`、`0x123456789` | 3 |
| `fault` | `ptg_hypervisor_fault_matrix_force.py` | 同上 | 3 |
| `two_stage` | `ptg_two_stage_fixed_force.py` | 十进制 `1..100` | 100 |

完整门槛是 **106/106**，且未传任何 `--seed`。审计核对 HLV.D/HSV.D/HLVX.WU、物理地址 LD 回读、`hvip`、两级翻译/跨页数据，以及四种 invalid-leaf fault 的 causes `13/15/21/23`、trap CSR 和无副作用。不是仅统计日志中 PASS。

### 3.4 jobs、seed、timeout 的准确含义

- M1 的 `--jobs` 默认 `1`，是同时运行的独立 case 数，不是 hart 数，不改变矩阵。必须为正整数。
- `--timeout` 默认每 case `120` 秒，必须为有限正数；超时终止整个用例进程组，并判失败。
- `--seed` 可重复，接受无符号 64 位十进制或 `0x` 十六进制。去重并保持首次出现顺序。
- 一旦传 `--seed`，就**替换三个模板全部默认 seed**，不是追加，也不是只调整 two_stage。N 个不同 seed 会得到 `3 × N` 个 case。
- `--profile m1 --seed 1` 只有 3 个 case；即使手工列出很多 seed，也不等于安装要求的默认矩阵，安装要求 manifest 的 `seeds` 为 `null`。

仅用于定位失败 seed 的命令：

```bash
"$PYTHON" "$FORCE_ROOT/utils/regression/run_hypervisor_m1.py" \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB" \
  --config "$M1_CONFIG" \
  --profile m1 --seed 1 --seed 0xdeadbeef --jobs 2 \
  --artifact-root "$SESSION/reproduce"
```

它执行 6 个 case，不是 106 个。安装前必须另外运行未覆盖 seed 的完整矩阵。

## 4. M1 归档及复审

### 4.1 不重新生成的审计

```bash
"$PYTHON" "$FORCE_ROOT/utils/regression/run_hypervisor_m1.py" \
  --audit-only "$M1_RUN"

"$PYTHON" "$FORCE_ROOT/utils/regression/run_hypervisor_m1.py" \
  --audit-only "$M1_RUN" \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB"
```

第一条审计原归档，原来外部传入的候选库可以不再存在。第二条额外要求当前指定库与归档库同 SHA-256；不会加载这些库。不能与 `--preflight` 或 `--seed` 同用；复审使用 manifest 中的 profile、seed、command，不用 CLI 的 `--profile` 重新选择矩阵。

`audit-only` 不运行生成器，但会重写 `results.json` 和 `summary.md`，所以归档需可写。它执行的是当前工作区的审计器，不是 `inputs/runner.py`。变更审计器后必须区分新旧结果中的 `auditor_sha256`，不能把重新出报告误称为新执行。

复审既有 revision2 时，将 `M1_RUN` 明确设为 `$FORCE_ROOT/output/spike-rebase-4ffd6ba/revision2-full-m1/m1-c9te7r64`，保留原绝对运行路径。只查看记录时读 summary/manifest 即可，无需重新运行 106/990；若选择同库复审，HANDCAR_SO 也应是原 revision2 库，不能将新 pinned-build 库附给旧证据冒充通过。

### 4.2 输出格式

每次运行在 `--artifact-root` 下创建唯一 `m1-*` 目录；参数默认父目录为 `output/hypervisor_m1`，与 manage 的“必须是新目录”规则不同，M1 的父目录可以存在并可自动创建。

```text
m1-<unique>/
  manifest.json
  receipts.json
  results.json
  summary.md
  inputs/
    runner.py
    source.config
    derived.config
    bin/handcar/...
    bin/ptg/...
    bin/friscv/...
    templates/...
    force/...
    external/...
  access-seed-1/
    command.log
    sim.log
    execution.json
    <template>.Default.ELF
    <template>.Default.S
  ...
```

| 文件 | 当前 schema / 主要字段 | 用途 |
| --- | --- | --- |
| `manifest.json` | `schema: 1`；`run_id/run_dir/created_at/profile/seeds/python/jobs/timeout/environment/inputs/cases`；`handcar/ptg/friscv/config` 指向归档相对路径 | `inputs` 记录来源和 SHA-256；每 case 有 `id/kind/seed/template/command/binding` |
| `receipts.json` | 无独立 `schema` 字段；`manifest_sha256`、`cases[].id/execution_sha256` | 绑定整体 manifest 和每个执行回执 |
| `<case>/execution.json` | 无独立 `schema` 字段；`binding/manifest_sha256/command/cwd/return_code/timeout/files`、时间、加载库证据、报告指令数/退出状态 | 绑定执行命令、日志、ELF/S 的存在性、大小和哈希 |
| `results.json` | `schema: 1`；`passed/audited_at/auditor_sha256/failures/cases` | 机器判定；逐 case 的失败原因、指令数、最终寄存器、语义证据 |
| `summary.md` | 人类可读报告 | PASS/FAIL、通过比例和逐 case 失败日志入口 |

生成器、Handcar、PTG、三个模板、`py/`、`3rd_party/py/` 及 XML 依赖被复制归档。派生配置只改 `simulator_shared_object` 的 `file` 属性，保留其他字节。相对 XML 依赖按归档 FORCE_PATH 解析；绝对 XML 依赖同时归档并用 `live_absolute` 绑定原文件。

通过要求包括退出码为 0、未超时、完整且非空 ELF/S/log、正确 ELF 头、文件哈希一致、实际库路径、seed/template/config 日志绑定、完整 sim.log 尾部、连续指令块及目标语义。指令总数是完整性证据，不是写死为某个数字的语义通过阈值。

### 4.3 证据何时失效

- M1 运行目录绑定绝对路径，移动/重命名后会报 `relocated run`；复制到新路径不能直接作为可复审原件。备份恢复应恢复到原绝对路径。
- 修改归档中的模板、XML、库、ELF/S、日志、manifest 或 execution 回执，都会触发相应哈希/绑定检查。不要“修报告”来解决失败。
- `live_absolute` 依赖被修改、删除，即使已有归档副本也会失败。普通原始相对依赖发生变化，不会取代归档中已冻结的版本。
- 原外部库变化不会改变旧运行事实，但提供 `--handcar-so/--ptg-lib` 进行同库复审会拒绝哈希不一致；安装也拒绝使用另一份 Handcar 的证据。
- 当前解析器只支持这三个模板的单 hart、非推测 trace，未知格式、部分寄存器 mask、截断或拼接日志按失败处理。新 Spike trace 改变时应补充审计器与负向测试，不能放宽为只看 SUCCESS。
- SHA-256 防止陈旧/替换产物被误用，不是签名，不能抵抗同时重写证据与 manifest 的攻击者。这里也不是完整系统镜像，未冻结所有宿主运行时依赖。

M1 命令成功返回 `0`，审计不通过返回 `1`，预检/runner 错误通常返回 `2`；argparse 参数错误也返回 `2`。启动准备阶段失败可能没有运行目录或完整报告。流水线使用 `set -o pipefail`，否则 `tee` 的成功会掩盖 runner 的失败。

## 5. Fault V2 两执行阶段回归

### 5.1 命令

接续第 2 节环境。该入口保留调用者的 ABI/加载器环境，不像 M1 主动清理 `LD_LIBRARY_PATH`、`LD_PRELOAD`、`PYTHONHOME` 等变量。先检查不必要的注入或旧 Python 环境；若必须保留，应将其视为本次验收条件。

```bash
"$PYTHON" "$FORCE_ROOT/utils/regression/run_ptg_fault_v2.py" --help
"$PYTHON" "$FORCE_ROOT/utils/regression/run_ptg_fault_v2.py" \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB" \
  --generator-config "$FAULT_CONFIG" \
  --fpix-config "$FPIX_CONFIG" \
  --artifact-root "$SESSION/fault-v2" | tee "$SESSION/fault-v2.console.log"
```

默认 seed 为 `0x15c0ffee`、`0x5eed1234`、`0xc001d00d`，共 **990 个生成任务 + 990 个独立 ISS 任务**。每 seed 必须有 Generate=330、ISS Sim=330、Total Tasks=330，三个相应失败计数都为 0。

此外每个任务必须通过 `ptg_replay_audit.py`：从 ELF entry 启动，无启动异常，完整重放
已断言的生成期场景，逐步匹配 PC/opcode/next-PC/trap/访存/寄存器结果及合法终点。
缺失、截断、额外步骤或错误异常都会令 runner 失败。输入需使用 trace-v2 adapter 与
包含物理写镜像同步修复的 friscv；旧 ELF 缺页表，不能直接用新 ISA 配置补救。
`--friscv`、`--fpix-bin` 可以显式选择隔离二进制，总入口也支持并透传这两个参数。

`--seed` 重复传入会替换默认 seed 集，按规范化后的数值去重。下例只有一个 seed，即 330 个生成任务和 330 个 ISS 任务，不是三 seed 完整验收：

```bash
"$PYTHON" "$FORCE_ROOT/utils/regression/run_ptg_fault_v2.py" \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB" \
  --generator-config "$FAULT_CONFIG" --fpix-config "$FPIX_CONFIG" \
  --seed 0x15c0ffee --artifact-root "$SESSION/fault-v2-reproduce"
```

**这个脚本没有 `--jobs`、`--timeout`、`--profile`、`--preflight`、`--audit-only`。**它依次处理 seed，由底层 `master_run.py` 管理任务执行；不能照搬 M1 的并发参数。需要单独 ctypes 检查时用第 7 节命令。

### 5.2 必须显式指定同一 Handcar

Fault V2 的 `--handcar-so` 默认是 `utils/handcar/handcar_cosim.so`，容易误用旧库，因此本手册始终显式传入候选库。

runner 在新目录生成两份配置，将**两个 simulator_shared_object 都设为同一显式候选**。
ISA 不自动改写，但 FPIX 配置必须显式包含 H，否则拒绝运行。默认 FPIX 配置已改为
`fpix/config/riscv_rv64_hypervisor.config`，包含 H/Zicclsm；generator 仍须显式选
`FAULT_CONFIG`。XML 经重新序列化，不保证字节格式不变。

不能仅修改 `ISS_SO_PATH` 或工作流的 `iss_so_path` 就声称更换了独立 ISS 库：当前 FPIX 执行器实际通过 `--cfg` 加载库，`iss_so_path` 主要被初始化检查消费。新 runner 同时设置派生配置，并要求两阶段实际加载证据。

`--ptg-lib` 未指定时先取 `PTG_LIB_PATH`，再在都未指定时搜索仓库内 `3rd_party/page_table_generator/build/libptg.so` 及仓库同级 `page_table_generator/build/libptg.so`。显式路径无效不会回退。这些候选是搜索规则，不保证新 clone 中存在 PTG。

### 5.3 输出与证据边界

默认父目录是 `output/ptg_fault_v2`，每次创建唯一 `run_*`：

```text
run_<unique>/
  manifest.json
  ctypes.log
  generator.config
  fpix.config
  ptg_fault_v2_fctrl.py
  ptg_fault_v2_fcfg.py
  seed_<hex>/
    master_run.log
    loader/trace.<pid>
    output/regression/regression_summary.log
    output/regression/...
```

底层以 `-k all` 保留任务资料。诊断时先打开运行目录 manifest 的 `failures`、对应 `master_run.log` 和 summary，再按具体任务目录查看生成/ISS 日志及 ELF/S。

Fault V2 **当前没有 `schema` 版本字段**，不要按 M1 schema 1 解析。其 `manifest.json` 主要结构是：

| 字段 | 含义 |
| --- | --- |
| `argv/run_root/started_at/finished_at/seeds/tasks_per_seed` | 本轮参数、目录、时间和每 seed 330 任务 |
| `sources/source_note` | FORCE/PTG 库目录/Handcar 库目录的 Git 探测命令、返回码、输出与 dirty 状态；不是库构建来源证明 |
| `inputs/inputs_after` | 库、配置、二进制、runner、ctypes 测试、控制文件及工作流的路径、SHA-256、大小；正常完成时比较前后 |
| `generated/environment/commands` | 派生文件记录、继承环境、每次子命令的 argv/cwd/log/时间/退出码/loader 设置 |
| `results` | 每 seed 返回码、summary 路径/哈希/文本/计数、`load_evidence` |
| `results[].replay_audits` | 每任务启动步数、完整场景步数、trap 数、ELF 与两份 trace 的 SHA-256 |
| `failures/return_code` | 全局错误；成功为 0，回归失败一般为 1，准备/启动异常通常为 2 |

每 seed 要求 glibc `LD_DEBUG=libs` 产生 **330 条 generation 和 330 条 standalone_iss 进程记录**。每个进程必须出现选定库的 `calling init:`，不能只出现 `trying file=`，也不能加载另一路径下的旧 `handcar_cosim.so`。summary 全绿但缺少任一阶段的加载记录仍失败。已记录的输入在运行前后变化也失败。

每个任务的 `fpix_sim.log` 是独立 trace，`fpix_console.log` 是 stdout/stderr，不能再由
两个 writer 写同一文件。成功任务记录 ELF/两份 trace 哈希；不复制冻结全部依赖，也不
提供 M1 式完整离线复审。前后哈希不是构建来源证明。提前退出可能只有部分字段，
不能单独读取 return_code 而忽略失败列表及缺失审计结果。

更换任一库、模板、ABI、配置或宿主环境，应重新跑矩阵；旧目录只证明原运行。M1 的 `--audit-only` 不能用于 Fault V2 目录，Fault V2 结果也不能交给 `manage.py install --acceptance-dir`。

## 6. 排错顺序

| 现象 | 检查和处理 |
| --- | --- |
| `run with Python 3.12` / `source setenv.bash` | 检查实际解释器；在正确根目录用 Bash source，不能仅手工伪造 `FORCE_SOURCED=True` |
| `seedgen` 导入失败、Python 版本不匹配 | 核对解释器、`FORCE_PYTHON_*` 与编译产物 ABI；定向重建 seedgen，不运行会删除 output 的根 `make tests` |
| Handcar `undefined symbol`，尤其 `fast_rv32e_mop_r_4...` | 多为生成指令列表与对象混用，见依赖手册；不要加假 alias 或容忍未解析指令符号 |
| PTG ctypes/结构体/导出函数失败 | 核对确实传入带 V2 ABI 的 `libptg.so`；先运行独立 ctypes 测试，不靠旧库回退掩盖问题 |
| `hvip` 读回异常 | 源码改好不等于旧 `.so` 改好；查看实际库路径/哈希，隔离构建并重跑语义矩阵 |
| 新版非对齐/跨页访问触发 misaligned trap | 生成期显式使用 `_handcar.config`，FPIX 使用 Hypervisor profile；两个阶段都声明 Zicclsm，不让 wrapper 隐式改 ISA |
| 未知物理地址 store fault | 检查宿主是否先初始化/声明 RAM backing；架构 store 不自动创建 sparse RAM，设备拒绝不可转为内存成功 |
| attrs 返回 9 / 非零 hart 初始化失败 | 属于明确不支持的合同；PA-only 传空 attrs，当前只支持 hart 0，不可视为可忽略的成功状态 |
| PASS/SUCCESS、退出码 0，但审计失败 | 属于假绿防护：查看具体失败、目标寄存器、VA/PA/数据、trap CSR 和无副作用证据，不能仅凭旧测试 `notice("FAIL")` 后的退出 0 验收 |
| `wrong/missing actual ... library` / loader records 不足 | 检查 M1 `command.log` 或 Fault V2 `loader/trace.*` 中正确进程的 `calling init:`；配置路径和搜索尝试不是加载证明 |
| `unsupported/malformed trace` | 检查真实 trace 变化、截断、多 hart 或推测记录；不能删掉不认识的行后重审 |
| `input/artifact hash mismatch` / `relocated run` | 恢复原始证据及原路径，或重新生成到新目录；不要改 manifest 哈希 |

M1 子环境清除 `LD_PRELOAD/LD_AUDIT/LD_LIBRARY_PATH/LD_DEBUG_OUTPUT/PYTHONHOME` 并固定 `LD_DEBUG=libs`，不应依赖外部库搜索路径“碰巧加载正确”。Fault V2 则保留原 ABI 环境，并把调试记录分离到每 seed 的 loader 目录。两者都依赖 Linux/glibc 的日志格式；没有加载证据时不能降级成只检查配置。

### 6.1 106/990 不覆盖什么

- 支持合同限定 native Linux/glibc、RV64、单 hart 且 hart id 0；`-p2`、`--hartids=0,1`、`--hartids=1` 应被拒绝。不能把 jobs 并发误写成多 hart 支持。
- 默认 RAM 外必须由宿主显式初始化/声明 RAM backing。普通 store、fetch、页表 PTE A/D 更新及 `CBO.ZERO` 都不能声明新内存；未知 store 必须 fault，不能为假绿自动补 RAM。C++ `declare_sparse_memory` 调用者负责区分 RAM 与 MMIO。
- 设备拒绝访问不能转成 sparse RAM 成功；该机制不是通用 PMA 模型。已有正常 RAM/已声明 sparse RAM 与设备空间分开处理。
- legacy packed PMP attrs 输出未实现，非空 attrs 请求返回状态 9；PA-only 调用传空指针，不能把未实现属性当已验证数据。
- vector 大寄存器读写、event/parameter 等仍有 stub，返回 0 不能证明真实语义。一般 ELF loading、sparse LR/SC、多 hart 也不是已建立支持；FPIX 本矩阵通过不等于任意 ELF 都可加载运行。
- ABI 反汇编接口依赖调用端自有 128 字节缓冲区。局部 ASan 只覆盖 wrapper 与 ABI caller，不覆盖完整 upstream/MMU，更不代替 Hypervisor 全指令、委托/中断、嵌套 trap 等覆盖。

## 7. 单元检查

在第 2 节已 source 的 Bash 中执行。前四项检查工具的正负向、安全和假绿防护，不执行完整 106/990 矩阵；upstream 测试是离线夹具，不做完整 native build，旧管理工具测试会在测试临时目录构建小型 native 夹具，不接触实际安装库。

```bash
"$PYTHON" -m unittest discover -s "$FORCE_ROOT/handcar/tools" -p test_upstream.py -v
"$PYTHON" -m unittest discover -s "$FORCE_ROOT/handcar/tools" -p test_manage.py -v
"$PYTHON" -m unittest discover -s "$FORCE_ROOT/utils/regression/tests" -p test_hypervisor_m1.py -v
"$PYTHON" -m unittest discover -s "$FORCE_ROOT/utils/regression/tests" -p test_ptg_fault_v2_runner.py -v

PTG_LIB_PATH="$PTG_LIB" "$PYTHON" "$FORCE_ROOT/tests/riscv/ptg_fault_v2_ctypes_test.py"

"$PYTHON" "$FORCE_ROOT/utils/regression/unit_tests.py" \
  --force-path "$FORCE_ROOT" --process-max 4 --print-failures
```

ctypes 测试实际加载 PTG，但不运行 Handcar。最后一条会在各 `unit_tests/` 目录构建并运行 C++ 用例，日志在对应 `bin/make.log`、`bin/run.log`，失败返回非零；它不是根 `make tests`，不清空根 `output/`。需要 Python 编译参数时使用第 2.1 节的导出变量。

本轮 upstream 工具离线测试 19 项通过；前轮 manage/M1/Fault V2 runner 测试分别 41、32、27 项通过。这只是工具级检查。真正 native `upstream_mmu_checks.cc` 和 `upstream_abi_checks.cc` 由 `upstream.py build` 编译执行，新 pinned-build 的最终构建和回归结果必须单独记录。

## 8. 长期交付清单

保留整个 SESSION、新版 prepare/source.json 与 build/build.json、版本化官方 pin/patch/工具/测试/profile，以及旧 snapshot 和已存在的历史 backup receipt。不要只留 `summary.md`、一份 PASS 截图或单个 `.so`。交接记录至少应指出 Handcar/PTG 哈希、M1 完整运行绝对路径、Fault V2 运行路径、配置与 seed 范围、当前审计器版本和未完成边界。

`output/` 默认被 Git 忽略，**存在于本机不等于已提交或已备份**。使用长期磁盘和独立备份，避免清理任务、`git clean -fdx`、根 `make tests` 及人工移目录破坏证据。M1 归档应原路径保留，源码快照的可迁移规则见依赖手册。

revision2 与正式固化工具产物各自有独立的 106/990 通过记录，证据保持原路径保存，见迁移状态。每份新产物仍需自己的完整验收记录，不能按 commit 相同继承旧 PASS。用户当前不安装的选择继续有效；任何后续安装都需另行明确授权，且不代表完整 Hypervisor 支持或独立 fork/submodule 已完成。
