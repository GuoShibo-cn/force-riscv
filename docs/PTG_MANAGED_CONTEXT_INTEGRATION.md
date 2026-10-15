# PTG GenThread 上下文、结构查询与 CSR/fence 闭环

**后续更新：** [C++ 数据 mapper](PTG_CPP_MAPPER_INTEGRATION.md) 已接通已发布映射的
genVA/genVAforPA；GenThread 激活现在要求新 friscv bridge，并提供显式 deactivation。
下文保留首期 GenThread 层的结果与当时边界。

## 当前完成范围

新增 `py/riscv/paging/PtgVmContext.py`，由 GenThread 提供
`createPtgVmContext()` / `activatePtgVmContext()` 入口。它在已验收的 PTG placement、
query、strict export 上建立受约束映射与发布/激活生命周期。

本轮是 **GenThread 层显式 PTG 接口**，没有替换 C++ `VmMapper` 或原 `genVA()`。
`base/src/TwoStageVmMapper.cc` 仍是历史 native 委托路径。M2 不因此整体完成。

## 接口与使用

```python
ctx = gen_thread.createPtgVmContext(
    "VM1Tables", asid=0x11, vmid=1,
    table_ram=(0x88000000, 0x89000000),
    data_ram=(0x84000000, 0x86000000),
    gva_range=(0x40000000, 0x41000000),
    gpa_range=(0x60000000, 0x61000000),
    table_gpa_range=(0x90000000, 0x91000000),
)
try:
    spa = ctx.map(0x40000000, 0x60000000)
    ctx.map_alias(0x40010000, 0x60000000)
    ctx.initialize_data(spa, (0x1122334455667788).to_bytes(8, "little"))
    info = ctx.lookup(0x40000008)
    aliases = ctx.reverse(spa + 8)
    ctx.publish()
    gen_thread.activatePtgVmContext(ctx, scratch=5)
    # Emit HLV/HSV using the mapped GVA; activation selects VS privilege for these accesses.
finally:
    gen_thread.deactivatePtgVmContext()
    ctx.close()
```

- `map(gva, gpa, size, vs_level, g_level, vs_perm, g_perm)`：GVA/GPA 在调用者明确声明的
  半开范围内；SPA 由 FORCE 在已认可 RAM 中锁内 `genPA` + reserve。PTG 逐叶构造全部 PTE。
  默认 4 KiB，支持完整 4 KiB/2 MiB/1 GiB leaf 的组合，整个请求按较大 leaf 对齐。
- `map_alias()`：4 KiB VS aliases，GPA 必须已有本 context 拥有的 payload backing。
- `lookup()`：从 PTG CURRENT VS/G 查询组合交集，返回 GVA/GPA/SPA base、size、两层
  leaf level 和原始权限。混合页尺寸的有效 range 是两个 stage 的交集。
- `translate()`：返回结构映射 SPA 或 None；SPA=0 有效，不作为缺页哨兵。
- `reverse()`：G reverse → VS reverse 组合所有 aliases。没有 FORCE 影子映射表、手写
  PTE 或自建 page walker。PTG current 变化可在结构查询中直接观察。
- 返回值是**结构与原始权限元数据**，不授权访问，也不是 ISS TLB 状态。X-only 的 VS 页
  可以有有效结构查询结果，但不能据此声称普通 HLV 可读。

## 生命周期和所有权

状态为 `building → published → closed`，host/映射/发布/激活失败进入 `failed`。
前置参数错误在分配/修改前拒绝。映射失败可能已有部分 PTG publication；不承诺整批回滚，
失败 context 禁止再激活，既有 reservation 保留。

- 每个 context 仍用独立 PTG handle 和独立 FORCE 预留表池，没有放宽单 handle/context
  合同。多个 context 的数据 SPA 也由 FORCE 分配、预留，不依赖硬编码物理目标。
- 表 RAM 和数据 RAM 必须为调用者认可的、不相交的 RAM 区间；GPA payload 和 GPA table
  区间也必须分离。没有自动探测 MMIO/PMA，也不支持跨 bank；当前 bank=0。
- 构造只支持 hart 0、Sv39/Sv39x4、GVA 下半 canonical 区间；A/D 预置 1，减少运行时
  PTE 写回同步的未覆盖状态。G-stage U=1；原始 perm 的未支持位明确拒绝。
- `publish()` 一次性 strict capture/pull/load，把页表同步到 FORCE/ISS/ELF；随后本 API
  禁止新增映射和宿主数据初始化。重复激活只核对冻结导出内容，不重写表或数据。
- 激活前检查 PTG root 的 MODE/ASID/VMID 和 export metadata/PTE bytes。越过托管 API
  修改已发布 PTG 图会在激活前失败，不 recapture、不悄悄覆盖运行时内存。
- close 释放 PTG handle/layout，不归还 FORCE 表/数据 reservation，不证明硬件已停止使用
  RAM，也不自动撤销当前 CSR。VMID 加入 GenThread 既有分配集合；托管 VMID 在会话内
  不能由 `releaseVMID()` 释放，关闭后也不能复用。

## 激活协议

当前仅在 M-mode 显式激活，消耗调用者指定的一个非零 scratch GPR：

