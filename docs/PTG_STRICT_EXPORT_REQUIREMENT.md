# R001：面向 FORCE 的严格页表导出合同

## 分类与基线

**2026-09-19 更新：** 候选 `8a56c462...` 的 Strict Export v1 已通过 FORCE 独立限定
验收。旧 callback fallback 保持兼容；首批模板已通过新增生产 API 迁移，旧
`load_to_force()` 仍为 legacy，当前覆盖见[生产适配说明](PTG_V1_PRODUCTION_INTEGRATION.md)。
下面保留原需求和旧库复现，最新结论见[验收反馈](PTG_MAPPING_EXPORT_V1_ACCEPTANCE_FEEDBACK.md)。

**分类：PTG API 需求；现有危险回退行为已独立复现，待用户转交维护者。**
目前不将其描述为新的 RISC-V 翻译算法错误。旧 `ptg_dump_binary_write` 的源码明确实现
了该回退，FORCE 旧 fault 测试也知道此行为；请维护者决定通过新增严格接口还是版本化
合同修复解决，不直接破坏已有诊断/故障注入用户。

- PTG HEAD：`1cdf8415efe36533744411d9c7798b036f1fbc76`。
- 库 SHA-256：`9eeac7b2f69c25f9a778974c1ab1ba71f47fc29c50749070e48e2d77f1eabb29`。
- 本机库：`/home/guoshibo/page_table_generator/build/libptg.so`。
- 公共头 SHA-256：`3f7fff2ce6e86a9aeb987c3e61cd4cfa63f9d17a74cf623d9290402a5281fc73`。
- 复现仅加载 PTG，不使用 FORCE Mapper、Handcar 或 FORCE wrapper，不写依赖仓库文件。

## FORCE 场景

FORCE 希望把 PTG 提供的页表 block 装载到宿主 SPA，并初始化同一块 Handcar RAM。
因此“block 的地址是可靠 SPA”必须是可检查的合同。把未翻译 GPA 当 SPA 写入会污染
其他宿主内存；单凭 `last_error=PTG_OK` 无法安全启用 guest。
同时，故障注入流程需要按**原始 backing 布局**装载被修改的 PTE，不能通过已故障的
G-stage 页表重新猜测 VS 节点位置。

## 最小复现

FORCE 仓库已提供独立脚本：`tests/riscv/ptg_export_contract_probe.py`，只依赖 Python 标准库。
在 FORCE 根目录的 Bash 中执行：

```bash
source ./setenv.bash
export PYTHONDONTWRITEBYTECODE=1
python3.12 tests/riscv/ptg_export_contract_probe.py \
  --ptg-lib /absolute/path/to/libptg.so
```

步骤：注册互不重叠的 SPA 池（base=`0xA0000000`、limit=`0xB0000000`）和 GPA 池
（base=`0x80000000`、limit=`0x90000000`）；创建 Sv39/Sv39x4 context，加入一个 VS 4 KiB 映射；
先正常导出 VS，再调用 `ptg_context_clear(h, ctx, G)` 清空 G leaf 后重新导出 VS。
脚本发现危险回退时返回 **1**，只表示复现命中；它不是安装验收，也不纳入默认 full。
未命中时返回 0 也不意味着新严格合同的全部验收通过。

原始输出：`output/ptg-first-integration/export-probe.json`；加入健康 SPA 基线检查后重跑的
输出为 `output/ptg-first-integration/export-probe-final.json`，两次都复现以下结果。

| 项目 | G-stage 健康 | 清空 G leaf 后 |
| --- | --- | --- |
| VS root GPA | `0x80000000` | 同一 root |
| 导出 block 写地址 | `0xA0004000`、`0xA0007000`、`0xA0008000` | `0x80000000`、`0x80001000`、`0x80002000` |
| 每 block 长度 | 4096 | 4096 |
| `ptg_last_error()` | 0 | **仍为 0** |
| 回调 | 3 次，写地址位于 SPA 池 | **3 次，写地址退化为 GPA** |

**严格装载场景的预期**：无法取得合法 SPA 时返回明确失败，不能默默把 GPA 当 SPA；
如果 API 允许 raw GPA 输出，必须显式选择并携带地址类型，不能与正常 SPA 导出混为一谈。

源码线索：`src/api/ptg_api.cpp:2630-2660`。VS 导出回调通过 G-stage `walk(Read)` 求 SPA，
`wr.hit=false` 时保留原 `addr`，仍调用用户 callback，函数末尾将 `last_error` 设为 OK。
这是对该版本的源码定位，不代替上面的真实库复现。

## 已核对的现有接口

- `ptg_dump_binary_write` 有 VS GPA→SPA 投影，但存在上述失败回退，callback 和函数均为 void。
- `ptg_dump_binary_blocks` 导出 raw sparse blocks，VS 地址不能自动当作 SPA；不能用它替换
  write 导出后就声称问题解决。
- `ptg_last_error` 能报告不存在的 context/tree，FORCE 应检查它；但不能检测这里返回 OK 的情况。
- 内存/JSON/walk-report 导出可以辅助诊断，尚未证明提供同一份冻结的 VS/G SPA 布局合同。

## 建议与验收标准

建议复用现有 PTG 树、OutputSink 和 backing 分配信息，新增严格模式或版本化接口。
具体 ABI 名称留给维护者设计；FORCE 不要求为了此需求重建另一套 PTG 实现。

1. 明确区分 raw stage 地址与宿主 SPA；结果至少能标识 stage、节点 GPA（适用时）、SPA、
   block 长度和状态，不使用 PA=0 等歧义 sentinel 代替有效性字段。
2. 严格 SPA 导出对缺失/不可导出的 G backing 返回非成功状态，不回退到 GPA。应先验证
   整个导出计划，再触发外部写回调，避免部分输出后才发现地址无效。
3. 为故障注入提供明确的 backing snapshot/layout 机制：健康时冻结布局、之后按该布局
   导出 mutation，或直接使用与当前 faulting walk 无关的分配元数据。不能将 fault 页表
   的投影失败视为宿主地址。
4. 说明 snapshot 的生命周期、同一 handle/context 的并发限制、CSR/root 绑定、映射新增
   后旧布局失效条件及 buffer 所有权。
5. 明确导出是否允许 A/D 写回、TLB/cache 改变或其他可见副作用。严格 snapshot 期望没有
   架构状态 mutation；这一点目前是**待验收的需求**，本复现没有证明已有 A/D 副作用 bug。
6. 增加健康非恒等 GPA/SPA、缺失 G leaf、权限/A-D fault、跨页/不同页尺寸及导出部分失败
   测试。预期宿主地址应来自独立构造的映射/布局，而不是调用待测导出器生成 expected。
7. 保留或明确版本化旧诊断导出语义。现有 990-task Fault V2 依赖 mutation 后的装载流程，
   FORCE 将在新接口可用后独立验收并迁移，不以旧库 PASS 自动接受新版本。

## 当前处理

FORCE 已修复自己的 writer 异常和 `last_error` 丢失问题（台账 F001），但这不解决 R001。
在严格合同具备前，不将现有导出升级宣称为任意 context/mutation 下的安全自动装载。
原需求已由用户转交，维护者回函及新接口验收见顶部更新。新 API 交付已通过，下一步
迁移 FORCE 生产导出链路；本次未修改外部 PTG 仓库或旧回调的兼容语义。
