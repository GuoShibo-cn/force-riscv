# Handcar 上游迁移状态

## 当前结论

同一 PTG/Handcar 组合已通过 [C++ 数据 mapper](PTG_CPP_MAPPER_INTEGRATION.md) 验收。
本次新构建的是隔离 friscv-v5，增加自动数据选址和 native reload 保护；Handcar 核心未改。

同一候选另通过 [GenThread 上下文闭环](PTG_MANAGED_CONTEXT_INTEGRATION.md)：原 106 M1、
990 Fault V2，外加 12 项上下文合同及 3 seed 双地址空间 ELF 审计。只验证单 hart、
M-mode 发起的 HLV/HSV 与全局 fence 协议，不外推到选择性 TLB/多 hart 或完整虚拟机调度。

同一 Handcar `3af0cb33...` / PTG `dfee221f...` 又完成
[placement 生产集成](PTG_PLACEMENT_PRODUCTION_INTEGRATION.md)：52 ctypes、106 M1、
990 ELF 语义审计通过。本次只更新 FORCE Python 适配和模板，没有升级 Handcar 核心。

**最新 trace 修复：** 指令 PC/next-PC 分离与 Spike 实际 trap 诊断事件已在新隔离库
`3af0cb33...` 验证，详见 [trace v2](HANDCAR_TRACE_V2_VALIDATION.md)。新库的 106 M1 和
日志/汇编核对通过。另已确认旧 FPIX 缺 H、提前异常仍报 SUCCESS，故历史 990 ISS
计数不能作为完整 ELF 场景重放证明。该缺口随后已在新 FORCE/FPIX 修复，重新生成的
990 份 ELF 通过完整场景审计，见 [FPIX 重放验收](FPIX_ELF_REPLAY_ACCEPTANCE.md)。

最新 PTG 候选更新：`dfee221f7417e950ee1ca93c9a8df697148c5ed50359590e5a82148f0646b082`
与同一隔离 Handcar 组合通过 checked allocation/placement 下游验收、实际预留池、
独立 ISS 和 FORCE full，见[验收反馈](PTG_ALLOCATION_PLACEMENT_ACCEPTANCE_FEEDBACK.md)。
它 supersede 维护者旧 2df 候选，B003/B004 修复通过；不是 Handcar pin 更新，也不是
通用 allocator/多 hart/回收或生产 placement 绑定已经完成。下列旧哈希证据保留原身份。

2026-09-19 PTG 依赖增量：维护者候选 `libptg.so` SHA-256
`8a56c462624b3cf7b1636b0021913ba0bf8e10a863910fef4c224997c05bcca0` 与本页隔离 Handcar
组合通过 FORCE full、新查询/严格导出下游检查及独立 ISS；见
[验收反馈](PTG_MAPPING_EXPORT_V1_ACCEPTANCE_FEEDBACK.md)。这不改变 Handcar pin/库，
也不表示生产 adapter 已迁移。旧 PTG 哈希的下列历史证据仍只绑定当时输入。

同日后续已正式绑定 Query/Strict Export v1，并迁移首批正常/guest-scope 模板；
`output/ptg-v1-production/full-isp_35fv/workflow.json` 的 106/990 及 32 ctypes 通过。
布局失效/关闭、全部 pull 后才写入及错误传播边界见
[生产适配说明](PTG_V1_PRODUCTION_INTEGRATION.md)。仍未接通 PTG-backed C++ Mapper，
也未完成所有 legacy 模板、通用地址池/RAM 集成。Handcar 与 PTG 库保持本轮验收身份。

2026-09-20 M1 access 模板使用首期 FORCE-reserved PTG table pool，40 ctypes、106 M1、
990 generation/ISS 和三 seed 实际 reservation 检查通过，见
[地址池适配](PTG_RESERVED_POOL_INTEGRATION.md)。新独立复现的 PTG B003/B004 分配问题
仍开放；不改变此前 Query/Strict Export 限定验收，也不升级多 context/通用 allocator 支持。

2026-09-05 核对官方 `master` 后，已将 Handcar 定制移植到
`4ffd6ba860f4190ceac2716fa3c2cf139e85538f`，并完成隔离冷构建及限定范围验收。
官方地址为 `https://github.com/riscv-software-src/riscv-isa-sim.git`。

这不是在旧 `standalone-v2` 上执行 Git 历史 rebase：旧目录没有独立 Git 历史且混有不同
上游版本。本轮使用独立官方 checkout，重新移植定制并导出完整补丁，没有提交、推送或
重写 FORCE 历史，没有替换安装库。没有建立 Handcar 远端 fork 或 submodule。

后续提交阶段已按用户要求建立 `handcar/dev-spike` 独立开发仓库并提交定制：
`master=upstream/master=4ffd6ba860f4190ceac2716fa3c2cf139e85538f`，
`handcar/force-integration=3cd61c76d87a10eadb4e1b6d763de6b8d837c903`。
其 tree 与下列已验收源码逐字节一致。此更新只建立本地提交，未推送、未安装；
完整维护方法见 [分支手册](HANDCAR_BRANCH_WORKFLOW.md) 和 `handcar/development.json`。

