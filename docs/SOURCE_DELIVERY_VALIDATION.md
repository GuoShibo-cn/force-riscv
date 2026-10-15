# 开发分支交付前：暂存源码树冷构建验证

## 结论

已从实际暂存树导出独立源码目录，重新构建 FORCE、SimAPI、FPIX、seedgen，并从固定
源码重新构建 PTG 和 Handcar。使用仓库正式配置完成 full，而非复用本机旧候选 XML。

验证代码树：`be75afaca605900ee2d3e7a7b1ea86f56c49ccb0`。验证后的交付收尾只增加本文及
文档状态更新；实现、配置与测试保持该验证树的内容。

| 检查 | 结果 |
| --- | --- |
| FORCE / SimAPI / FPIX / seedgen 源码构建 | 通过 |
| Handcar pin + patch 冷构建、native MMU/ABI、局部 ASan | 通过，source_unchanged=true |
| PTG 固定源码 shared 构建 | 通过，库哈希与此前 dfee 候选一致 |
| 工具单测 | 157 项通过 |
| ctypes / M1 | 52/52、106/106 |
| Fault V2 独立 ELF 执行和语义审计 | 990/990 |
| 上下文合同 / 上下文 ELF / C++ mapper ELF | 12/12、3/3 seeds、3/3 seeds |
| 两组历史 native 定向测试 | TwoStageTranslationUnit、TwoStageAllocation 通过；后者还加载新 Handcar 执行检查 |

本机原始记录：`output/push-validation-2f9874f/`，最终工作流为
`accepted/full-axxi62ra/workflow.json`。这些原始构建/运行产物不随 Git 推送，复跑入口见
[HYPERVISOR_BUILD_FROM_SOURCE.md](HYPERVISOR_BUILD_FROM_SOURCE.md)。
这是受限开发版本的交付验证，不是完整 Hypervisor、任意 ELF 或所有 PTG stress 的支持声明。

## 依赖身份

PTG 来自独立 SSH clone 的已发布 commit
`addd85d973dd5bac9d0e0580e0ade7c32888b48c`；include/src/Makefile 相对该 commit 无修改。
使用 `BUILD_DIR` 指向独立目录，不修改维护者已有工作区或旧库。
Handcar 从 lock 的官方 `4ffd6ba...` 加 patch `daa1fc93...` 构造源码，不读取 dev-spike
工作区的未提交改动；本轮借助其官方 Git 对象作为 prepare 镜像缓存。

| 冷构建产物 | SHA-256 |
| --- | --- |
| friscv | `5bc76e7af91e08095627e3f2a456308a5f7bbbe60ad4cdf4ace2f38e58168d7f` |
| SimApiHANDCAR.so | `b99736d154530bd221dbe07cc13fd4cf6dfcfbaa0d317c329d5f401f433bd86a` |
| FPIX | `88f9e92f9a07cab11c4d50d545c3030f200f77c8de51e40e7a26838b6e11eb69` |
| Handcar | `bd0ac281ee64420f8a922914f76f24b3fe7d3b7584588c80082988747fb835f7` |
| PTG | `dfee221f7417e950ee1ca93c9a8df697148c5ed50359590e5a82148f0646b082` |

FORCE/Handcar 哈希与旧构建不同，记录各自身份，不要求不同构建目录/环境字节一致。

## 冷构建暴露并修复的问题 F006

分类：FORCE 默认配置问题，不是 PTG bug。

旧正式 `riscv_rv64_twostage_handcar.config` 声明 `RV64IMAFDCH`，FPIX Hypervisor profile
声明 `RV64IMAFDCVH`。之前本机隔离 XML 两边都含 V，因此掩盖了正式配置的差异。

最小场景为 guest-explicit 的 trap 后读取 mstatus：

```text
generation: x9 = 0x800000ca00006980
FPIX:       x9 = 0x800000ca00006f80
```

差异 `0x600` 是 mstatus.VS 位；不同 ISA 声明造成 WARL 字段不同。首次源码验证在
`acceptance/full-2qw90_uv` 正确失败，日志和报告保留。

已使正式生成配置和 FPIX 的 ISA 完全一致，并添加 `test_default_profiles_keep_isa_consistent`。
没有屏蔽 VS 位、放宽寄存器比较或把失败计为通过。V 的声明一致不等于 FORCE vector
数据接口已完整实现。修复后用同一组新构建产物重跑 full，全项通过。

此外修复 FPIX Makefile 的 usage.h 生成依赖顺序，避免干净构建在生成依赖文件时先报
missing usage.h；移除验证副本中生成的 header 后重建，顺序正确且没有该错误。

## 交付整理

首次直接推送本地历史被 GitHub 拒绝：早期历史包含约 189 MB 的 Handcar 库。因此发布时
从官方 master `5b66fd574c3aef3592cfcb6c6a112a040b127f36` 创建单独的干净交付提交。
本地原历史保留在 `feature/hypervisor-phase3`（交付整理提交 `d77cdc6`），未重写。
干净交付树相对该本地提交只省略根目录 sim.log/示例 ELF/S，并保留官方基线的预置库；
其余实现、配置、测试与上述已验证源码一致。验收始终使用显式冷构建 Handcar，不使用预置库。

- 恢复 pybind11 2.12.0 的上游 LICENSE。
- 把被历史反馈引用的独立复现源移至 `tests/riscv/ptg_fault_v2_legacy_repro.cpp`。
- 提交 AGENTS.md、实现/测试和项目文档；排除 .opencode、会话状态、当前 dirty 库和日志。
- 旧文档/根目录示例生成物的本地删除未混入本次功能提交，实验模板改动仍留待单独整理。
- Handcar submodule 仍是方案草案，本次继续交付有效的 pin + patch 构建输入。
- 本地没有安装 pre-commit hook/Black，本次未跳过任何已安装 hook；格式配置升级另行处理。
  普通暂存差异的 whitespace 检查通过，patch 内四个统一 diff 空白上下文前缀仍保留，
  其可应用性由本次 prepare/build 验证。
