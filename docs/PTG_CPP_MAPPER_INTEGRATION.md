# PTG C++ 数据 VmMapper / genVA 首期接入

## 结果与范围

新增 `base/inc/PtgVmMapper.h`、`base/src/PtgVmMapper.cc`。托管上下文激活后，普通
`genVA()` / `genVAforPA()` 数据请求已进入 C++ PTG mapper，直接消费 PTG Query v1，
复用 FORCE 约束选择器选址，并经 HLV/HSV 和独立 ELF 重放验证。

这是 **published-data-only 子集**，不是所有 VmMapper 功能完成：

- 单 hart 0、M-mode 发起的 VS 数据访问，Sv39/Sv39x4。
- 只复用已发布、已拥有 SPA backing 的映射，不在 genVA 阶段创建新页表。
- 保守筛选 VS supervisor RW、G U=1/RW、A/D=1、PBMT/NAPOT=0 的页；一般 SUM/MXR、
  execute/HLVX、VU、fault-generation 等权限约束不在此子集内。
- 请求支持 Size、Align、Range、bank 0；PA 查询复用已有 alias。新映射、指令地址、
  ForceNewAddr/ForceAlias、指定其他 VM、共享属性及其他未支持选项明确拒绝。
- 主机 PC/instruction mapper 与物理 genPA 保持其原职责；没有把整个 CurrentVmMapper
  换成 guest mapper。完整 PageInfo、通用 VaGenerator、隐式操作数选址、动态映射/回收
  仍待实现。M2 总体验收继续保持未完成。

## 数据路径

```text
GenThread.activatePtgVmContext
  → existing strict publication + CSR/fence activation
  → VirtualMemory.bindPtgDataMapper
  → VmManager's PTG data binding

Sequence.genVA / genVAforPA
  → GenVirtualMemoryAgent (C++)
  → PtgVmMapper::GenerateAddress
  → PTG CURRENT VS/G enumeration + composed interval intersection
  → FORCE ConstraintSet / side-effect-free address selector
  → GVA used by real HLV/HSV
```

C++ 通过选定的同一个 libptg.so 查询，借用 Python 托管 handle，不持有影子 VA→PA 表。
每次生成候选都重新读取 PTG current records。保留的 payload spans 只是宿主预留记录，
不是另一套页表/翻译模型。没有 native 页表 fallback 或 FORCE 自行构造 PTE。

Range/Size 在每个组合映射 span 内处理，再合并允许的起始地址，避免两个相邻 GVA 页
映射到不连续 SPA 时错误拼接大访问。`genVAforPA` 从符合完整访问长度和 alignment 的
已有 aliases 选择，不创建 alias。无候选抛出异常，不用地址 0 表示失败。

`VirtualMemory.ptgTranslationRange(va)` 暴露本子集的 C++ range 查询，返回 inclusive
`(va_low, va_high, spa_low, spa_high)` 或 None。Python `ctx.lookup()` 仍是较广的结构
观察接口，两者不能混同为完整架构权限 oracle。

## 生命周期与 root reload 保护

- 激活开始先进入 PTG-required 状态，旧 C++ binding 清除。随后实际 CSR/fence 成功且
  新 binding 校验完成才开放数据选址；中途失败保持阻断，不能回落到 native genVA。
- 每次 C++ 查询检查实际 ISS 的 vsatp/hgatp 与绑定根一致、HSTATUS.SPVP=1，并读取
  frozen Strict Export layout 对比 metadata/PTE bytes。拓扑 stale 或软件页表变化会失败。
- native `VmManager::Update`、native context 创建及未接入的 VMVA/free-page 请求在
  PTG address scope 内拒绝。活动 scope 的 VmManager clone 也明确不支持。
- 关闭 active context 先撤销 C++ 借用，再销毁 PTG handle；此后选址保持阻断，避免
  dangling handle 和 native fallback。调用者不得绕过 managed API 销毁底层 handle。
- `deactivatePtgVmContext()` 在 M-mode 发出 vsatp=0/HFENCE.VVMA、hgatp=0/HFENCE.GVMA，
  检查 ISS 两个根 CSR 都为 0 后，才允许离开 PTG address scope。
- 表/数据 RAM reservation 和会话 VMID 的保留合同继续有效，不自动回收。

Python 使用方式：

```python
ctx.publish()
gen_thread.activatePtgVmContext(ctx)
try:
    va = gen_thread.genVA({"Size": 8, "Align": 8, "Type": "D",
                          "Range": "0x40000000-0x40003fff"})
    # Emit HLV/HSV using va. Initialize payload RAM before publishing the context.
finally:
    gen_thread.deactivatePtgVmContext()
    ctx.close()
```