## 可复现输入

- `handcar/upstream.lock.json`：官方 commit、补丁、测试及消费端头文件 SHA-256。
- `handcar/patches/spike-4ffd6ba-handcar.patch`：完整定制，不依赖旧 ignored 源码。
- `handcar/tools/upstream.py`：独立 prepare、官方 configure/make 再生成、构建和检查。
- `handcar/tests/upstream_mmu_checks.cc`、`upstream_abi_checks.cc`：定向 MMU/ABI 检查。
- 两份 `_handcar.config`：通过 import 继承原配置，仅显式覆盖 ISA 的 Zicclsm。

上述输入已在 FORCE `97e01c3` 中跟踪；交付时必须包含这些文件，不能只转交 `output/`。
补丁 SHA-256：`52e0a9929cc31b24b45c0a934b98a266b1bf5788d77f889e52f047d32dff27ce`。

## 本机最终证据

| 内容 | 路径/结果 |
| --- | --- |
| 迁移前有效输入快照 | `output/handcar-pre-rebase-snapshot` |
| 固化工具准备的源码 | `output/handcar-pinned-source` |
| 固化工具最终构建 | `output/handcar-pinned-build-v2` |
| 冷构建、符号和定向检查 | `build.json` 的 `status=passed`、`source_unchanged=true` |
| ASan/LeakSanitizer | wrapper + ABI caller 通过；不是全部 Spike 插桩 |
| 完整 M1 | `output/handcar-pinned-m1/m1-i0wa378x`，106/106，通过同哈希 audit-only |
| Fault V2 | `output/handcar-pinned-fault-v2/run_gtxq3__m`，ctypes 8/8，990/990 generation 和 990/990 ISS |
| 最终 full 总入口 | `output/handcar-workflow-validation/full-7m1yahyx/workflow.json`，返回 0；143 项工具单测、预检、smoke、106 M1 和 990 双执行阶段全部通过 |

最终库：`output/handcar-pinned-build-v2/handcar_cosim.so`。
SHA-256：`a1013545508251676b63ec93686cd305a7c7140a1795887193a11061e3529224`。
不同构建路径/工具链不保证产生相同二进制哈希；新库必须重新绑定验收，不能套用旧清单。

原安装库 `utils/handcar/handcar_cosim.so` 与 `bin/handcar_cosim.so` 保持
`8ebad9706aeff632f18b5a77fb803829b687c25b95469e26b3f8eed8428ea786`。
用户已选择保留隔离版，后续任务不能把“验收通过”当成安装授权。

首次固化工具构建 `output/handcar-pinned-build` 因 GCC 探针错误失败，日志原样保留。
已将 `cc1plus/collect2` 查询改为 `-print-prog-name` 并用新目录完成冷构建。
临时移植 revision1/revision2 的证据保留在 `output/spike-rebase-4ffd6ba`，不能将不同
库哈希的报告混用。`make tests` 会删除整个 `output/`；备份时不要移动 M1 原始运行目录，
其审计绑定绝对路径。

## 移植内容与修复

保留官方 processor/CSR/指令及 walk/s2xlate 权限主逻辑，只在 MMU、共享库 wrapper、
必要的 `sim_t::addr_to_mem` 空指针处理和 ABI 头中接入 Handcar。1580 个指令实现和
配置来自官方构建再生成，不复制旧 generated 文件。

- 接入稀疏内存、冷热路径回调、跨页访存和 PTE A/D 持久写回。
- 物理写必须先成功，随后才更新回调/cache；设备拒绝不再被伪装为成功。
- host RAM 不再被部分 sparse 覆盖遮蔽，MMIO 与声明的 sparse RAM 分开处理。
- 修复 disassembly 的 `strdup/delete[]` 所有权错误、寄存器掩码写、多位 GPR 编号。
- 修复物理读假成功、非法长度及模拟器生命周期泄漏；逸出的 C++ step 异常返回失败。
- 适配新启动 PC、构造函数和配置生命周期，ISA 不再隐式追加 Zicclsm。
- HLVX 翻译标志和单地址 PMP 检查长度得到修正，属性输出未实现则明确返回 unsupported。

## 限定合同

这些通过结果不是完整 Hypervisor 或完整 Handcar ABI 支持：

- 只验收 RV64、hart 0。多 hart 请求明确拒绝；RV32、vector/event/parameter stub 未补齐。
- 默认 RAM 以外的目标须先由宿主写入/初始化，或通过内部声明接口建立 RAM backing。
  FORCE “已分配但尚未初始化”的地址不会自动同步给 Handcar。当前测试显式准备数据和
  页表；将来扩展 store-only/CBO.ZERO 生成路径时，必须接入独立 RAM-range 声明合同，
  不能恢复任意 CPU store 自动创建 backing 的做法。
