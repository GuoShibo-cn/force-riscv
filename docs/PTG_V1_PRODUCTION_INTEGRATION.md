# PTG v1 生产适配：首批模板迁移

## 当前结果

后续已接入 [placement v1 生产封装](PTG_PLACEMENT_PRODUCTION_INTEGRATION.md)，新增
不可变策略、独立 allocation 状态域和窗口控制，并完成新 ELF 的独立执行与语义审计。

2026-09-20 后续已增加[FORCE 预留的 PTG 页表池](PTG_RESERVED_POOL_INTEGRATION.md)，
仅 M1 access 模板开始使用该 owned-pool 合同；本文其余内容保留首批 v1 迁移的验证范围。

2026-09-19 已在 `py/riscv/paging/PtgBackend.py` 正式接入已验收的 Mapping Query v1 / Strict
Export v1，迁移正常访存与 guest-scope 两类模板。仍是 PTG 生成页表，FORCE 负责适配、
内存写入和指令生成；没有新增 native 页表生成路径，也没有把结构查询当作访问授权。

使用 PTG 候选 SHA-256
`8a56c462624b3cf7b1636b0021913ba0bf8e10a863910fef4c224997c05bcca0`，Handcar 为隔离库
`a1013545508251676b63ec93686cd305a7c7140a1795887193a11061e3529224`。
候选的独立验收背景见 [v1 验收反馈](PTG_MAPPING_EXPORT_V1_ACCEPTANCE_FEEDBACK.md)。

## 生产 API

以下方法同时提供在 `PtgHandle` 和 `PtgBackend`：

| API | 返回/合同 |
| --- | --- |
| `query_mappings(ctx_id, stage, address=0, direction="forward", domain="current")` | 调用者拥有的 `PtgMappingRecordV1` 列表；空列表表示无记录，PA=0 不是未命中 |
| `capture_export_layout(ctx_id, stage)` | `PtgExportLayout` 对象；捕获健康 managed backing，冻结 placement 而非 PTE 字节 |
| `load_export_layouts(layouts, gen_thread, mem_bank=0)` | 先完整 pull 并验证全部布局，再调用 `writePhysicalMemory()`；错误向上传播 |

`stage` 为 S/VS/G 或 0/1/2，方向为 forward/reverse/enumerate 或 0/1/2，域为
current/logical 或 0/1。枚举要求 address=0。context/address/memory bank 的无符号范围
在进入 ctypes 前检查，避免负数或超宽整数被静默截断。

生产 ctypes 结构分别为 `PtgMappingQueryV1`、`PtgMappingRangeV1`、`PtgMappingRecordV1`、
`PtgExportLayoutRequestV1`、`PtgExportBlockV1`，与已验收公共 ABI 一致。
初始化、preflight、fill、free 均检查**版本化状态码**；`PtgMappingError.status` 和
`.operation` 保留错误域与阶段，不调用 legacy `last_error()` 推断新接口是否成功。

### 查询

当前示例只读取元数据，后续真实访问仍由 Handcar 验证：

```python
from riscv.paging.PtgBackend import (
    PTG_MAPPING_VALID_CURRENT,
    PTG_MAPPING_VALID_MATCH,
)

records = ptg.query_mappings(context, "VS", gva)
needed = PTG_MAPPING_VALID_CURRENT | PTG_MAPPING_VALID_MATCH
if len(records) != 1 or (records[0].valid_fields & needed) != needed:
    raise RuntimeError("No structurally current VS mapping")
gpa = records[0].matched_pa  # Zero is valid; this is GPA, not final SPA.
```

故障后 forward 查询可以返回含 logical/PTE 信息、但没有 CURRENT/MATCH 的诊断记录。
必须检查 `valid_fields`，不能仅检查列表非空。raw_perm、current-valid 不替代 privilege、
SUM/MXR、HLVX 或访问权限判定。单个 stage 查询不自动组合 VS/G，也不创建映射。

### 捕获、故障注入与装载

在同一 context 的所有映射已建立并检查后：

```python
with ptg.capture_export_layout(context, "VS") as vs_layout:
    with ptg.capture_export_layout(context, "G") as g_layout:
        # If needed, commit the validated PTG fault request here, after capture.
        ptg.load_export_layouts((vs_layout, g_layout), gen_thread)
```

- `PtgExportLayout.read()` 返回 `(block_records, bytes)`，完整 pull 后验证头部、stage/
  地址域、偏移连续性、长度及地址溢出。S/G 的 source address 必须是同一 SPA，VS source
  是 GPA。合法零 SPA 保留。
- 对象支持 `with` 和幂等 `close()`。显式关闭失败会报告错误；析构只做尽力清理。
  `PtgHandle.destroy()` 由 PTG 释放剩余布局，所有旧 layout 对象随后不可读，close 不再
  调用已销毁 handle，避免 double-free。
- batch loader 先检查所有对象的 handle/context 所有权，完成全部 pull，再检查 SPA
  区间互不重叠，最后写目标内存。第二个 stage stale 时不会先写第一个 stage。
- 当前 batch 合同限**同一 context、互不重叠的 SPA blocks**；包括重复布局在内的重叠
  被明确拒绝，不静默合并共享 bytes。这是首期 FORCE adapter 限制，不是 PTG 不支持共享。
