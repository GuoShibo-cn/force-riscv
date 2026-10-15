# A001 首期：FORCE 预留的 PTG 页表池

## 已实现的合同

**后续候选更新：** PTG `dfee221f...` 已修复并通过 B003/B004/R003 独立限定验收，见
[反馈](PTG_ALLOCATION_PLACEMENT_ACCEPTANCE_FEEDBACK.md)。下面记录首次 owned-pool
适配；其单 context 等生产限制仍保留。后续已正式绑定 placement v1，工厂在预留前
检查能力，并默认设置自然对齐/all-owned PA policy，见
[placement 生产适配](PTG_PLACEMENT_PRODUCTION_INTEGRATION.md)。

2026-09-20 新增 `PtgBackend.with_reserved_table_pool()`。它应用现有 FORCE 分配/预留
和 PTG region API，不生成或修补 PTE，不添加独立 native Hypervisor 页表后端。

```python
ptg = PtgBackend.with_reserved_table_pool(
    gen_thread, "UniquePtePoolName", 0x100000, 0x88000000, 0x89000000,
    mem_bank=0, lib_path=ptg_library,
)
try:
    ctx = ptg.create_two_stage_context(
        vs_mode="Sv39", gs_mode="Sv39x4", asid=1, vmid=1,
        gpa_base=0x90000000, gpa_limit=0x91000000,
    )
    # Configure mappings using PTG, then capture/pull with the existing strict APIs.
finally:
    ptg.destroy()  # Does NOT unreserve the FORCE RAM pool.
```

`ram_base/ram_limit` 是调用者明确认可的连续 RAM 半开范围，不是 API 自动发现的 PMA。
不能因为默认 `memory.py` 允许很宽的物理地址范围，就把它全部当成 RAM。reservation name
必须在 FORCE 生成会话内唯一；FORCE 原有重复名称失败行为仍适用。

流程：

1. 校验非零范围、正的 16 KiB 倍数大小及整数边界，确认 PTG v1 能力可用。
2. 在 `lockThreadScheduler()` / `unlockThreadScheduler()` 的平衡临界区中，用
   `genPA(Size, Align=0x4000, ForceNewAddr=1, Range, Bank)` 选择可用且未映射的地址，
   随即 `reserveMemoryRange()`；不能直接 reserve 一个未经可用性检查的硬编码地址。
3. FORCE 的 Range 为 inclusive，PTG 的 limit 为 exclusive；传入 PTG `[base, base+size)`。
4. 通过 `table_pool` 返回只读的 name/base/limit/bank。GPA region 不在 FORCE 中预留；
   GPA 与 SPA 数值可相同或不同，但不是同一个地址域。
5. 严格 batch 装载要求原 GenThread writer、原 bank，完整 pull 后逐 SPA 区间检查均在
   预留池内，再写任何内存。VS source GPA 不作为宿主写地址或池授权依据。

原 `PtgBackend()` 未绑定池的行为保留，供分阶段迁移。本轮只有 M1 access matrix
改用 owned pool；fixed 和 guest-scope 仍使用上一轮严格导出，但尚未获得此预留合同。

## 生命周期与首期限制

- FORCE reservation 保留到生成会话结束；PTG handle/layout 销毁不代表 ISS/ELF 已停止
  使用其页表。即使后续 PTG 注册/配置失败，也不自动归还已经预留的地址。
- 调用者不得在活动页表仍被使用时手工 unreserve；这不是针对绕过 API 的安全沙箱。
  回收需要另行建立 CSR/fence/quiescence 合同，当前未提供自动回收。
- 本路径限定新 handle、单 VMID、一个 VS/G context、每 stage 一次 RV64 配置；当前真实
  验证为 Sv39/Sv39x4、hart 0。禁止额外 PA region、S-stage 混用、重复 stage setup、
  restore 和 legacy `load_to_force()` 写入逃逸；可添加同 VMID 的不重叠 GPA region。
