# Handcar 中文依赖管理手册

最新诊断候选与验收边界见 [trace v2](HANDCAR_TRACE_V2_VALIDATION.md)：新 patch
SHA-256 为 `daa1fc933dec48150c00d976623077ad09bc6193dd1500ef0bf74d6f3df9689a`，
已冷构建并验证 PC/trap 日志。下文旧 patch/库哈希保留历史身份；历史 FPIX PASS 计数
不能替代目标场景独立重放验收。该问题后续已在新 FORCE/FPIX 修复，并对重生成的
990 份 ELF 完成语义审计，见 [FPIX 重放验收](FPIX_ELF_REPLAY_ACCEPTANCE.md)。

新版推荐入口是 `handcar/tools/upstream.py`：按 `handcar/upstream.lock.json` 获取官方固定提交，应用仓库内的版本化 patch，再由官方 configure/make 在源树外重新生成和构建。旧 `manage.py snapshot/build` 仅用于兼容及保存本地历史来源；`manage.py install/rollback` 仍负责授权安装和回滚。Hypervisor、M1、Fault V2 的完整运行说明见 [工作流手册](HYPERVISOR_WORKFLOW_GUIDE.md)。

## 1. 当前事实与迁移状态

- 新版来源是官方 `https://github.com/riscv-software-src/riscv-isa-sim.git` 的固定提交 `4ffd6ba860f4190ceac2716fa3c2cf139e85538f`，不是随时间变化的 master HEAD。
- `handcar/upstream.lock.json`、`handcar/patches/spike-4ffd6ba-handcar.patch`、`handcar/tools/upstream.py`、对应 Python 测试及两个 native 测试均已形成非 ignored 的源码交付输入。包含这些文件的干净 checkout 可以从官方对象和 patch 重现源码，不再必须依赖 ignored standalone 或旧 snapshot。非 ignored 不等于已经推送；交付 checkout 必须实际包含这些文件。
- trace v2 之前的 patch SHA-256 为 `52e0a9929cc31b24b45c0a934b98a266b1bf5788d77f889e52f047d32dff27ce`；当前值见顶部及 lock，工具校验 patch、测试和消费端头文件哈希。
- 旧 `handcar/standalone-v2` 仍是没有独立 Git 身份、许多文件被忽略的本地混合来源目录。其 `git rev-parse` 会向上落到 FORCE，不能作为旧库的 Spike 来源证明。`handcar/dependency.json` 的 `schema: 1`、`standalone-v2-gnu20-v1` 和 `upstream: unknown` 只描述该旧流程，不与新版 pin 混用。
- 新 clone 不自动携带本机 `output/` 证据或旧 snapshot，但新版 prepare 不需要它们。官方远端已经明确，独立 Handcar fork 的 remote 仍未提供，submodule 尚未接入；不能把官方远端或 FORCE origin 说成已发布的 Handcar fork。

本地独立开发仓库现已建立在 `handcar/dev-spike/`，`master` 跟踪 `upstream/master`，
`handcar/force-integration` 已提交定制，初始 commit 为
`3cd61c76d87a10eadb4e1b6d763de6b8d837c903`。这不等于远端发布或 submodule 完成。
定期快进同步、备份和 rebase 操作见 [分支维护手册](HANDCAR_BRANCH_WORKFLOW.md)。
`upstream.py prepare --mirror` 可接受官方名为 `upstream` 的开发仓库，兼容原 `origin`
命名；存在 `upstream` 时必须是官方地址，不会偷偷回退到其他 remote。

**revision2 已有实际验收，不再标记为“仅完成上游 checkout”：**

| 对象 | 仓库根目录下的实际位置或结果 |
| --- | --- |
| 已验收候选库 | `output/spike-rebase-4ffd6ba/revision2-build/handcar_cosim.so` |
| 候选 SHA-256 | `aefc29258af888744e5308941cd0a43ea9bcba2a354625114b4ea17beaf12030` |
| 完整 M1 | `output/spike-rebase-4ffd6ba/revision2-full-m1/m1-c9te7r64`，106/106 |
| 默认三 seed Fault V2 | `output/spike-rebase-4ffd6ba/revision2-fault-v2/run_yyliol5e`，990/990 generation、990/990 独立 ISS，manifest 无失败 |
| 固化工具最终构建 | `output/handcar-pinned-build-v2`，冷构建、MMU/ABI/局部 ASan 通过 |
| 固化工具产物 SHA-256 | `a1013545508251676b63ec93686cd305a7c7140a1795887193a11061e3529224` |
| 固化工具产物验收 | 106/106 M1、990/990 generation 和 ISS，同哈希 audit-only 通过；目录见迁移状态 |

revision2 与固化工具产物有各自独立的验收，不能互相转记。最新证据路径见
[迁移状态](HANDCAR_UPSTREAM_REBASE_STATUS.md)。首次 `output/handcar-pinned-build`
因 GCC 探针错误失败，后续已修正工具并换目录重建，失败记录保留。
源码可重现、构建成功、同库完整回归和安装是四个不同状态。**用户仍选择不安装，现有安装库保持不动。**106/990 也不代表完整 Hypervisor、完整内存模型或多 hart 支持，具体边界见第 3.5 节。

## 2. 准备环境和长期目录

使用 Bash、Linux/glibc、本机 64 位构建环境；不承诺交叉编译或旧 glibc 可移植性。新版需要 Git、支持 GNU C++20 的 GCC/G++、make、binutils（ar/ranlib/ld/as/nm）、ldd、dtc、POSIX sh、Boost/宿主开发依赖及静态 libstdc++/libgcc；`--asan` 还需要 libasan。旧 manage 构建另有 LP64/`__int128` 探针，不能把它误写成 upstream 的独立预检步骤。仓库其他位置的旧编译器最低版本说明不足以保证新构建可用。