```text
CSRRW vsatp, x0       # Disable the previous VS translation.
HFENCE.VVMA x0,x0
CSRRW hgatp, PTG_hgatp
HFENCE.GVMA x0,x0
CSRRW vsatp, PTG_vsatp
HFENCE.VVMA x0,x0
CSRRS hstatus, SPVP   # Select VS privilege for HLV/HSV; preserve other bits.
```

CSR 值来自 PTG，不自行重建根表。激活路径不调用 native `updateVm()`；调用者仍不得在
托管执行阶段用其他 CSR/native VM API 覆盖这些设置。自动拦截/协调 C++ Mapper 的 root
reload、权限约束与 genVA 是下一阶段，不应把当前接口当成该机制已经接通。

此验证证明全局 fence 序列与实际地址空间切换正确执行，不证明选择性 fence 或无需
flush 时的 VMID-tag TLB 隔离；也不是完整虚拟机寄存器/中断上下文调度。

## 实际场景与结果

迁移现有 `tests/riscv/ptg_vm_context_fence_force.py`：

- 两个 context，ASID `0x11/0x12`、VMID `1/2`，相同 GVA `0x40000000` 和 GPA `0x60000000`，
  独立 FORCE 分配的 SPA；每个 context 还有一个 GVA alias。
- VS 2 MiB/G 4 KiB 和 VS 4 KiB/G 2 MiB 两种组合，检查交集 range 和真实哨兵读取。
- 64 轮 A/B 交替激活，132 次 HLV、64 次 HSV。每次切回先读此前该 VM 的存储值，再写
  新值，并通过 alias 回读；检查跨 VM 隔离和持久性。
- 每轮检查 CSR/fence 编码顺序及源寄存器中的 MODE/ASID/VMID，独立执行不能含任何 trap。
- FPIX 的 ELF 加载只发生在启动阶段；runner 检查开始 step 后没有 `WRITE_SIM_MEM`
  宿主重写。生成期本身仍会初始化指令字节，不能仅凭生成期日志推断 fence 必要性。

最终证据根：`output/ptg-context-integration/final/full-_kgk83bo/`。

| 检查 | 结果 |
| --- | --- |
| 原有工具测试 | 156 项通过 |
| 原 M1 | 106/106 |
| 原 ctypes | 52/52 |
| Fault V2 ELF 及逐场景审计 | 990/990 |
| 新上下文合同检查（真实 PTG、host fixture） | 12/12 |
| 新上下文生成 + 独立 ELF + 语义审计 | 3/3 seeds |

新场景每个 seed 有 1932 个目标执行步；seed 1 的独立 FPIX 共 2118 步（186 启动 +
1932 场景），不是用固定步数判定通过。三份审计报告：
`contexts/contexts-lc9cwy79/contexts.json`。
日志：`contexts/contexts-lc9cwy79/seed-1/fpix_sim.log`；同目录有 ELF/S、生成日志和 console。
`hypervisor_workflow.py --profile full` 现自动追加 context contracts 和三 seed 专项阶段，
失败会传播；Fault V2 的 330 tasks/seed 保持其原矩阵身份。

## 首轮失败：FORCE adapter 错误，不是 PTG bug

`output/ptg-context-integration/first/contexts-akh2cupn` 保留失败日志。初版 adapter 对 G-stage
传入 `size=0x200000, leaf_level=0`，错误地假设一次 `ptg_add_mapping` 安装了 512 个叶子。
最小复现是注册池/创建 Sv39x4 后调用这一映射，再 CURRENT 查询 `gpa+0x1000`：没有记录。
源码 `PageTableTree::add_mapping` 根据 leaf_level 安装单个 leaf，范围为其自然 page size。

适配器的期望是完整 2 MiB 请求，实际只有起始叶，所以 mixed-range 查找失败。
修复为按 stage 的自然 leaf 大小分别调用 PTG；FORCE 不构造 PTE。新测试覆盖区间起始、
内部和最后字节，两种 leaf-size 组合均通过。接受标准是每个子页可查询，并在 Handcar
得到正确数据；本轮没有提出新 PTG API 需求，也未修改/提交外部 PTG。

另保留 `full/full-972m11wj` 的 workflow 测试失败：新增 context 阶段后旧测试未纳入其
子报告路径；更新精确期望后通过，没有放宽错误传播。其他中间通过记录保持原身份。

## 身份和复跑

| 输入 | SHA-256 |
| --- | --- |
| PTG | `dfee221f7417e950ee1ca93c9a8df697148c5ed50359590e5a82148f0646b082` |
| Handcar | `3af0cb331e3d6f7a9e77f48304574c8183e14a6099bca8752eaf9f6c28be3cad` |
| 新 PtgVmContext.py | `0c59b3a4d27cedaeb0016e916a12c5a5be36781fd92813eed85ba6ed59c3512e` |
| GenThreadRISCV.py | `eae54d434699c37155864101e4efdd644ab9457b8b882be3f177340b84d7210c` |

friscv/FPIX 仍为上一轮 ELF 镜像修复的隔离候选。完整命令见
[ELF 重放验收](FPIX_ELF_REPLAY_ACCEPTANCE.md)，使用新的 artifact-root。
也可单独调用 `utils/regression/run_ptg_context.py --help`；须 source setenv.bash，并显式
指定 friscv/FPIX/Handcar/PTG 及 trace-v2 generator config。未安装、提交或推送。
