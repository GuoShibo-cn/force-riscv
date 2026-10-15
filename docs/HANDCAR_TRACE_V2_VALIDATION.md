# Handcar trace v2：指令 PC 与真实 trap 事件

**后续更新：** 下文独立重放缺口已在新 FORCE/FPIX 隔离候选修复；新生成的 990 份
ELF 均通过目标场景语义审计，见 [FPIX 重放验收](FPIX_ELF_REPLAY_ACCEPTANCE.md)。
本篇旧 runner 计数及旧 ELF 不自动升级为新证据。

## 问题与修复

用户指出异常日志 PC/指令不对应且没有 trap 描述，复核确认：

1. **FORCE adapter 日志错误**：`SimApiHANDCAR::Step()` 用执行前 PC 反汇编，却把执行后
   PC 传给 `PrintInstructionStep()`。普通指令通常错位 4 字节，异常则把 handler 地址
   贴到原指令上；不能通过统一减 4 修复。
2. **Handcar 诊断事件缺失**：旧候选没有调用 `update_exception_event`，所以
   `PrintExceptionUpdates()` 没有内容。非零 mcause/CSR 差值不能替代真实事件：正常
   指令可以看到旧 cause，重复异常可能不改变任何 trap CSR。

旧复现目录：
`output/ptg-allocation-acceptance/full-f7y3alcy/fault_v2/run_218fklw9/seed_15c0ffee/output/regression/ptg_fault_v2_guest_explicit_trap_gexp_gva_g2_force/00000/`

`.Default.S:394` 中 SD 在 `0x8001301c`，`sim.log:485` 却标为 `0x80015000`；
handler 的 CSRRS 实际在 `0x80015000`，日志标成 `0x80015004`。旧库 SHA-256 为
`a1013545508251676b63ec93686cd305a7c7140a1795887193a11061e3529224`。
旧 M1 审计知道 POST-PC 含义，但先前展示日志时未解释该错位是不准确的。

新实现：

- 在 step 前取 PC、反汇编，避免 trap/xRET 改变翻译上下文后再解码旧 PC。
- v2 文件头明确 `PC(VA)=instruction address`，另列 `NextPC(VA)`。
- 从 Spike 实际 `processor_t::take_trap()` 调用可选弱诊断回调 `handcar_trace_trap`，
  记录原始 trap 名、cause、EPC、tval/tval2/tinst、处理后 PC、前后 privilege/V 状态。
- 诊断回调不向 FORCE 自动 exception-handler 队列注入行为。原始 trap 字段不笼统
  等同于所有委托/double-trap 场景的最终 machine CSR；这不是完整 exception-event ABI。
- M1 v2 fault 审计要求实际事件字段匹配；成功访问不允许 trap。旧 POST-PC 归档仍可解析。
  旧库缺少回调时仍可加载，但不能通过新的 v2 fault 事件门槛。
- 新 `tests/riscv/handcar_trace_check.py` 对照 `.S` 的地址/机器码和事件 EPC/target。
  无法解码的取指故障必须伴随真实 trap，不冒充成功执行。

## 候选与验证

| 项目 | 身份/结果 |
| --- | --- |
| Spike pin | `4ffd6ba860f4190ceac2716fa3c2cf139e85538f`，未升级 |
| 新 patch SHA-256 | `daa1fc933dec48150c00d976623077ad09bc6193dd1500ef0bf74d6f3df9689a` |
| 新 Handcar | `output/handcar-trace-v2-build/handcar_cosim.so` |
| Handcar SHA-256 | `3af0cb331e3d6f7a9e77f48304574c8183e14a6099bca8752eaf9f6c28be3cad` |
| 新 adapter | `output/handcar-trace-validation/SimApiHANDCAR.so` |
| Adapter SHA-256 | `55b1afdcc93e19946dd97a79ae8a4e57ed0e3fabb811183272d48f155ba65c26` |
| PTG SHA-256 | `dfee221f7417e950ee1ca93c9a8df697148c5ed50359590e5a82148f0646b082` |
| 新构建 | pin + patch 全新 prepare/build；native MMU/ABI、局部 ASan 通过，源码未变 |
| Native 新检查 | 重复相同异常、CSR 写入不产生事件、取指异常、S-mode 委托异常 |
| M1 runner 单测 | 36/36，含旧格式兼容、v2 双 PC、缺失/伪造事件拒绝 |
| M1 | `output/handcar-trace-validation/m1/m1-79v4fsir`，106/106 |
| M1 fault 汇编核对 | `m1-fault-trace-check.json`，268/268，四个实际 trap |
| Guest-explicit 核对 | `guest-explicit-trace-check.json`，188 步：187 条匹配，一次取指异常无法解码；三个实际 trap |

后两份 JSON 在 `output/handcar-trace-validation/`。构建证据为
`output/handcar-trace-v2-build/build.json`。独立开发分支改动未提交，patch/lock 已同步。
默认 Handcar/adapter 未替换，PTG 未修改。`git diff --check` 的四个 patch 空白上下文
前缀警告保留；其余已跟踪源码差异检查通过，prepare 验证 patch 可应用。

full 入口也已执行：`output/handcar-trace-validation/full/full-sj0cxi7r/workflow.json`。
生成阶段使用新 adapter，runner 返回 passed；**独立 FPIX 有下节缺口，不将其 PASS
描述为目标场景的完整 ELF 重放验收。**

同一 guest-explicit 新日志目录：
`output/handcar-trace-validation/full/full-sj0cxi7r/fault_v2/run_li79ozhk/seed_15c0ffee/output/regression/ptg_fault_v2_guest_explicit_trap_gexp_gva_g2_force/00000/`

`sim.log:614–627` 显示 SD 的 PC=`0x8001301c`，NextPC=`0x80015000`，
`trap_store_guest_page_fault` 的 cause=`0x17`、epc=`0x8001301c`、tval=`0x44400000`、
tval2=`0x31a80000`，从 VS（priv=1,V=1）到 M（priv=3,V=0）。随后 handler 的
`csrr a0, mcause` 正确显示在 `0x80015000`。

## 独立 ELF 重放仍有验收缺口

另已确认 **FORCE/FPIX 配置与成功门槛问题**，不是 PTG bug：

- 旧 `full-f7y3alcy` 的 `fpix.config` ISA=`RV64IMAFDCV_zfh`，缺 H。
- 上述 guest-explicit 的 `fpix_sim.log:186–250` 在初始化 `csrw vstvec` 时 cause 2，
  跳到 0 后 cause 1，仍打印 `Executed 50 instructions ... SUCCESS`。
- `ptg_fault_v2_instruction_trap_force/00000/fpix_sim.log` 抽查到相同行为。
- 历史 **990/990 ISS 仅是 runner 计数，不能证明完整目标场景独立重放成功**。

后续验收条件：修正 Hypervisor FPIX ISA；核对初始化、页表和执行状态重建；必须到达
目标指令、预期异常和合法终点。只开启 H 或检查 SUCCESS 不足以关闭问题。
本次 PC/trap 诊断修复不宣称解决此重放缺口。旧证据保留，不改写旧 PASS 文件。