- 校验实际 G root 的 MODE、16 KiB 对齐和池内边界，失败后拒绝继续新严格查询/捕获/装载。
  这里不在 FORCE 做 allocator padding 或 PTE 修复。
- 首期限制源于当时复现的 B003/B004；新候选已修复并接入，但更广宿主生命周期仍需验证。
  增量 mapping/backfill 可部分提交，不能将 checked allocation 当成全局事务回滚。
- 只管理页表池。数据 SPA、显式 genVAforPA/物理写、跨 context 共享、动态 MMIO 排除、
  跨线程/多 hart 生命周期和其他 legacy mutation 不在本次所有权保证内。
- FORCE reservation 控制正常地址分配，不会阻止所有显式物理访问；PTG 数据映射也应
  由调用者与页表池分开，不能把表池又作为数据 payload 使用。

## 验证

PTG/Handcar 继续是 `8a56c462...` / `a1013545...` 两个已验收库，完整哈希记录于各 manifest。

| 检查 | 结果与证据（相对 `output/ptg-pool-integration/`） |
| --- | --- |
| ctypes + adapter | 40/40，`ctypes-final.log`，新增 8 项池测试 |
| 独立 v1 ABI/合同 | 19/19，`independent-contracts.json` |
| 初始 quick | `quick-1iupq39q/workflow.json`，通过 |
| full | `full-xdidtvut/workflow.json`，146 工具单测、3 smoke、106 M1、40 ctypes、990 generation/ISS，通过 |
| M1 | `full-xdidtvut/m1/m1-gb14kv1d`；三个 access seed 实际使用 FORCE 预留池 |
| Fault V2 | `full-xdidtvut/fault_v2/run_yhmbtv32`；既有严格 guest-scope 与其余路径无回归 |
| 真实池合同模板 | `force-pool-q4zeazbl/pool-contract.json`，3/3 seeds，通过，含输入前后哈希和实际库加载记录 |
| PTG allocator 诊断 | `allocator-probe-final.json`，B003/B004 命中；不是通过验收 |

真实模板 `tests/riscv/ptg_reserved_pool_force.py` 先选择一段 FORCE 可用内存，在前半段
建立一个已有 reservation 和哨兵；owned pool 必须落入剩余半段。严格加载 PTG 页表后，
通过真实 M-mode LD 读回邻居哨兵。PTG 销毁后再对池内发起 genPA，要求出现明确的
`ConstraintSet is empty`，从而验证实际分配器排除而非仅检查 mock 调用记录。

原失败 `force-pool-v_9ylj0b` 保留：fixture 用 `initializeMemory` 写出了不符合本测试
小端期望的字节序，日志显示 `123456789abcdef0`。改成显式 `<Q` 字节写入后，保留
原 x2 目的寄存器再次通过；不是 PTG 表写破坏邻居。中间通过目录也保留，最终以表中目录
为准。full 后仅做换行和专项 runner 证据字段完善，专项已重新执行。

复现命令（Bash、仓库根目录）：

```bash
source ./setenv.bash
export PYTHONDONTWRITEBYTECODE=1
python3.12 utils/regression/run_ptg_pool_contract.py \
  --handcar-so "$PWD/output/handcar-pinned-build-v2/handcar_cosim.so" \
  --ptg-lib "$(realpath ../page_table_generator/build/libptg.so)" \
  --artifact-root "$PWD/output/ptg-pool-integration"
```

专项 runner 每次创建新目录，检查模板强断言 marker、非空 ELF、返回码、库加载与主要
输入前后哈希。它是生成期 Handcar 验证，不是 M1 式逐指令外部审计或独立 ELF 重放。
host 单测另覆盖锁内选址/预留、选择与预留失败时解锁、PTG 注册失败保留 reservation、
writer/bank/SPAs 越界拒绝、GPA/SPA 区分、旧接口逃逸拒绝及错误 G root 的失败传播。

## 状态

A001 仅完成首期专用池合同，未整体关闭。B003/B004/R003 已收到回函并通过顶部所述
候选验收；原始失败证据保留。未修改外部 PTG、未安装库、未提交或推送。
