# Spike / Handcar 分支维护

## 当前布局

独立开发仓库位于 `handcar/dev-spike/`，不在会被根 `make tests` 删除的 `output/` 下。
该目录由 FORCE 忽略，不能把它作为普通源码目录 `git add` 到父仓库，也尚不是 submodule。

| 对象 | 作用与当前值 |
| --- | --- |
| `upstream` | 官方 `https://github.com/riscv-software-src/riscv-isa-sim.git`，只获取历史 |
| `master` | 跟踪 `upstream/master`，当前 `4ffd6ba860f4190ceac2716fa3c2cf139e85538f` |
| `handcar/force-integration` | 定制分支，当前 `3cd61c76d87a10eadb4e1b6d763de6b8d837c903` |
| `origin` | 尚未设置；将来由用户提供自己的 Handcar fork 远端 |

本地定制提交的 tree 为 `2489cd9f7a47d9c9759702488f5f2e6522c23c2c`，与既有
`output/handcar-pinned-source/source.json` 中已验收 tree 完全一致。本次没有重新设计
补丁，也未移除旧 wrapper 的尾随空格或已记录诊断输出，避免改变已验收输入。
这些既有格式问题可在独立后续提交中处理；不要把 `git diff --check` 的警告误报为通过。

`handcar/development.json` 记录这份初始本地提交。`handcar/upstream.lock.json` 继续是
FORCE 构建的版本事实来源，不能直接改为依赖一个没有远端可获取的本地 commit。
定制分支用于开发，pin + patch 用于当前可交付、可复现构建，两者职责不同。

## 定期同步与 rebase

不自动定时改写正在开发的分支。每次决定更新时，在 Bash 中执行以下步骤；
`set -e` 确保冲突或失败后停止，不继续导出半完成结果。命令使用 `git -C`，避免误操作
FORCE 自己的 `master`。

```bash
set -eo pipefail
FORCE_ROOT="$(pwd)"  # 当前必须为 FORCE 仓库根目录。
SPIKE="$FORCE_ROOT/handcar/dev-spike"
test -d "$SPIKE/.git"
test -z "$(git -C "$SPIKE" status --porcelain)"
test "$(git -C "$SPIKE" remote get-url upstream)" = \
  "https://github.com/riscv-software-src/riscv-isa-sim.git"

git -C "$SPIKE" fetch upstream
git -C "$SPIKE" switch master
git -C "$SPIKE" merge --ff-only upstream/master

BACKUP="backup/handcar-$(date -u +%Y%m%dT%H%M%SZ)-$$"
git -C "$SPIKE" branch "$BACKUP" handcar/force-integration
git -C "$SPIKE" switch handcar/force-integration
git -C "$SPIKE" rebase master
git -C "$SPIKE" log --oneline master..HEAD
git -C "$SPIKE" diff --stat master...HEAD
```

`master` 不承载本地提交；`merge --ff-only` 拒绝分叉而不是生成合并提交。
本轮官方 master 没有新提交，因此无需做空 rebase。以后 rebase 有冲突时先审查并修复；
不确定则 `git -C "$SPIKE" rebase --abort`，保留 backup 分支，不用 hard reset 清理。
提交身份可沿用 FORCE 的作者信息；不要为脚本修改全局 Git 配置或跳过 hooks。

## 更新 FORCE 锁定版本

rebase 成功只表示 Git 冲突解决，不等于新模拟器正确。先记录新 base、定制 commit/tree，
对比 `git range-diff`，检查 MMU/CSR/ABI API 的上游变化，再做新的构建和验收。

1. 从干净的定制分支导出 `git diff --binary master..handcar/force-integration` 到新的补丁文件。
   只导出相对新 base 的定制，不能带编译产物、日志或无关源码。
2. 在 FORCE 专门的更新任务中同步 `upstream.lock.json` 的 base、补丁路径及 SHA-256，
   并同步 `upstream.py` 的受控 `PIN`、补丁路径检查及相关测试。当前工具故意不跟随动态 master。
3. 在新输出目录运行官方 `prepare/build --asan`，再运行 `hypervisor_workflow.py --profile full`。
   使用显式的 Handcar/PTG 库；旧库的哈希证据不能套用到新库。
4. 通过后再提交 FORCE 的 lock、补丁、测试和状态文档。失败则保留新分支/日志供排查，
   FORCE 继续使用上一个已验收 lock，不自动覆盖安装库。

当前锁定版本可使用开发仓库的 Git 对象作为缓存：

```bash
source ./setenv.bash
mkdir -p output
python3.12 handcar/tools/upstream.py prepare \
  --mirror "$PWD/handcar/dev-spike" \
  --output-dir "$PWD/output/handcar-prepare-from-dev-new"
```

该命令只取固定官方 Git 对象并应用锁定补丁，不复制开发分支上的未验收变化。
输出目标必须全新；不要把可编辑的 `dev-spike` 直接传给要求不可变 prepare 输入的 build。

## 远端发布与备份

当前定制 commit 仅在本机。用户提供 Handcar fork URL 并明确要求推送后，才添加
`origin` 并发布 `master` 和 `handcar/force-integration`；不向 `upstream` 推送。
之后可让 FORCE 使用该 fork 的固定 commit 接入 submodule 或 repo manifest。

rebase 会重写定制提交。若分支已被他人使用，先协调；优先发布新的版本分支。
只有明确授权并确认远端状态后，才考虑带 lease 的历史更新，绝不自动 force-push。

没有远端时，可以在仓库外备份 `git bundle`；忽略目录不等于已有备份。要在新机器保留
原始本地 commit ID，需带走其对象库/bundle；仅从已跟踪的 patch 重新提交，可以得到
相同源码 tree，但作者/时间不同会得到不同 commit ID。
