# FPIX ELF 独立重放：修复与限定验收

后续 full 已加入 [C++ PTG 数据 mapper](PTG_CPP_MAPPER_INTEGRATION.md) 阶段；当前工作区
复跑应使用快速入口最新 friscv-v5。本文保留 ELF 重放修复当时的 binary/hash 身份。

## 结论

F004 在当前 RV64、单 hart 0、Fault V2 固定矩阵内已修复并重新验收：**990 次生成、990 次
独立 FPIX ELF 执行，以及 990 份逐场景语义审计全部通过**。这次不是只统计 SUCCESS。
M1 106/106、155 项工具单测、40 项 ctypes 检查也通过。

最终完整入口证据：`output/fpix-replay-validation/accepted/full-d5ja_djd/workflow.json`。
Fault V2：`output/fpix-replay-validation/accepted/full-d5ja_djd/fault_v2/run_arub_bqv/manifest.json`。
每 seed 330 份 `results[].replay_audits` 记录启动步数、场景步数、trap 数和 ELF/两份 trace 哈希。
此前 `full/full-00g6bpvf` 也通过；最终轮进一步要求故障指令无额外寄存器写入，并记录
审计 parser/executor 及实际显式 generator adapter 输入哈希。

历史 `full-f7y3alcy`、`full-sj0cxi7r` 的 ISS PASS 仍只是旧 runner 的计数，不因本次通过
而升级证据。旧 ELF 缺页表，**必须重新生成**；只换模拟器或开启 H 不能补回缺失内容。

## 原因、归属和改动

均为 FORCE/FPIX 侧问题，本轮没有修改 PTG 或 Handcar 核心。

| 问题 | 实际修复 |
| --- | --- |
| FPIX ISA 缺 H，初始化 vstvec 即 cause 2 | 新 `fpix/config/riscv_rv64_hypervisor.config` 显式启用 H/Zicclsm；Fault V2 拒绝缺 H 的配置 |
| PTG 页表只存在于生成期 ISS，ELF 缺失 | `PyVirtualMemory.h` 的物理写同步 FORCE MemoryManager 的初始镜像和当前字节；由正常 ELF 输出链序列化 |
| PC 不变即判测试结束，地址 0 异常循环也成功 | SimApi 保留本步解码与真实 trap 结果；FPIX 只接受无 trap 的 `jal x0,0`/`c.j 0`，否则报错退出 |
| stdout/stderr 与 simulator 同时写 fpix_sim.log | executor 改用 `fpix_console.log`，`fpix_sim.log` 专供逐指令 trace |
| ELF 参数解析向空字符串的 begin() 写入 | 修复小写转换的未定义行为；长绝对路径 ELF 实跑覆盖 |
| summary/加载库正确仍可能跑错场景 | 新 `ptg_replay_audit.py` 必须逐步核对目标场景和合法终点，失败使 runner 返回非零 |

物理写保留已有初始字节，更新当前字节；即时写不再额外排队，避免下一条指令前重复覆盖。
初始镜像不是宿主运行时修改事件的回放日志：执行期间修改 PTE 等后续动作仍须有对应
目标指令/专用重放合同。本轮静态构造后注入故障的矩阵已实际验证，不外推到任意动态场景。
该修复不替代宿主 RAM/MMIO 所有权、通用 allocator 或回收设计。

## 复现与正负对照

旧 guest-explicit ELF：
`output/handcar-trace-validation/full/full-sj0cxi7r/fault_v2/run_li79ozhk/seed_15c0ffee/output/regression/ptg_fault_v2_guest_explicit_trap_gexp_gva_g2_force/00000/`

1. 历史缺 H 配置：初始化异常、PC=0，50 步仍报 SUCCESS。
2. 本轮仅开启 H：`output/fpix-replay-validation/fpix_sim.log`，498 步结束，但三次都是
   **instruction access fault（cause 1）**，未得到所需 guest-page faults。旧 ELF 没有
   PTG 根表 SPA `0x180000000` 对应段。
3. 修复内存镜像、重新生成：`guest-with-image/`，ELF 新增起始 `0x180000000`、长度
   `0x15000` 的 RW LOAD 段，覆盖 PTG 导出页表。
4. 独立重放：318 个启动步 + 188 个场景步 = 506 步，得到预期 load/store/instruction
   guest-page faults（21/23/20），与生成期目标轨迹逐步一致。