需要新的 friscv C++ bridge；旧 binary 明确报缺失能力，不用 Python 选址伪装 C++ 接入。

## 实际验证

新模板 `tests/riscv/ptg_cpp_mapper_force.py`：每 seed 32 次 genVA + 32 次 genVAforPA，
两个上下文交替选址，65 次 HLV、32 次 HSV。完整初始化的数据模式含 VMID/page/word，
store 值含迭代编号；外部 auditor 独立重建预期数据，检查跨 VM 隔离和写后 alias 回读。
`PTG_DATA_ADDRESS` C++ 日志 marker 证明实际进入 native 选择路径。

负向检查包括未映射范围、VS X-only、G 只读、VS U 页、非法大小/对齐、新映射请求、
不存在的 PA、跨不同物理叶的访问、native updateVm/context 请求、软件-only PTE mutation、
active context 关闭和失败切换后的再次选址。它们均被拒绝，随后合法上下文可重新激活。

最终工作流：`output/ptg-cpp-mapper/accepted/full-xrc63xkh/workflow.json`。

| 验证 | 结果 |
| --- | --- |
| 工具测试 / ctypes | 156 项 / 52 项，通过 |
| 原 M1 | 106/106 |
| 原 Fault V2 ELF 语义审计 | 990/990 |
| 托管上下文合同 / 原双地址空间 ELF | 12/12、3/3 seeds |
| 新 C++ 自动选址 ELF | 3/3 seeds，全部生成、独立执行及语义审计通过 |

新场景报告：`cpp_mapper/contexts-j52k3vw5/contexts.json`。
seed 1 日志：`cpp_mapper/contexts-j52k3vw5/seed-1/fpix_sim.log`，共 **1287 步**
（206 启动 + 1081 场景），无 trap。原 context 用例增加显式 deactivation，保留独立计数。
full 已新增 `ptg_cpp_mapper` 阶段；不同专项的三 seed 不混入原 Fault V2 990 计数。

## 开发期错误 F005：权限位域混用

分类：FORCE C++ adapter bug，已修复，不是 PTG bug/API 缺口。

初版误把 `ptg_add_mapping` 的输入 U=0x10 用于 Query `raw_perm`。公共 Query 合同是
R/W/X/U/G/A/D 位 0..6，U=0x08；G RW/U/AD 的查询值为 **0x6b**，不是输入值 0x73。
错误筛选导致全部 G 页被排除，正确的 genVA 请求也报 ConstraintSet empty。

最小复现：创建托管 context，map 一页默认 VS/G RW，publish/activate 后对该 GVA 页
执行 Size=8/Align=8 的 genVA。预期返回页内地址，初版实际失败。
证据：`output/ptg-cpp-mapper/automatic/contexts-d0ejoe1h`；失败 binary `friscv-v2` SHA-256
`004490e7ab60eff83c47ced0e0bdf7111c76f259094e9946a521735e8a73fc99`。
修复后按 query 位域解码，并通过正常 RW/VS U/G 只读/X-only 对照。未放宽访问筛选。

## 版本与复跑

| 输入 | SHA-256 |
| --- | --- |
| `output/ptg-cpp-mapper/friscv-v5` | `c94c81d0171541aaa698933ff66d894e6d42f298b4ef41d94801871219baa5c0` |
| `base/src/PtgVmMapper.cc` | `bafe38cf4723b8b172c04f95179250c39727e0981c11c8bcb0f1f1f7f571358e` |
| `base/inc/PtgVmMapper.h` | `c12e1930355cabda6f4f5fc2782c96fbe49e55ea7fc1e6d910f32950d322ad9b` |
| PTG | `dfee221f7417e950ee1ca93c9a8df697148c5ed50359590e5a82148f0646b082` |
| Handcar | `3af0cb331e3d6f7a9e77f48304574c8183e14a6099bca8752eaf9f6c28be3cad` |

使用快速入口的显式候选/配置命令，friscv 改为上述 v5，profile=full，输出使用新目录。
单项入口 `utils/regression/run_ptg_context.py --scenario mapper --help`。
新 binary 由 `riscv/Makefile` 的 FRISCV_BIN 隔离目标构建；没有安装、提交或推送。
本轮未修改外部 PTG 或 Handcar 核心，也未重新宣称 PTG 全局 stress 全绿。

下一步是扩展通用 VmMapper/PageInfo 和权限/访问类型合同，并设计新映射/重映射的
架构可重放更新协议。现阶段 published-only 限制避免把宿主动态写页表冒充 ELF 指令。