统一用 Python 3.12 运行命令，特别是安装复审严格要求 3.12。没有工具时请按宿主发行版的受控流程准备依赖；本管理器不会自动安装软件包或请求 sudo。

```bash
FORCE_ROOT="/absolute/path/to/force-riscv"

cd "$FORCE_ROOT"
source ./setenv.bash
set -eo pipefail
PYTHON="$(command -v python3.12)"
test -x "$PYTHON"
"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 12); print(sys.executable, sys.version)'
test "$FORCE_SOURCED" = True
export PYTHONDONTWRITEBYTECODE=1
export PATH="$(dirname "$PYTHON"):$PATH"

ls "$FORCE_ROOT"
mkdir -p "$FORCE_ROOT/output"
WORK="$FORCE_ROOT/output/handcar-$(date -u +%Y%m%dT%H%M%SZ)-$$"
test ! -e "$WORK"
mkdir "$WORK"
PREPARED_DIR="$WORK/prepared"
BUILD_DIR="$WORK/build"
```

先进入根目录再 source；不能在 zsh 中直接套用脚本的 Bash 语义。如果继承了另一 checkout 的 `FORCE_ORIG_PYTHONPATH`，应换干净 Bash 会话。不要把 `FORCE_SOURCED=True` 当作可替代 source 的环境修复。

`WORK` 是新建的长期父目录，`PREPARED_DIR`、`BUILD_DIR` 则**不要提前 mkdir**。新版 `prepare/build --output-dir` 和旧版 `snapshot/build --output-dir` 都要求目标不存在，连已存在空目录也拒绝；其父目录必须已经存在。输出不能与输入、`handcar/`、`utils/handcar/`、`bin/` 发生祖先/后代重叠。新版还要求路径仅含 ASCII 字母、数字、`_ . / + -`，拒绝 `..` 和所有路径组件中的符号链接。失败输出保留，重试用新名字，不清理后原地复用。

重要：当前根 `make tests` 会先删除整个 `output/`。保留本手册目录和 rebase 资料时不能运行该目标；C++ unit runner 及 seedgen 定向构建见工作流手册。`output/` 被忽略，不代表已经备份，最终资料应长期保存并做独立备份，而不是放到 `/tmp`。

## 3. 推荐：官方 pin 加 patch

### 3.1 新会话快速开始

接续第 2 节环境和全新目录。先确认交付文件，再 prepare/build；不用 ignored 驱动，不复制旧 `.o`，也不安装。

```bash
test -f "$FORCE_ROOT/handcar/upstream.lock.json"
test -f "$FORCE_ROOT/handcar/patches/spike-4ffd6ba-handcar.patch"
"$PYTHON" "$FORCE_ROOT/handcar/tools/upstream.py" --help
"$PYTHON" "$FORCE_ROOT/handcar/tools/upstream.py" prepare --help
"$PYTHON" "$FORCE_ROOT/handcar/tools/upstream.py" build --help

"$PYTHON" "$FORCE_ROOT/handcar/tools/upstream.py" prepare \
  --output-dir "$PREPARED_DIR"
BUILD_JOBS=8
"$PYTHON" "$FORCE_ROOT/handcar/tools/upstream.py" build \
  --source-dir "$PREPARED_DIR" --output-dir "$BUILD_DIR" \
  --jobs "$BUILD_JOBS" --asan

HANDCAR_SO="$BUILD_DIR/handcar_cosim.so"
test -f "$HANDCAR_SO"
sha256sum "$HANDCAR_SO"
```

`--source-dir` 必须指向含 `source.json` 的 **prepare 输出父目录**，不能指向其 `source/`、普通 upstream clone 或旧 manage snapshot。执行成功返回正常候选库路径。新库需继续第 6 节验收，不能引用其他库的 PASS 作为本轮结果。上面的目录刻意不复用已有构建输出。

| 子命令 | 实际参数 | 默认行为 |
| --- | --- | --- |
| `upstream.py prepare` | 必填 `--output-dir`；可选 `--mirror` | 从锁定官方 URL clone，detached checkout 固定 commit，检查并应用 patch |
| `upstream.py build` | 必填 `--source-dir/--output-dir`；可选 `--jobs/--asan` | `jobs=8`，ASan 默认关闭；源树外 configure/make、native 检查及符号审计，不安装 |

upstream 没有 `--cc/--cxx`、`--seed`、`--timeout`、`verify-source` 或 `install`。jobs 为正整数，只控制 make 编译并发。旧 manage 的 jobs 默认是 1，M1 runner 的 jobs 默认也是 1，不要混为同一默认值。upstream 成功退出 0，被捕获的操作失败退出 1，参数错误退出 2；没有每条命令的内置超时参数。

### 3.2 prepare 的来源检查

联网默认从官方 URL 取得 Git 对象；已有本地官方 clone 时，可以用它作为只读对象来源。以下是**替代**上面 prepare 的离线命令，需另一个新输出名：

```bash
OFFICIAL_MIRROR="/absolute/path/to/local/riscv-isa-sim"
PREPARED_DIR="$WORK/prepared-from-mirror"
test -d "$OFFICIAL_MIRROR"
"$PYTHON" "$FORCE_ROOT/handcar/tools/upstream.py" prepare \
  --mirror "$OFFICIAL_MIRROR" --output-dir "$PREPARED_DIR"
```