- HLV/HSV 异常矩阵限于 D 尺寸、L0 V=0 leaf。其他层级、权限、A/D cause 不自动升级覆盖状态。
- 完整 Fault V2 保持原 330 tasks/seed 的范围；不因新上游支持更多扩展而宣称 cause 10-12 完成。
- packed PMP/memory attributes 请求返回 9；PA-only 调用传空输出指针。所有第三方 ABI
  消费者须重新核对，不能假定与旧实现的假成功兼容。
- disassembly 依赖现有 FORCE/FPIX 的调用方 128-byte buffer 合同；局部 ASan 验证了该用法。
- 稀疏 LR/SC、通用设备 PMA、多 hart 一致性，以及成功 device-backed PTE A/D 的全部组合
  仍不属于本轮已证实范围。全 mask 的部分 CSR 初始化兼容行为及详细诊断日志仍保留。

## 下一步

2026-09-06 接手复验未改变 pin、patch、开发分支或任何 Handcar/PTG 库：
`output/hypervisor-m2-entry/quick-afic79av/workflow.json` 为修改前 quick，
`output/hypervisor-m2-entry/full-4ggnyfiy/workflow.json` 为 M2 协调器改动后的 full，
均 rc=0。后者含 145 项工具单测、预检、3 smoke、106 M1、990 generation 和 990 独立 ISS。
PTG 为 `/home/guoshibo/page_table_generator/build/libptg.so`，SHA-256
`9eeac7b2f69c25f9a778974c1ab1ba71f47fc29c50749070e48e2d77f1eabb29`；Handcar 仍为上列
`a1013545...` 隔离库，两份原安装库仍为 `8ebad970...`。FORCE 定向重建后的 `bin/friscv`
SHA-256 为 `12704b7435224333dd3c8da40ef2f8a1e40dc4e9e7533e07333042ebe6962528`。
新增协调器 C++ 单测 12/12、完整 C++ suite 43/43 通过，但分配环节使用替身；不能把
原 PTG/Handcar 回归转换为新内部 Mapper 的真实页表支持声明。M2 第 1 项仍部分完成，
接续边界、原始目录和命令见[当前计划](plans/CURRENT_HYPERVISOR_DEVELOPMENT_PLAN.md)
的 M2 首轮进度。这是同日首轮状态，由下面的 native 增量继续推进。

同日后续已加入真实内部分配测试，修复 FORCE 的 x4 根表大小/unsigned GPA 范围、跨
stage 根表 alias 防护和 VS 页表恒等 backing。`output/hypervisor-m2-native/batch2-seed-*.log`
记录 102/102 seeds native 内存 walk 和同一隔离候选的 HLV/HSV 检查；每 seed 另有未声明
RAM store fault 强断言。未使用 PTG 生成这些页表，未确认新的外部 PTG bug。
原 PTG/Handcar full 在 `output/hypervisor-m2-native/full-0lo3w8qg/workflow.json` 继续 rc=0，
C++ suite 44/44。最新 FORCE 二进制 SHA-256 为
`f20bf18b81c862b3faed4cd99f5b39ddef531a21c85e5616b6e9cf6fc0b769eb`。
M2 第 1 项按 Sv39/Sv39x4、单 hart 0、页表 GPA=SPA、宿主显式初始化的限定合同验收；
不是完整 Mapper、CSR 序列、Python 模板或 live RAM-range 接入完成。
详细失败/通过证据及复现命令见当前计划“真实分配与隔离 ISS”。
本轮未安装、未提交、未推送，Handcar/PTG 与两份原安装库的哈希均未变化，既有改动保留。

**用户已明确改用 PTG-first 主线。** 上述 native Mapper 改动与验收保留为历史，不再扩展
另一套 Hypervisor 页表生成器。先使用 [快速上手](HYPERVISOR_QUICKSTART.md) 保持基线，
随后按当前 M2 接入 PTG-backed Mapper、内存同步和 CSR/fence。PTG 需求与问题记录在
[集成需求台账](PTG_FORCE_INTEGRATION_REQUIREMENTS.md)，由用户提交给 PTG 维护者。
PTG-first 首轮已修复 FORCE 导出错误和 writer 异常传播，11/11 ctypes 及 full 通过：
`output/ptg-first-integration/full-_0pto9vu/workflow.json`。PTG 严格导出需求 R001 仍待用户
转交，不能把这一轮回归通过当成该接口缺口已解决。所有依赖库保持原样。
随后诊断索引绑定通过 15/15 ctypes 和
`output/ptg-query-integration/full-jkp9icg4/workflow.json` full 回归；独立复现的 PTG
索引同步问题 B001/B002 与查询需求 R002 已写入台账，待用户转交。没有修改 PTG/Handcar
库，也没有把这些回归结果视为 PTG-backed C++ Mapper 已完成。
若要改为真正 submodule/repo 管理，需建立并发布 Handcar 定制仓库，然后用不可变 fork
commit 替代当前官方 commit + patch；不能把官方 URL 误当成已发布定制版远端。
