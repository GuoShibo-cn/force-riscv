# PTG placement v1 生产适配

## 当前结果

后续已完成 [GenThread 托管上下文闭环](PTG_MANAGED_CONTEXT_INTEGRATION.md)，消费本模块的
预留池与 checked API，提供受约束映射、结构查询和显式 CSR/fence 激活；C++ Mapper 尚待接入。

已在 `py/riscv/paging/PtgBackend.py` 正式绑定四个 placement v1 C API，并接入 FORCE
预留池、M1 access matrix 及 guest-implicit/guest-explicit 模板。页表地址选择、对齐、
padding 占用与层级回退全部由 PTG 实现；FORCE 负责约束输入、宿主所有权和错误传播。
本轮未发现新的 PTG bug/API 缺口，未修改外部 PTG 或 Handcar 核心。

R003 的首批 Python 生产适配已完成。A001 通用池生命周期、A003 其余 legacy 错误处理、
PTG-backed C++ Mapper 仍未完成；本轮没有解除 owned pool 的单 VMID/context 限制。

## 生产接口

```python
from riscv.paging.PtgBackend import PtgBackend, PtgPlacement, PtgAllocationError

ptg = PtgBackend.with_reserved_table_pool(
    gen_thread, "MyPageTables", 0x100000, 0x88000000, 0x89000000,
    lib_path=ptg_library,
)
try:
    base = ptg.table_pool.base
    ptg.configure_pa_placement(PtgPlacement(levels=(
        (2, base + 0x10000, base + 0x14000),  # Sv39x4 root priority window.
        (1, base + 0x20000, base + 0x28000),
        (0, base + 0x30000, base + 0x38000),
    )))
    ctx = ptg.create_two_stage_context(
        asid=1, vmid=1, gpa_base=0x90000000, gpa_limit=0x91000000,
        gpa_placement=PtgPlacement(levels=((2, 0x90008000, 0x90009000),)),
    )
    # Add mappings through PTG; capture and load with Strict Export v1.
finally:
    ptg.destroy()  # The FORCE reservation remains live for the generation session.
```

| API | 合同 |
| --- | --- |
| `PtgPlacement(base=0, limit=0, alignment=0, levels=())` | 不可变策略值，嵌套窗口复制成 tuple；地址为绝对 PA 或 GPA |
| `configure_pa_placement(policy)` | 在已注册 PA 所有权内设置策略，Handle/Backend 均提供 |
| `configure_gpa_placement(vmid, policy)` | VMID-local GPA 策略，Handle/Backend 均提供 |
| `create_two_stage_context(..., pa_placement=None, gpa_placement=None)` | 注册 region 后、创建根表前应用策略；启用 placement 的路径先配置 G，再配置 VS |

区间均为半开 `[base, limit)`。`base=limit=0` 表示全部已注册 region 的 GENERAL view，
`base=0, limit>0` 是显式区间；零根地址合法，成功只看状态。`alignment=0` 表示自然
对齐，非零必须为 2 的幂。`levels` 为有序 `(level, base, limit)` 三元组，level 为 0..4，
拒绝重叠/重复窗口，允许相邻窗口；校验用排序副本，不改变传入 PTG 的窗口优先顺序。
VMID setter 检查 uint16，高层 RV64 context/owned pool 继续限制为 14-bit VMID。

PUBLIC C ABI：`PtgPlacementConfigV1` 40 字节、`PtgLevelPlacementV1` 32 字节、自然 LP64
对齐；初始化器/设置器使用 `c_int32` 返回码，数组 count/stride 固定按声明传递。PTG 同步
复制输入，不持有 Python ctypes 缓冲区。Python `_replace/_make` 绕过构造器的值也会在
调用时重新校验，避免 bool、负数、超宽整数被 ctypes 静默截断。

## 能力和错误边界

- `PtgAllocationError.status/operation` 保存 **PtgStatus**，与正值 MappingStatus/FaultStatus
  分开。例如未注册池为 -7，越界 policy 为 -4，耗尽为 -9，不解释为 query 状态 7/4。
- 缺任一 placement 符号即失败；owned-pool 工厂在 FORCE 选址/预留之前检查能力，不回退
  到手动 padding 或另一套 allocator。M1 预检现在也要求 placement v1。
- 工厂默认应用 all-owned/natural PA policy，保留原 scheduler 锁、选址、预留、writer/bank
  与严格 SPA 边界检查。GPA policy 不能切换到 owned pool 的其他 VMID。
- policy 设置失败保持旧策略与占用，不把健康 owned pool 标记为失效；配置成功不意味着
  已有根表移动、host RAM 扩张或硬件 fence 已执行。