mirror 的 `origin` 必须精确为 lock 中的官方 HTTPS URL，并包含 pin；不能用修改 remote 来伪造来源。工具 `clone --no-checkout --no-hardlinks`，不继承镜像工作区的脏文件，不改镜像。联网时不交互索取 Git 凭据，禁用系统/全局 Git 配置及 hooks；需要站点网络配置时应使用经核对的本地官方镜像，而非假设用户 Git URL 重写仍生效。

prepare 后 `source/` 有独立 `.git/`，HEAD detached 在 pin；index 保持官方 commit，patch 只应用到工作树，不创建本地提交、不 stage。因此它不是“git status 必须全空”的源码；**期望状态是 pin 加精确 patch**。检查器在私有临时对象库/index 中计算预期树，并检查实际文件、目录、内容、执行位及安全链接。源码中新增 ignored `.o`、额外空目录、删除文件、stage patch、修改 HEAD 或 source.json 都会被 build 前校验拒绝。不要在 `source/` 内 configure/make 或手工修补。

`upstream.lock.json` 使用 `schema_version: 1`，不是旧 manage 的 `schema: 1`。它锁定 `upstream.url/commit`、`patch.path/sha256`、两个 native `tests` 和消费端 `utils/handcar/SimLoader.h` 哈希；`provenance.fork_remote: null` 如实表示无独立 fork。`provenance.patch_export` 记录 patch 的历史导出位置，**prepare 不读取该 ignored 文件**，只读取仓库中的 patch。`support` 描述能力合同，不是通过记录。升级 pin/patch/test/头文件需要一致的代码与 lock 变更，不是运行时覆盖参数。

### 3.3 build 与 ASan 范围

build 使用 `/usr/bin:/bin` 的本机工具，受控环境不继承 `MAKEFLAGS`、编译/include 覆盖或 preload；HOME/TMPDIR 指向本轮输出，`CONFIG_SITE=/dev/null`。它调用已核对 source 中的 configure，在输出目录 make 五个静态库 `libriscv/libdisasm/libfesvr/libsoftfloat/libfdt`，重新生成指令源，再编译 Handcar wrapper。正常库用 whole-archive 链接，静态链接 libstdc++/libgcc。与旧 snapshot build 的“冻结预生成源再逐文件编译”不同，这是官方生成流程，不借用旧 standalone 文件。

每次 build 都运行 `mmu_checks`、使用真实 `SimLoader.h` 类型的 `abi_checks`，以及 `-p2`、`--hartids=0,1`、`--hartids=1` 三个预期退出 1 的拒绝测试。构建日志中这些命令的 `expected_exit: 1` 是负向测试，不应误判为漏报；退出 99 表示错误接受配置，会使 build 失败。正常库还须通过 `nm`/`ldd -r` 审计：未解析强回调恰为 FORCE 的两个 generator callback，系统依赖正常，不动态依赖 libstdc++.so。

`--asan` **额外**生成 `handcar_cosim_asan.so`、`abi_checks_asan` 并运行 ABI 检查，设置 `ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:strict_string_checks=1`。只对 wrapper 和 ABI caller 插桩，五个 upstream 静态库仍是未插桩的正常构建，不能声称全 Spike/MMU sanitizer 覆盖或完整 ASan 回归。用于后续 M1/Fault V2 的仍是 `handcar_cosim.so`；不要把诊断 `.so` 冒充正常候选，也不要自动安装任何一种库。

### 3.4 新版输出和失效边界

| 文件 | 当前结构和用途 |
| --- | --- |
| `prepared/source.json` | 顶层 `identity/mirror/commands/prepare_log_sha256`；`identity.schema_version: 1`、upstream、patch、`lock_sha256/tree/source_files`；每个源文件记录 mode/SHA-256 |
| `prepared/prepare.log` | prepare 的 Git 命令与输出；失败可能另有 `failure.json`，没有成功 source.json 时不可交给 build |
| `build/build.json` | `schema_version: 1`、`status/source_identity/source_dir/jobs/asan/asan_scope/host/environment/commands/tools` 等，不能按 manage build.json 同一字段表解析 |
| build 来源和工具字段 | `input_sha256/source_manifest_sha256/compiler_target/compiler_configuration/compiler_input_sha256`；记录工具、lock、patch、测试、消费端头文件和编译输入身份 |
| build 产物和审计字段 | `artifact_sha256/dependency_sha256/runtime_dependency_sha256/source_unchanged/library_sha256/log_sha256`；失败可能有 `error/source_check_error` |
| `build/inputs/`、`build/abi/` | native 测试、消费端 loader 头副本，以及 patch 内两份 wrapper ABI 头副本 |
| build 其他资料 | configure 输出/生成指令源/静态库、`handcar_cosim.so`、native 检查程序、`nm.txt/ldd.txt/build.log`；启用 ASan 时另有诊断库与 caller |

`commands[]` 记录 argv/cwd/expected_exit/exit_code/environment_overrides。`artifact_sha256` 在成功末尾收集产物（不包含 build.log 和随后写入的 build.json）；日志另用 `log_sha256` 记录。结束前重查 lock、输入、工具、源码和 source.json，`source_unchanged: true` 与 `status: passed` 才是本轮构建成功记录。准备/源码校验失败可能在创建输出前退出；后续失败保留失败 build.json 与日志，即使已有 `.so` 也不可跳过失败。

这不是签名、密封容器或位级可复现保证，不抵抗同时篡改工具/lock/证据。source.json 的 identity 不绑定旧绝对位置，但搬迁 prepared 时必须完整保留独立 `.git`、文件模式及合法链接；下一次 build 仍按当前 lock 重新校验。build 日志和依赖记录包含绝对路径，不提供通用 `verify-build` 或搬迁后自动复审命令。任何补丁、工具链、ABI/测试输入变化都应重新 prepare/build/验收；M1 运行归档还必须保留原绝对路径。不要混用不同 schema 的记录或手改哈希让它们通过。

