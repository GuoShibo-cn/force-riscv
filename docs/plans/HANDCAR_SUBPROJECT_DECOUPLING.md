# Handcar / Spike 子项目与解耦方案（建议稿）

## 状态

用户明确：`.opencode/` 全部不进入本轮提交范围，AGENTS.md 和项目 docs 仍属于交付内容。
本篇记录 Handcar 子项目方案，**尚未执行仓库发布、submodule 转换、构建迁移或 ABI 改版**。
迁移完成前，现有 `handcar/upstream.lock.json` + versioned patch 继续是实际构建入口。

## 1. 推荐目标

采用 **独立 Handcar 仓库（保留 Spike 上游历史的 fork）+ FORCE Git submodule 固定引用**。
Handcar 负责 ISS 库及其必要的 Spike 定制；FORCE 只消费库接口和版本化构建产物。

建议新布局：

```text
handcar 独立仓库
  riscv/, spike_main/, ...     Spike 源码与小范围定制
  include/handcar/             唯一公共 C ABI 定义（目标布局）
  tools/ 或 build scripts      独立构建入口
  tests/                      不依赖 FORCE 源码的 native/ABI 测试

force-riscv
  .gitmodules
  external/handcar/            submodule，指向 Handcar integration commit
  utils/handcar/               FORCE-specific SimAPI adapter/loader
  handcar/                    依赖编排、兼容要求和历史资料
  py/riscv/, base/, riscv/     PTG/生成器集成
  utils/regression/            跨组件验收
  docs/, AGENTS.md             FORCE 项目规则和集成说明
```

`external/handcar` 是建议路径，避免把已有、包含工具和历史源码的整个 `handcar/` 目录
直接变为子模块。现有 `handcar/dev-spike` 是开发 checkout，不自动改作版本引用。

## 2. 已核对的现状

- `handcar/dev-spike/` 已是独立 Git 仓库，当前分支 `handcar/force-integration`。
- `master` 跟踪官方 `upstream/master`，固定基线 `4ffd6ba860f4190ceac2716fa3c2cf139e85538f`。
- integration HEAD 为 `3cd61c76d87a10eadb4e1b6d763de6b8d837c903`；尚无发布 origin。
- `riscv/processor.cc` 还有 16 行未提交的 trap observer 改动。只 pin 旧 integration HEAD
  无法表示当前已验收的新 trace 能力。
- FORCE 目前通过官方 pin + patch prepare，再构建库；不能直接将该流程替换为未经验证的
  dev checkout，也不能把未提交工作区冒充远程可获取版本。
- `handcar/tools/upstream.py` 当前持有库的编译/链接配方，并复制 FORCE 内的测试与
  `utils/handcar/SimLoader.h`；仅增加 submodule 不会自动解除这些耦合。

## 3. 源码归属

| 内容 | 目标归属 |
| --- | --- |
| Spike MMU/processor/sim 修改，稀疏 RAM 与 trap hook | Handcar 独立仓库 |
| `spike_main/spike_lib.cc` 等 C 库 wrapper | Handcar 独立仓库 |
| 纯 Spike/MMU 行为测试及独立库构建 | Handcar 独立仓库 |
| `SimApiHANDCAR.cc/.h`、FORCE loader 和日志适配 | FORCE |
| `PtgVmMapper`、Python PTG backend/context、内存镜像同步 | FORCE |
| FPIX、ELF/地址生成审计、Hypervisor full 工作流 | FORCE |
| Handcar 原生 ABI 测试 | Handcar，使用公共 ABI 头 |
| 使用 FORCE 实际 loader 类型的兼容测试 | FORCE，继续检查真实消费端 |

现有 `upstream_abi_checks.cc` 包含真实 FORCE loader 类型验证，不应整份无区分搬走。
应拆出供应方自测和消费方兼容检查；`upstream_mmu_checks.cc` 的内部 MMU 验证更适合
Handcar 自己维护。测试边界跟随责任，而不是简单按当前目录移动。

## 4. 真正的解耦点

### 4.1 公共 C ABI

目标是 Handcar 可独立构建、加载和测试，不包含 FORCE 的 C++ 类型/头文件，不访问 PTG。
公共头只使用固定宽度整数、opaque handle、明确的缓冲区与状态码合同。