上述本轮相对路径均在 `output/fpix-replay-validation/`。初期参数解析崩溃/超时和构建目录
错误日志保留，不作为通过证据。

`tests/riscv/fpix_replay_checks.py` 的 7 项 native 检查通过，证据 `native-checks/checks.json`：

- 32-bit、16-bit 自环正常结束；非法指令停在 0 返回 1。
- 缺 H 的 CSR 指令返回 1；启用 H 后同一指令正常执行。
- 完整 ELF 独立重放并通过语义审计。
- 缺页表的旧 ELF 虽然可走到自环且 rc=0，**审计明确拒绝**。

## 审计合同

`audit_case()` 要求 ELF64 little-endian / RISC-V，并核对执行起点为 ELF e_entry。
生成和 FPIX 日志均须为完整 trace v2；独立执行必须有启动阶段，且启动阶段无异常。
从唯一场景入口开始，全部目标步一一匹配 PC、NextPC、opcode、实际 trap 字段、访存事件，
并验证生成期记录的寄存器结果；不得跳过多余指令或只搜索零散 PASS 标记。最后必须是
无 trap 的终止自环。至少一个实际 trap 是本 Fault V2 矩阵的要求，不是一般程序要求。
故障步的寄存器写集合也必须与生成期完全一致，不能掩盖额外目的寄存器修改。

审计参考来自已有强断言的生成期模板；它证明独立装载/初始化/执行与目标语义一致，
**不是不同 ISA 模型之间的差分验证**，两进程使用同一 Handcar。当前支持单 hart、
非推测执行、限定 trace 格式，不声称支持任意 OS 镜像或完整 Hypervisor。

## 本轮身份

| 产物 | SHA-256 |
| --- | --- |
| `output/fpix-replay-validation/friscv` | `ee83a3ad07b7b994cee5ef4bfd7b6340ccf7865d3a6feb17ba73c9a846c1a333` |
| `output/fpix-replay-validation/fpix-checked` | `f80269fc562e05d88ce42e4ab4a5ce9391803a6742a80f067b54d85476b9c42a` |
| 生成期 `output/handcar-trace-validation/SimApiHANDCAR.so` | `55b1afdcc93e19946dd97a79ae8a4e57ed0e3fabb811183272d48f155ba65c26` |
| `output/handcar-trace-v2-build/handcar_cosim.so` | `3af0cb331e3d6f7a9e77f48304574c8183e14a6099bca8752eaf9f6c28be3cad` |
| PTG `libptg.so` | `dfee221f7417e950ee1ca93c9a8df697148c5ed50359590e5a82148f0646b082` |

生成期使用已有 trace-v2 adapter；独立 FPIX 静态编入本轮新增自环判定的 adapter。
不混淆二者，也不需要替换默认安装库。默认 friscv/FPIX/Handcar 二进制未安装更新。
源码未提交、未推送，既有修改和失败证据保留。

## 本机复跑

在仓库根目录 Bash：

```bash
source ./setenv.bash
export PYTHONDONTWRITEBYTECODE=1
python3.12 utils/regression/hypervisor_workflow.py --profile full \
  --friscv "$PWD/output/fpix-replay-validation/friscv" \
  --fpix-bin "$PWD/output/fpix-replay-validation/fpix-checked" \
  --handcar-so "$PWD/output/handcar-trace-v2-build/handcar_cosim.so" \
  --ptg-lib "$(realpath ../page_table_generator/build/libptg.so)" \
  --m1-config "$PWD/output/handcar-trace-validation/rv64.config" \
  --generator-config "$PWD/output/handcar-trace-validation/twostage.config" \
  --artifact-root "$PWD/output/fpix-replay-next" --jobs 8
```

新机器需从源码构建。`riscv/Makefile` 支持 `FRISCV_BIN`，`fpix/riscv/Makefile` 支持
`FPIX_BIN` 与 `OBJ_DIR/DEP_DIR` 覆盖，便于隔离构建；不执行根 `make tests`。
runner 的 `--friscv/--fpix-bin` 支持显式候选；FPIX_PATH/FORCE_PATH 由 Fault V2 runner
设为仓库路径。full 默认 FPIX 配置已改为 Hypervisor profile，旧非 H profile 保留。

下一步可回到 placement v1 生产适配及受限池扩展；本轮不解除单 context/所有权约束。