### 3.5 新版支持合同

- ISA 不再隐式追加 `Zicclsm`。跨页/非对齐访问需要调用者显式请求 `_zicclsm`；无该扩展时相应 misaligned trap 是正常语义，不应修改 wrapper 偷开扩展。
- 新版 M1 使用 `config/riscv_rv64_handcar.config`，Fault V2 生成期使用 `config/riscv_rv64_twostage_handcar.config`；两者只在原配置 ISA 后显式增加 `_zicclsm`。FPIX 继续使用原 `fpix/config/riscv_rv64.config`，本轮 990 已在该配置下通过，不要求为它额外开启 misaligned。
- 默认 RAM 之外，宿主必须先声明/初始化 RAM backing。wrapper 的外部 FORCE 初始化路径与 C++ `declare_sparse_memory` 是宿主接口，不是目标指令；普通 store、fetch、PTE A/D 更新和 `CBO.ZERO` 不自动声明内存。向未知地址 store 返回 fault，不能因为失败就创建 sparse backing 或发成功访存回调。
- RAM 与 MMIO 必须区分；设备拒绝访问不得降级成 sparse RAM。C++ 声明调用者负责选择 RAM 区域，这不是通用 PMA/设备发现模型。
- 只建立 RV64、一个 hart、hart id 0 的合同；其他 hart 配置被拒绝。地址翻译只求 PA 时传空 attrs 指针，legacy packed PMP attributes 未支持，非空 attrs 返回状态 **9**，不是有效属性结果。
- vector 大寄存器访问、事件注入和参数接口仍有 stub，不能由返回 0 推断语义支持；一般 ELF 加载、sparse LR/SC、多 hart 也不是已建立支持。反汇编要求调用端自有的 128 字节 opcode/disassembly 缓冲区。

## 4. 旧版 snapshot 与 verify-source

以下仅用于历史归档或旧源码兼容，**新用户跳过本节及第 5 节，按第 3 节构建后直接进入第 6 节**。`manage.py` 的 source lock 不是 upstream prepare 的 source.json，两类 source-dir 不能交换。

### 4.1 旧管理器参数

```bash
"$PYTHON" "$FORCE_ROOT/handcar/tools/manage.py" --help
"$PYTHON" "$FORCE_ROOT/handcar/tools/manage.py" snapshot --help
"$PYTHON" "$FORCE_ROOT/handcar/tools/manage.py" build --help
"$PYTHON" "$FORCE_ROOT/handcar/tools/manage.py" install --help
"$PYTHON" "$FORCE_ROOT/handcar/tools/manage.py" rollback --help
```

| 子命令 | 参数及默认值 | 写入范围 |
| --- | --- | --- |
| `snapshot` | 必填 `--source-dir`、`--output-dir` | 新快照目录 |
| `verify-source` | 必填 `--source-dir`，该目录需已有 lock | 只校验，输出 JSON 摘要 |
| `inspect` | 与 `verify-source` 相同 | 它是完整校验的别名，不是只看目录名称 |
| `build` | 必填 source/output；`--jobs 1`、`--cc gcc`、`--cxx g++` | 新构建目录，不安装 |
| `install` | 必填 `--library`、`--acceptance-dir`、`--backup-root`；`--target utils`，可选 `both`；必须 `--yes` | 经授权才替换指定安装文件，并保留备份/回执 |
| `rollback` | 必填 `--receipt`；必须 `--yes` | 按回执恢复原安装文件，带哈希保护 |

管理器没有独立 `preflight/smoke/m1/audit-only` 子命令，这些属于 M1 runner。正常成功返回 `0`，被管理器捕获的操作失败返回 `1`，argparse 参数错误返回 `2`。终端 JSON 会省略大体量的 files、inputs、commands、工具链细节等，完整记录必须看落盘文件。

### 4.2 冻结历史有效源码

只有要保留或重建旧库时，才需要从可信维护者获取其完整有效源码/快照。新 clone 的新版入口是第 3 节，不需要取回 ignored standalone。不能用旧 `.so` 反推出 snapshot，也不能随意 clone 最新 Spike 充当旧库来源。

```bash
SOURCE_DIR="$FORCE_ROOT/handcar/standalone-v2"
SNAPSHOT_DIR="$WORK/legacy-source"
test -d "$SOURCE_DIR"
test ! -e "$SNAPSHOT_DIR"
test -d "$WORK"
"$PYTHON" "$FORCE_ROOT/handcar/tools/manage.py" snapshot \
  --source-dir "$SOURCE_DIR" --output-dir "$SNAPSHOT_DIR"

"$PYTHON" "$FORCE_ROOT/handcar/tools/manage.py" verify-source \
  --source-dir "$SNAPSHOT_DIR"
```

若接收的是既有锁定快照，可以先对其执行 `verify-source`，再把 `SOURCE_DIR` 改为该快照的实际绝对路径执行上述流程。重新 snapshot 相同输入时，输入集合的 `snapshot_sha256` 应一致；创建时间与源路径不同不要求 lock 文件整体哈希相同。

快照包含下列有效输入：