- 两次调用的数量/长度变化、容量错误、错误元数据均失败，不截断、不自动重试/重建。
  STALE_LAYOUT 必须由调用者基于有意的图/绑定变更处理，不能在故障后偷偷重新捕获。
- writer 抛异常立即停止，但此前已写入的 block 不回滚。内存/临时 snapshot 消耗与导出
  大小成正比；所有 calls/mutations 必须由调用者串行化。
- 普通 `PtgBackend()` 的本方法不预留 FORCE 地址；后续 `with_reserved_table_pool()`
  额外绑定原 writer/bank 和池内 SPA。两者都不自动发现 RAM/MMIO 或覆盖所有显式数据
  写入冲突，A001 整体未闭环。架构访问前显式初始化页表/数据的要求不变。

旧 `load_to_force()` / `get_force_blocks()` 仍保留供尚未迁移的用例显式调用。
新 API 不调用它们，也不降级到 legacy callback 或 native 页表后端。

## 已迁移路径及覆盖范围

1. `ptg_two_stage_fixed_force.py`：用 Query v1 校验已知 VS/G 元数据，采用严格 VS/G 装载。
   保留原软件翻译、HLV.D、4 KiB 跨页、2 MiB/1 GiB 及混合页尺寸数据断言。
2. `ptg_hypervisor_access_matrix_force.py`：切换装载路径，保留 HLV.D、HSV.D→HLV.D、
   M-mode 物理 LD 回读、HLVX.WU 与 hvip 断言。它补足真实生产装载下的 store/物理读回验证。
3. `ptg_fault_v2_guest_scope_common.py`：由 guest-implicit 和 guest-explicit 模板共同消费。
   在 healthy validation 后捕获 VS/G，随后执行原 V2 dry-run/commit，最后按冻结布局
   装载当前字节。原 PTE 单槽修改、stage 隔离、trap CSR 及无副作用检查均保留。

已核对最终 full 中的严格装载 marker：M1 的 100 个 two-stage 和 3 个 access 用例，
以及 Fault V2 三 seed 的 **81 个 guest-scope generation 用例**。这不是 990 个任务全都
改走了新 API：剩余 direct cause 矩阵、M1 fault matrix 和其他旧 PTG 模板仍待迁移。

M1 保留原逐指令外部审计；Fault V2 保留原模板强断言、两执行阶段和库加载证据检查，
本轮没有把它升级宣称为 M1 式全依赖冻结/逐指令外部审计。

## 验证证据

证据根目录：`output/ptg-v1-production/`。

| 检查 | 结果 / 证据 |
| --- | --- |
| ctypes + wrapper | **32/32**，`ctypes-final.log`；其中 17 项新生产封装测试，15 项既有测试 |
| 独立下游 ABI 合同 | **19/19**，`independent-v1.json`；未用生产结构替换独立声明，测试源哈希仍为 `c0122312...` |
| 最终模板 full | `full-isp_35fv/workflow.json`，rc=0；145 工具单测、预检、3 smoke、106/106 M1、32 ctypes、990/990 generation 和 ISS |
| M1 归档 | `full-isp_35fv/m1/m1-1bh_jvkx` |
| Fault V2 归档 | `full-isp_35fv/fault_v2/run_soz6oo6r` |
| 预检诊断修复后的 quick | `quick-erj9n5oo/workflow.json`，rc=0；146 工具单测、预检及 3 smoke |
| 老 PTG 拒绝 | `old-candidate-preflight-final.log`；旧 `9eeac7b2...` 库缺少新符号，明确报 `lacks Mapping Query/Strict Export v1` |

新增测试覆盖：PA=0/SPA=0、alias 与 logical/current、A/D 不变、输入范围、能力缺失、
context manager 清理、父 handle 销毁、显式 free 失败、G backing 故障后的冻结地址和
当前 bytes、第二 stage stale 零写入、writer 部分写失败、异属/跨 context/重叠拒绝、
协议数量变化及错误元数据拒绝。

`ctypes-v1.log` 中首次失败是测试建立了 context/stage 却未创建映射，capture 正确返回
TREE_NOT_FOUND；修正夹具后通过。`full-rg94ksim` 为较早完整通过记录，最终模板结果以
`full-isp_35fv` 为准。后续仅修改预检错误文本渲染并新增工具单测，用 quick 定向验证；
没有混用或改写旧报告。

## 预检与剩余工作

M1 预检现在检查 Query/Strict Export v1 六个符号。仅导出错误文本时过滤 glibc PID
前缀的 shutdown 噪音，避免真正的 Python 能力错误被截断；库加载证据仍使用未过滤的
原始 stderr。能力检查不等于新 ABI 的完整语义验收。

本轮没有新增需要 PTG 修改的功能缺口；上述空树拒绝与 stale 等均按已验收合同执行。
新增 FORCE 工具问题 F002（预检诊断被 loader 尾部淹没）已修复并记录到台账。
后续仍需：迁移剩余 legacy 装载用例、解决 A001 地址池预留/宿主内存所有权，接通
PTG-backed C++ Mapper 与生成器约束，以及逐项核验 A003 legacy void 调用错误处理。

未安装、未提交、未推送，也未修改 PTG 外部仓库、Handcar 库或此前 native 历史改动。