- placement 启用后，region/context/stage/add_mapping/random 的适用调用检查 legacy
  `last_error`；random 分配失败不再作为“零条映射成功”返回。其余未启用路径与其他
  legacy mutation 的全面错误合同仍属 A003。
- 单次 stage replacement 的失败原子性不等于高层创建 VS/G 的整体事务：G 已成功而 VS
  失败时不自动回收 G。增量 mapping/backfill 失败也可能保留此前提交的映射。
- owned-pool setup 失败保留 FORCE reservation，并沿用既有失效保护。在线策略调用和
  同 handle 的其他操作须由调用者串行化；未提供并发/hardware 原子事务或自动回收。

## 已接入场景

1. `ptg_hypervisor_access_matrix_force.py`：在真实预留池内为 G L2/L1/L0 和 VS L2/L1/L0
   设置窗口；断言 G root=`pool.base+0x10000`、VS root GPA=`0x90008000`。建表/capture 后
   在线更新 PA/GPA alignment，逐字节核对 CSR、导出 metadata 和 PTE 不变，再严格装载，
   执行 HLV/HSV/物理回读/HLVX。seed 1 的 pool base=`0x88E08000`。
2. `ptg_fault_v2_guest_scope_common.py`：在 guest implicit/explicit 场景设置 PA/GPA 根表
   窗口并强断言，随后执行原故障注入及 trap CSR 检查；新 ELF 由 FPIX 独立重放与逐步审计。
   这些模板仍是显式固定地址 region，未宣称已经获得 owned-pool 的 FORCE 预留合同。

guest-explicit、G level 2、seed `0x15c0ffee` 的新独立执行为 **507 步**，实际观察到
causes 21/23/20；相较上一轮 506 步，多出的 CSR 常量构造指令不是错误。验收不写死总步数。

## 验证与身份

证据根目录：`output/ptg-placement-production/`。

| 检查 | 结果/目录 |
| --- | --- |
| 修改前 quick | `quick-qii4_30z/workflow.json`，通过 |
| 公共 ABI 独立验收 | `independent.json`，39/39，未复用生产 ctypes 声明作为 oracle |
| ctypes/生产封装 | 52/52，其中新增 12 项 placement 测试 |
| 实际 reservation/邻居/销毁后禁止复用 | `pool/force-pool-s_kehmr2/pool-contract.json`，3/3 seeds |
| 最终 full | `accepted/full-o6uvaf8a/workflow.json`，155 工具单测、3 smoke、106 M1、52 ctypes，通过 |
| ELF 独立重放及语义审计 | `accepted/full-o6uvaf8a/fault_v2/run_5fv7_1hl/manifest.json`，990/990 |
| M1 逐指令证据 | `accepted/full-o6uvaf8a/m1/m1-jodt1no7`，106/106 |

新增单测覆盖：ABI/负状态域、不可变值和参数拒绝、零根、优先顺序与 GENERAL 回退、
VMID-local GPA、耗尽状态、旧映射/旧 CSR 保留、在线策略不使 layout stale、失败策略
保持池可用、能力缺失先于宿主预留、销毁后拒绝调用。

| 输入 | SHA-256 |
| --- | --- |
| PTG libptg.so | `dfee221f7417e950ee1ca93c9a8df697148c5ed50359590e5a82148f0646b082` |
| PTG ptg_allocation.h | `952121074807457f167a126864599a769e8f060fdce3a683a2e7358bbf28fe30` |
| PtgBackend.py | `3e6df83c72bb5f092e192d5904b1690ee9b4a7938241824d70e77ad814567991` |
| Handcar | `3af0cb331e3d6f7a9e77f48304574c8183e14a6099bca8752eaf9f6c28be3cad` |
| friscv | `ee83a3ad07b7b994cee5ef4bfd7b6340ccf7865d3a6feb17ba73c9a846c1a333` |
| FPIX | `f80269fc562e05d88ce42e4ab4a5ce9391803a6742a80f067b54d85476b9c42a` |

复跑使用 [FPIX 重放验收](FPIX_ELF_REPLAY_ACCEPTANCE.md) 的显式二进制/配置命令，将
artifact-root 换成新目录。库身份与上轮相同，Python adapter/模板已经更新，不能复用旧
模板通过记录。库未安装、代码未提交/推送；既有 PTG stress 两项失败不在本轮修复范围。

下一步：将这些已验证的 PTG adapter/所有权/错误合同接入更通用的上下文与地址约束路径，
设计 CSR/fence 与多 context 生命周期，再逐步扩展受限池及 PTG-backed Mapper。