- `riscv/`、`fesvr/`、`disasm/`、`softfloat/`、`fdt/`、`spike_main/`、`debug_rom/` 下所选 `.cc/.c/.h/.hpp/.inc/.def` 文件，以及 `build/` 顶层同类文件。
- 必需的 `config.h`、`riscv/processor.cc`、`build/insn_list.h`、`spike_main/spike_lib.cc`、`debug_rom/debug_rom.h`，以及至少一份生成好的 `build/*.cc`。
- 若存在，保存 `config.h.in/configure/configure.ac/aclocal.m4/Makefile.in/VERSION/LICENSE` 等上下文文件；保存它们不等于执行了源码再生成。
- `headers/handcar_cosim_wrapper.h` 和 `force-abi/handcar_cosim_wrapper.h` 两份 ABI 头。优先取源码内副本，缺失时分别取当前 FORCE 的 `handcar/headers/` 与 `utils/handcar/` 版本并复制。

不复制 `.o/.a/.so`、编译缓存、可执行文件、普通构建日志或 `build_v2.sh`。允许的源树内部文件链接会物化为普通文件，越界链接和链接目录被拒绝，最终快照不能含符号链接。复制前后重新检查输入哈希和文件集合，源树变化会失败；快照空间要求为输入总大小再加约 16 MiB 余量。

### 4.3 旧 lock 的含义

`local-source-lock.json` 当前结构：

| 字段 | 含义 |
| --- | --- |
| `schema/recipe` | `1` / `standalone-v2-gnu20-v1`，校验器只接受当前方案 |
| `created_at/source_dir/provenance` | 快照时间、原路径、本地有效源码说明 |
| `upstream` | 必须为 `unknown`，remote/revision 为 `null`，不能伪装成官方 Git pin |
| `files` | 快照内相对文件名到 SHA-256 的映射，不含 lock 本身 |
| `snapshot_sha256` | 对按键排序序列化的 `files` JSON 求 SHA-256，不是目录名或 tar 包哈希 |
| `abi_headers` | 两份 ABI 头的快照哈希 |
| `manager_sha256/dependency_sha256` | 创建时管理器和依赖描述文件的哈希记录 |

`verify-source` 会核对 schema/recipe、未知上游声明、摘要、实际所有文件集合/哈希、选择规则和 ABI lock。添加一份说明文件到快照内部也会使集合不符；说明和新报告应放在 `WORK` 的其他目录，不要往不可变 snapshot 里写。

快照可以迁移到另一绝对路径，因为校验不要求原 `source_dir` 仍存在，也不依赖原源码/ABI 链接。这与绑定绝对运行路径的 M1 归档不同。

`manager_sha256/dependency_sha256` 是记录信息，`verify-source` 不自动要求当前工具与它们一致，也不校验 lock 每项元数据的可信作者身份。快照只是冻结有效输入，不是证明这些生成文件最初如何产生，更不是包含完整工具链的密封构建环境。

## 5. 旧版快照隔离 build

```bash
BUILD_DIR="$WORK/legacy-build"
BUILD_JOBS=4
test ! -e "$BUILD_DIR"
test -d "$WORK"
"$PYTHON" "$FORCE_ROOT/handcar/tools/manage.py" build \
  --source-dir "$SNAPSHOT_DIR" --output-dir "$BUILD_DIR" \
  --jobs "$BUILD_JOBS" --cc /usr/bin/gcc --cxx /usr/bin/g++

HANDCAR_SO="$BUILD_DIR/handcar_cosim.so"
test -f "$HANDCAR_SO"
sha256sum "$HANDCAR_SO"
"$PYTHON" "$FORCE_ROOT/handcar/tools/manage.py" verify-source \
  --source-dir "$BUILD_DIR/inputs"
```

编译器绝对路径是可替换示例，请使用真实工具位置。`--jobs` 默认为 `1`，仅控制本地编译命令并发，必须为正整数；不是回归 jobs、不是 seed 数，也不改变输入。不要为了追求并发占满系统内存。

build 可以接受未锁定有效源树，但仍会在 `BUILD_DIR/inputs` 内创建并验证独立快照。建议先显式 snapshot，便于冻结和交接。构建时要求两份 snapshot ABI 头与**当前 FORCE** 对应头哈希相同；原快照通过校验，不代表它与新版 FORCE ABI 兼容。

构建子进程使用受控环境：`PATH=/usr/local/bin:/usr/bin:/bin`、`LC_ALL=C`、`HOME=/nonexistent`，不继承 `CPATH`、`LD_PRELOAD` 等注入变量。自定义编译器用 `--cc/--cxx` 显式指定，不能假定当前 shell PATH 或 FORCE 的 `FORCE_CC` 会覆盖它。

工具会检查至少 1 GiB 可用空间，执行工具版本、目标三元组、Boost/glibc/LP64 探针，记录工具链输入，再编译冻结源码。C++ 使用 GNU C++20/PIC/O2，C 使用 C99/PIC/O2，链接静态 libstdc++/libgcc；不会调用原 `build_v2.sh`、configure 或 make 来重新生成指令源。单条外部工具调用有 600 秒超时，不提供 CLI 超时覆盖。

### 5.1 mop alias 防错与动态链接检查

已知故障形态为 `_Z18fast_rv32e_mop_r_4P11processor_t6insn_tm` 一类未解析指令符号：源码旁的陈旧 `insn_list.h` 声明 `mop_r_4`，而实际生成列表/对象只提供通用 `mop_r_N`，导致来源不一致。

管理器把 `riscv/processor.cc` 和 `build/insn_list.h` 成对复制到构建的 `generated/`，让 processor 使用同一生成列表，并只链接本轮独立 `obj/` 中的对象。修复应保持生成声明与实现一致；不能添加空实现、假 alias，或靠延迟绑定让缺符号的库表面构建成功。