当前两个强外部回调是 `update_generator_memory` / `update_generator_register`，另有
可选弱 trap observer。中期建议改为显式 callback table 注册，包含 `struct_size`、
`abi_version`、`user_data` 与 memory/register/trap callback，逐步消除宿主符号隐式解析。
这样独立测试不再必须伪造 FORCE 同名导出函数或依赖 `--export-dynamic`。

补充明确的 ABI version / capabilities 查询。能力不等于符号存在；single-hart、vector、
events 等支持范围需可判断。不把当前 stub 的返回 0 当作实现证明。
仓库迁移首轮保持现有 ABI，callback 改版是后续单独迁移，不能与移动仓库一次性混改。

### 4.2 构建产物

Handcar 独立构建建议输出一个 SDK 布局：

```text
include/handcar/handcar.h
lib/handcar_cosim.so
manifest.json
```

manifest 记录源码 commit、上游基线、编译器/选项、ABI 和库哈希。FORCE 编排工具只负责
选择固定源码、调用 Handcar 构建入口、验证产物和运行集成验收，不继续维护另一份
wrapper/static archives 链接配方。继续允许显式 `--handcar-so`，便于候选对比和回归。

### 4.3 测试与语义

Handcar 自测负责 MMU、内存后端、寄存器访问、step/trap ABI；FORCE 自测负责生成器状态、
PTG 装载、ELF 重放及场景断言。升级 Handcar 后，两层都要运行，submodule pin 本身不是验收。
现有 106 M1、990 Fault V2 和上下文/C++ mapper 专项作为跨组件检查保留。

## 5. 版本引用规则

- FORCE 的子模块 gitlink SHA 是源码版本的唯一选择，不在 lock 中手工维护另一个可能
  不同的 Handcar commit。兼容配置可另记所需 ABI/capabilities；上游基线由 Handcar 记录。
- 不自动跟随分支 HEAD；升级子模块就是 FORCE 中一笔显式 dependency bump。
- 官方 master 保持纯上游，定制在 integration branch。开发分支可受控 rebase，但被
  FORCE 引用的发布 commit 必须保持可获取，使用不可变 release refs/tags 保留。
- `.so` 是构建/发布产物，子模块不负责分发机器本地二进制。已有 tracked 脏库不随此
  方案自动替换、取消跟踪或删除；其默认安装策略另行迁移。
- 稳定后，旧 patch 可留作历史，但不能与 fork commit 同时成为活动源码输入，避免
  “子模块 checkout 后再叠 FORCE patch”产生双重版本事实来源和脏子模块。

## 6. 建议迁移顺序

1. 明确 Handcar 发布仓库位置；审查并在独立仓库保存当前 wrapper/MMU/trap 改动。
   先取得包含已验收能力、可远程拉取的固定 commit。发布/提交动作另需用户明确授权。
2. 首轮保持 ABI 和功能行为，形成 Handcar 单独 checkout 能运行的构建与基础自测入口。
3. FORCE 新增子模块引用，并增加使用该源码/SDK 的构建模式。旧 pin+patch 暂时保留为
   显式兼容模式，两个模式不能混用同一验收身份。
4. 在新目录构建、运行完整 FORCE 验收及独立 Handcar 自测。功能/语义对照通过后，
   将日常入口切到子模块；更新 quickstart、依赖说明、agent 规则和 CI 初始化方式。
5. 后续单独完成公共头统一、version/capability 与 callback registration 改版，再逐步
   移除活动构建对 FORCE 私有头和宿主隐式符号的依赖。

每阶段都可独立审查和回退，避免把“源树搬家、ABI 重写、上游升级、行为变化”合在一起。

## 7. 对当前提交清单的影响

若先完成解耦：Spike/Handcar 核心提交进入独立仓库；FORCE 提交 submodule 指针、consumer
adapter、PTG/FPIX/runner 和项目文档。这样之后的常规 FORCE 提交不再携带大块 Spike patch。

若先保存当前 FORCE 开发成果：现有 patch + lock + tests 必须仍成组提交，因为当前
工具依赖它们。后续再做子模块迁移，不可提前漏交构建输入。

当前待确定的是发布仓库 URL；本方案没有创建远端、修改 remote、提交、推送或重写分支。
