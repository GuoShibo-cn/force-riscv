# 从源码构建并验收 PTG-first Hypervisor 开发版本

本页用于新 checkout；不依赖文档中历史 `output/.../friscv-v5` 或隔离 XML。
当前交付仍是 Handcar 官方固定 pin + 版本化 patch；submodule 迁移尚未实施。
完整 Hypervisor 支持尚未完成，当前 C++ mapper 是已发布 RW 数据映射子集。

## 环境

- Linux/glibc，Python 3.12 及开发头/库。
- GCC/G++，其中 Handcar 构建需要 GNU C++20；make、binutils、Git、Boost 开发包、dtc。
- 以下命令在 **Bash、全新 FORCE checkout 根目录** 执行。
- 不执行根 `make tests`，它会删除 output。已有 dirty binary 的开发目录请继续使用
  隔离构建目标，不套用本页面向新 checkout 的默认 bin 构建命令。

## 1. FORCE、SimAPI、FPIX 和 seedgen

```bash
source ./setenv.bash
export PYTHONDONTWRITEBYTECODE=1
export FORCE_CC=g++
export FORCE_PYTHON_VER=3.12
export FORCE_PYTHON_INC="$(python3.12 -c 'import sysconfig; print(sysconfig.get_path("include"))')"
export FORCE_PYTHON_LIB="$(python3.12 -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')"

make -C riscv -j8
make -C fpix/riscv -j8
make -C utils/regression/seedgen -j8 all
```

第一条构建 friscv 和 `bin/SimApiHANDCAR.so`；这些目标不重新生成 Handcar 核心库。
源码中包含 pybind11 2.12.0 版本宏；其 BSD 许可文件已从上游 v2.12.0 LICENSE 补回。

## 2. 新建本轮证据目录

```bash
mkdir -p output
WORK="$(mktemp -d "$PWD/output/source-check-XXXXXX")"
```

目录名必须是新的且不包含空格；它用于构建产物与证据，不纳入源码提交。也可使用已存在
output 父目录内的新子目录，保持每轮 source/build/acceptance 路径不复用。

## 3. PTG 固定源码

PTG 的 checked allocation / Query / Strict Export 已发布为：
`addd85d973dd5bac9d0e0580e0ade7c32888b48c`。

```bash
git clone git@github.com:GuoShibo-cn/page_table_generator.git "$WORK/ptg-source"
git -C "$WORK/ptg-source" checkout --detach addd85d973dd5bac9d0e0580e0ade7c32888b48c
make -C "$WORK/ptg-source" -j8 BUILD_DIR="$WORK/ptg-build" shared
PTG_LIB="$WORK/ptg-build/libptg.so"
```

需要该仓库的读取权限和已配置的 Git SSH 认证；也可使用维护者提供的同 commit 源码包。
不要在维护者原有 dirty 工作区重建替换候选库。本步骤使用独立 checkout 和输出目录。
源码 commit、编译选项与 library hash 分别记录；不要求不同编译环境产物等于历史 dfee 哈希。
PTG 当前仍有已记录的范围外 stress 限制，完整边界见需求台账。

## 4. Handcar 固定 pin + patch

```bash
python3.12 handcar/tools/upstream.py prepare --output-dir "$WORK/handcar-source"
python3.12 handcar/tools/upstream.py build \
  --source-dir "$WORK/handcar-source" --output-dir "$WORK/handcar-build" --jobs 8 --asan
HANDCAR_SO="$WORK/handcar-build/handcar_cosim.so"
```

有官方 Spike 本地镜像时，可在 prepare 增加 `--mirror /path/to/official-mirror`；其 remote
和 pin 会被校验，不读取镜像工作区的本地改动。build 包含 native MMU/ABI 与局部 ASan，
不安装或覆盖 `utils/handcar/handcar_cosim.so`。

## 5. 完整集成验收

```bash
python3.12 utils/regression/hypervisor_workflow.py --profile full \
  --friscv "$PWD/bin/friscv" --fpix-bin "$PWD/fpix/bin/fpix_riscv" \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_LIB" \
  --m1-config "$PWD/config/riscv_rv64_handcar.config" \
  --generator-config "$PWD/config/riscv_rv64_twostage_handcar.config" \
  --fpix-config "$PWD/fpix/config/riscv_rv64_hypervisor.config" \
  --artifact-root "$WORK/acceptance" --jobs 8
```

应检查 workflow.json 的 passed，以及各子报告：106 M1、990 Fault V2 独立重放/语义审计、
12 项托管上下文合同、三 seed 上下文和三 seed C++ 自动选址专项。数量来自当前固定矩阵，
不能只看某一份 trace 的 SUCCESS。旧历史 990 runner PASS 不自动升级成此验收证据。

## Agent 接续

先读 AGENTS.md、HYPERVISOR_QUICKSTART.md、当前开发计划和 PTG_CPP_MAPPER_INTEGRATION.md。
当前路线是 PTG-first；不安装已有 dirty 库，不清理别人的改动，不提交 .opencode/ 或运行状态。
历史文档和旧日志保留原时间/库身份；本页是源码重建入口，不是新的测试通过声明。