链接成功还必须通过 `nm -D --undefined-only --format=posix` 和 `ldd -r`。只有 FORCE 宿主提供的 `update_generator_memory`、`update_generator_register` 两个 callback 可作为未解析的宿主强符号；有明确白名单的弱运行时符号允许存在，带版本的系统符号还需正常解析。丢失依赖、工具失败、异常输出、其他未解析 relocation 都失败。

### 5.2 构建输出

```text
build/
  inputs/local-source-lock.json
  inputs/...
  generated/processor.cc
  generated/insn_list.h
  obj/*.o
  obj/*.d
  abi-probe
  build.log
  build.json
  handcar_cosim.so
```

`build.json` 当前为 `schema: 1`、同一 `recipe`，主要字段如下：

| 字段 | 内容 |
| --- | --- |
| `status/error/started_at/finished_at` | 成功为 `passed`，进入构建记录阶段后的失败通常为 `failed` 并记录错误 |
| `source_dir/output_dir/jobs/environment/commands` | 输入/输出位置、并发、实际受控环境和命令数组 |
| `inputs/snapshot_sha256/source_lock_sha256` | 构建内部快照文件哈希、集合摘要和整个 lock 文件哈希 |
| `manager_sha256/dependency_sha256` | 本次使用的管理器/依赖文件哈希 |
| `toolchain/toolchain_inputs/abi_probe` | 工具路径/哈希/版本/C-C++ target，静态库与编译辅助程序哈希，以及探针源 |
| `compiler_inputs/linker_inputs` | `.d` 解析得到的编译输入、链接器报告的实际文件路径及哈希 |
| `validation` | undefined 符号报告、ldd 输出、实际动态运行时输入哈希 |
| `build_log/build_log_sha256/library/library_sha256` | 构建日志和成功候选库的定位与哈希 |

准备阶段的路径/工具/空间检查可能在创建目录前就失败，此时没有 `build.json`。失败后即使存在 `.so` 也不能当成功候选；先查 `status` 和 `error`。

这份记录提升可追溯性，但不是可验证签名、不是保证逐字节可复现的工具链容器。工具链、系统头文件、静态库、源输入或 ABI 变化后应新建目录重建并重新验收。`verify-source` 只检查源码快照，不会复审整个 build.json，也不会证明旁边 `.so` 就来自该快照；管理器目前没有通用 `verify-build` 命令。

## 6. build 后的验收交接

两种 build 都不改变 `utils/handcar/handcar_cosim.so` 或 `bin/handcar_cosim.so`。以下接续第 3 节的新版正常候选库，无需安装即可验收。设置真实 PTG 路径并确认显式 Zicclsm profile 已随本轮交付提供；缺少时停止补齐交付，不手工改原 XML，不静默回退到默认配置。

```bash
PTG_LIB="/absolute/path/to/page_table_generator/build/libptg.so"
M1_CONFIG="$FORCE_ROOT/config/riscv_rv64_handcar.config"
FAULT_CONFIG="$FORCE_ROOT/config/riscv_rv64_twostage_handcar.config"
FPIX_CONFIG="$FORCE_ROOT/fpix/config/riscv_rv64.config"
test -f "$PTG_LIB"
test -f "$M1_CONFIG"
test -f "$FAULT_CONFIG"
test -f "$FPIX_CONFIG"

"$PYTHON" "$FORCE_ROOT/utils/regression/run_hypervisor_m1.py" \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB" --config "$M1_CONFIG" --preflight

"$PYTHON" "$FORCE_ROOT/utils/regression/run_hypervisor_m1.py" \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB" \
  --config "$M1_CONFIG" \
  --profile smoke --jobs 4 --artifact-root "$WORK/smoke"

"$PYTHON" "$FORCE_ROOT/utils/regression/run_hypervisor_m1.py" \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB" \
  --config "$M1_CONFIG" \
  --profile m1 --jobs 4 --artifact-root "$WORK/m1"

M1_RUNS=("$WORK"/m1/m1-*)
test "${#M1_RUNS[@]}" -eq 1
M1_RUN="${M1_RUNS[0]}"
test -f "$M1_RUN/manifest.json"

"$PYTHON" "$FORCE_ROOT/utils/regression/run_hypervisor_m1.py" \
  --audit-only "$M1_RUN" --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB"

"$PYTHON" "$FORCE_ROOT/utils/regression/run_ptg_fault_v2.py" \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB" \
  --generator-config "$FAULT_CONFIG" --fpix-config "$FPIX_CONFIG" \
  --artifact-root "$WORK/fault-v2"
```

完整 M1 必须不传 `--seed`：access/fault 各固定三 seed，two_stage 为 1..100，总计 106。M1 `--jobs` 控制 case 并发；任何 `--seed` 都替换三个模板默认 seed。Fault V2 没有 `--jobs`，默认三 seed 为 `0x15c0ffee/0x5eed1234/0xc001d00d`，每 seed 330 任务；同样一旦指定 seed 就替换默认集合。

M1 只审计生成期 Handcar。Fault V2 同时给生成器与独立 FPIX 配置指定同一 `--handcar-so`，并用两阶段 `calling init:` 日志确认实际加载，不只是检查 XML。不要只换生成期库或 `ISS_SO_PATH` 就认为完成新版验收。两入口输出格式与失效边界不同，详见工作流手册。

revision2 与固化工具产物各自的 106/990 已验收记录见第 1 节。历史 revision2 的生成配置保存在 `output/spike-rebase-4ffd6ba/revision2-rv64*.config` 及相应归档中；新命令使用交付的显式 profile，不会改写旧归档或宣称旧运行已使用新文件名。分层总入口 `utils/regression/hypervisor_workflow.py` 的用法见快速上手，无需手工编辑 ISA。

## 7. 经用户授权才安装

**用户当前仍选择不安装，本节仅保留将来另行授权时的操作说明。**先向用户明确列出候选库绝对路径和 SHA-256、完整 M1 目录、Fault V2/迁移检查结果、拟替换目标及备份位置，并取得明确同意。构建任务、编写手册或用户要求 rebase 都不隐含安装授权。`--yes` 是工具层显式开关，不是代替用户授权的理由。

### 7.1 安装门禁

工具会检查：

- `--yes`、sourced 环境、Linux/glibc，以及用于安装复审的 Python 3.12。
- M1 manifest 为 schema 1、profile `m1`、`seeds: null`，case 顺序/标识/种类/seed 与当前完整 106 矩阵严格一致。
- 待安装库、M1 内归档 Handcar 与 manifest 记录三者 SHA-256 一致。
- 使用当前可信工作区的 `run_hypervisor_m1.py` 重新审计所有 106 个 case，全部通过；不会执行归档 runner，也不信任单独编辑出来的 `results.json` 中“106 passed”。
- 验收路径/文件无符号链接；实际库再次通过动态链接检查，安装期间库哈希未变化。
- 目标是现有普通文件，不是候选自身，无路径链接，并有足够磁盘空间。

安装门禁**并不检查 build.json 的来源链，也不自动检查 Fault V2 结果**。因此还需审核 upstream.lock/source.json/build.json（旧库则审核旧 source lock/build），并核对该库自己的完整验收。revision2 通过不构成用户安装授权，固化工具的新库也不能借用它的哈希或报告。

### 7.2 安装命令

仅在第 6 节产生本库的完整 M1 证据、其他必需验收结束，并且用户批准以下目标后执行。`BACKUP_ROOT` 必须先存在，应与候选构建目录、验收目录、源码/安装目录互不重叠。

```bash
BACKUP_ROOT="$WORK/backups"
ls "$WORK"
mkdir -p "$BACKUP_ROOT"
"$PYTHON" "$FORCE_ROOT/handcar/tools/manage.py" install \
  --library "$HANDCAR_SO" \
  --acceptance-dir "$M1_RUN" \
  --backup-root "$BACKUP_ROOT" \
  --target utils --yes
```

`--target utils` 是默认值，只替换 `utils/handcar/handcar_cosim.so`。只有用户明确授权两个目标时才将参数改为 `--target both`，同时替换 `bin/handcar_cosim.so`。没有仅安装 bin 的选项。

`BACKUP_ROOT` 不要设为整个 `WORK`，因为它包含构建及验收目录，会触发重叠拒绝；使用上述独立的 `backups` 子目录。工具在其下创建唯一 `handcar-install-*` 目录，先保存每个目标原始字节、哈希和模式，再写 `receipt.json`，最后逐文件原子替换并 fsync。

`both` 是两个依次执行的文件替换，**不是两文件整体原子事务**。中途失败不会自动撤销已替换目标，会打印回执路径；保留备份，检查回执后按下一节受控回滚。不要在其他进程同时更新安装库时执行安装。

### 7.3 安装回执格式

`receipt.json` 为 `schema: 1`，包含 `state/created_at/library_sha256/acceptance/targets`，失败可能有 `error`。全局状态从 `prepared` 到 `installed`，回滚后为 `rolled_back`；每个 target 有独立状态。

`acceptance` 记录运行目录、M1 manifest/results 哈希、当前审计器哈希、库哈希和 `passed: 106`。`targets[]` 记录固定安装路径、备份相对文件名（如 `0.original.so`）、`original_sha256/installed_sha256/mode/state`。原始两份库可以不同，不能用一个目标的备份覆盖另一个目标。

工具终端返回 JSON 的 `receipt` 是后续回滚的准确定位。保留整个备份目录，不要只保留 JSON。之后重新执行 M1 audit 会重写 results，回执内的 results 哈希仍是安装当时记录，不能据此伪造为一份新验收。

## 8. 受保护 rollback

用户明确授权恢复后，把 `RECEIPT` 设置为安装命令实际输出的绝对路径：

```bash
RECEIPT="/absolute/path/to/handcar-install-actual/receipt.json"
test -f "$RECEIPT"
"$PYTHON" "$FORCE_ROOT/handcar/tools/manage.py" rollback \
  --receipt "$RECEIPT" --yes
```

回滚会在写入前校验整个目标集合：仅允许当前 FORCE 的两个安装路径、备份必须位于回执同目录且哈希匹配，回执安装哈希必须一致。目标当前哈希必须仍等于当时安装的新库；若用户或其他任务后来修改过它，会报 `refusing rollback of subsequently modified target` 并拒绝覆盖。

部分安装留下的 `pending` 目标若仍是原始哈希可跳过，其他已安装目标按原始字节/模式原子恢复。已完成回滚的全局 receipt 不允许再次回滚。不要编辑 receipt 的路径、state 或哈希来强行通过保护；遇到后续修改先让用户决定如何保留和恢复。

rollback 不会把候选库或验收资料删除，也不是撤销源码变更。它只恢复 receipt 指定的安装文件；receipt 绑定当前工作区安装位置，不是任意 checkout 的通用恢复包。

## 9. 常见故障处理

| 报错/现象 | 正确处理 |
| --- | --- |
| `output must be new` | 目标连空目录都不能存在；保持父目录存在，改用新的 snapshot/build 目标名 |
| upstream `input hash mismatch` / `pin/url mismatch` | 核对版本化 lock、patch、native tests 和 loader 头是否来自同一交付；不能修改锁值或伪造官方 remote 来绕过 |
| upstream source/index/tree 不匹配 | `--source-dir` 指向 prepare 父目录；不要在 source 内编译、stage 或改文件，新目录重新 prepare |
| `unsafe output overlap` / `symlink path` | 使用 `output/` 下独立真实目录，不把输出放回 source、handcar 或安装目录内；核对所有父路径 |
| 旧 manage `missing required input` / `missing generated instruction sources` | 历史重建需要完整旧快照；新版改走 upstream prepare/build，不给旧 manager 塞入纯官方 clone |
| `source changed during snapshot` / 文件集合不一致 | 停止并发改源，保留失败输出，重新冻结到新目录；不能删改 lock 绕过 |
| `snapshot ABI differs from current FORCE` | 核对两份 wrapper 声明及调用端布局/签名，决定统一 ABI 后重建；只改哈希不是 ABI 修复 |
| `missing tool`、Boost/静态库/LP64 探针失败 | 检查本机工具链、开发依赖、编译目标；环境注入被清理是设计行为 |
| `mop_r_4`/`mop_r_N` 未解析 | 核对 generated 列表与实现同源、processor 使用 build 列表、不混旧对象；见第 5.1 节 |
| `ldd`/`nm` 失败或 `not found` | 先修运行时依赖；只有明确宿主 callback 可留给 FORCE 解析，不能忽略整份 stderr |
| `full default M1 profile required` | 重跑不带 seed 覆盖的 `--profile m1`，smoke/自定义矩阵/Fault V2 都不适用 |
| `M1 library hash mismatch` / 复审失败 | 找到该候选库自己的完整证据；新构建即使源码相近也不可借用另一哈希的结果 |
| 新版跨页/非对齐访问 trap | 检查生成期是否显式选了 `_handcar.config` 的 `_zicclsm` ISA；不要让 wrapper 隐式开扩展 |
| 未知地址 store fault / attrs 状态 9 | 先核对宿主 RAM backing 声明；attrs 输出未支持，PA-only 调用传空指针，不能将故障改成假成功 |
| summary 全绿但 loader/audit 失败 | 以实际进程 `calling init:`、输入哈希和语义审计为准，不能用搜索路径或退出码 0 充当验收 |
| 安装中断或 rollback 拒绝 | 保留 receipt/原库/当前库；按状态和哈希核对，不能直接 `cp` 或改 receipt 覆盖用户后续修改 |

可对可信本地候选库手工辅助诊断，但这些命令不替代工具门禁：

```bash
nm -D --undefined-only --format=posix "$HANDCAR_SO"
ldd -r "$HANDCAR_SO"
sha256sum "$HANDCAR_SO"
```

独立 `ldd -r` 看到两个宿主 callback 未解析可能是预期现象；必须区分其他符号错误。M1 已将 `LD_DEBUG=libs` 合并到 case 的 `command.log`，Fault V2 使用 `loader/trace.<pid>`，优先检查这些真实运行证据，不另写一份只展示“准备加载”的脚本。

## 10. 单元测试与长期方案

在已 source 的 Bash 中执行工具测试：

```bash
"$PYTHON" -m unittest discover -s "$FORCE_ROOT/handcar/tools" -p test_upstream.py -v
"$PYTHON" -m unittest discover -s "$FORCE_ROOT/handcar/tools" -p test_manage.py -v
"$PYTHON" -m unittest discover -s "$FORCE_ROOT/utils/regression/tests" -p test_hypervisor_m1.py -v
"$PYTHON" -m unittest discover -s "$FORCE_ROOT/utils/regression/tests" -p test_ptg_fault_v2_runner.py -v
```

upstream 的离线夹具测试覆盖 pin/patch/头文件、镜像不变、source/index/mode/额外文件篡改拒绝、失败保留、构建命令、编译器探针、开发仓库 remote 命名和 ASan 范围；它们不联网、不进行完整 upstream native build。真正的 `upstream_mmu_checks.cc`、`upstream_abi_checks.cc` 由第 3 节 build 自动编译运行。旧管理测试覆盖快照、native 小夹具、伪造 106 PASS 拒绝、同库哈希、部分安装回滚和用户后续修改保护。测试不安装工作区库；工具级通过不替代实际库的完整 M1/Fault V2。

未来推荐将 Handcar 适配源码、可重复的生成规则、补丁历史和 ABI 测试放入**独立 Handcar 仓库**，FORCE 通过 **submodule 固定其具体提交**，另行记录官方 Spike 基线、工具链及构建/验收产物哈希。需要先获得用户确认的真实远端、访问权限和迁移策略；现在不能杜撰 remote URL、提交号或“submodule 已完成”。

建议迁移顺序：

1. 保留 revision2 候选及完整证据；旧 snapshot/原安装库保留历史恢复用途，不再充当新版源码获取前提。
2. 使用版本化官方 pin 加 patch 从 clean prepare 重建，保留 source.json/build.json，完成该固化工具产物自己的验收，不挪用 revision2 结论。
3. 将 lock、patch、工具、测试和显式 ISA profiles 随源码交付，验证新会话流程，列明本手册的支持边界；用户当前不安装的选择继续有效。
4. 获得独立 Handcar fork remote 后再整理独立仓库并接入 FORCE submodule，固定实际提交。在此之前，官方 commit 加版本化 patch 就是当前来源模式，不伪称 fork/submodule 已完成。

旧 `dependency.json` 的本地未知来源与新 `upstream.lock.json` 的官方 pin 分别保持真实，不互相覆盖。干净 checkout 可重现新版源码，不等于二进制位级一致、全部 Hypervisor 支持、完整回归通过或用户授权安装。
