# PTG Mapping Query / Strict Export v1：FORCE 独立验收反馈

验收日期：2026-09-19。

同日后续已完成 Python 生产封装和首批模板迁移，见
[生产适配说明](PTG_V1_PRODUCTION_INTEGRATION.md)。本文保留候选验收当时的对象与范围。

## 1. 结论

**本轮候选通过限定合同验收。** 未发现本次查询/严格导出合同范围内的新增阻塞问题。
这不是 PTG 全部测试通过、FORCE 生产 adapter 已迁移或用户授权安装的声明。

| 台账项 | 下游结论 |
| --- | --- |
| B001 | 修复验收通过：Clear 后旧正反向关联消失，并保留其他 context 的映射 |
| B002 | 修复验收通过：页内 remap 更新整页与 reverse alias，包括共享根路径 alias |
| R001 | **新 Strict Export v1 API 验收通过**；生产 `load_to_force()` 仍使用 legacy 导出，迁移未完成 |
| R002 | **新 Mapping Query v1 元数据合同验收通过**；不是权限授权，PTG-backed C++ Mapper 未接通 |
| A001 / A003 | 保持开放；没有验收通用宿主 RAM allocator、MMIO 动态排除或全部 legacy wrapper 失败边界 |

维护者已披露的 stress 两项失败仍可复现，不能把本轮写成“整个 PTG 全绿”。旧
`ptg_dump_binary_write` 的 GPA fallback、旧精确键/PA=0 歧义也仍是兼容语义，新调用者
必须采用版本化接口，不能因换了库就认为旧接口自动安全。

## 2. 验收对象与输入身份

回函实际位置是 **PTG 仓库**内：
`.omo/evidence/ptg-mapping-query-strict-export/maintainer-response.md`。
同时核对了 `final-review-summary.md`、公共头及 `docs/MAPPING_QUERY_AND_EXPORT.md`。

| 输入 | SHA-256 |
| --- | --- |
| `page_table_generator/build/libptg.so` | `8a56c462624b3cf7b1636b0021913ba0bf8e10a863910fef4c224997c05bcca0` |
| `page_table_generator/build/libptg.a` | `f11b497df4108c54b63b2b808424172cb1836780e5cceca0dcb6e3868ca910a1` |
| `ptg_mapping_query.h` | `f87f1ae53d60db30dfddfe1d41d407df53e28207830492e3c8d3aa2141a31274` |
| `ptg_export_layout.h` | `97b4bfecb7e9589287170165038041fd56a9c3b6c0007d6c1170dcf24f9006a3` |
| 隔离 Handcar `output/handcar-pinned-build-v2/handcar_cosim.so` | `a1013545508251676b63ec93686cd305a7c7140a1795887193a11061e3529224` |

PTG 的 base HEAD 仍为 `1cdf8415efe36533744411d9c7798b036f1fbc76`，但候选包含未提交的
实现，**不能仅凭该 HEAD 重现本候选**。上述共享/静态库哈希均与回函相符，验收前后未变。
本机候选库已有 M1 冻结副本：
`output/ptg-contracts-acceptance/full-azkh8dfv/m1/m1-2hb27uh9/inputs/bin/ptg/libptg.so`。
M1 归档需保持原绝对位置；不要移动或改写它。

## 3. 独立下游检查

新增测试源：`tests/riscv/ptg_mapping_export_acceptance.py`。
它根据公共头手工声明 ctypes ABI，使用固定映射、原始 PTE 和独立已知 GPA→SPA 关系
构造预期，没有导入维护者测试 helper，也没有复制待测查询结果生成 expected。
基本 handle/旧 C API 调用复用现有 FORCE wrapper；新版本化 API 的返回码直接判断，
不与 `ptg_last_error()` 的 legacy 错误域混用。

最终 **19/19 测试通过**，覆盖：

- LP64 struct 大小/关键偏移、initializer、扩展 struct/stride 尾部 canary。
- PA=0 与未命中、页内 forward/reverse、全部 alias、枚举无 match 标志、2 MiB/1 GiB。
- S/VS/G 地址域，VS 的 PTE 地址及结果仍为 GPA；64 位、负 canonical 和高位 GPA。
- Sv48/Sv57 的基本 current-range 与 S-stage 导出；这些模式没有升级到 Handcar 执行验收。
- Clear/remap 后的索引及 context 隔离；真实共享根路径的别名随物理 leaf remap 更新。
- 故障后 logical/current 分离、invalid-range 的零字段与 level=-1、原始 PTE 精确匹配。
- A/D=0 的 S-stage 查询和导出无 PTE 改写；G-stage A=0、ADUE=1 时 VS 捕获/读取也无写回。
- 参数、ABI、context/tree、输入输出重叠、容量不足时无数据缓冲区部分改写。
- VS 非恒等 backing 与合法 SPA=0；完整 block 元数据及每段字节与 raw snapshot 一致。
- G leaf Clear 后新 capture 返回 BACKING_UNAVAILABLE，而旧 layout 保留 SPA 并读当前 VS 字节。
- G leaf remap 改变 current query，但不改变旧 layout 的 SPA；新 capture 才获得新布局。
- 新增同一节点中的 leaf 不使 layout 失效；实际节点图增长触发 STALE，数据缓冲区保持不变。
- VS 需要硬件 A/D 写回而 G backing 只读时拒绝 capture；拒绝过程不改变 PTE。
- layout 的 foreign handle、free(0)、double-free 和 freed ID 拒绝。

证据：`output/ptg-contracts-acceptance/downstream-final.json` 和 `downstream-final.log`。
JSON 记录测试源哈希、库前后哈希、测试数量、时间和错误列表。

### 保留的测试开发失败

- `downstream-v1.*`：SPA=0 未注册进 PTG PA placement 池，capture 正确返回 7。最终测试
  先断言该拒绝，再注册 `[base=0, limit=0x200000]` 验证零 SPA 成功。这是夹具缺少
  managed-backing 前提，不是候选零地址 bug。
- `downstream-v2.*`：尝试在 ADUE=1 时注入 ADZero，Fault V2 正确返回 UNSUITABLE_TARGET。
  最终夹具先在 ADUE=0 下建立 A=0，再打开 ADUE=1，独立读取 raw PTE 确认前提后验收
  只读查询/导出。没有通过手写 PTE 或改动 PTG 绕过拒绝。
- `downstream-v3.*` 已通过，最终版本进一步增加 raw G PTE 校验；以 `downstream-final.*`
  为最终证据，失败与中间文件原样保留。

## 4. 新严格导出 → 独立 Handcar

新增独立消费者：`tests/riscv/ptg_strict_export_iss.cc`。它只通过 PTG 构造页表，用
Strict Export v1 的 capture/preflight/pull 取得 VS/G 地址域明确的 block，检查完整结果
后由宿主显式初始化 Handcar RAM。没有 native 页表生成器或手写 PTE。

实测 **9 条架构指令**：

1. 两组 HLV.D → HSV.D → HLV.D，分别覆盖 4 KiB 页内 offset `0xffc` 的跨页访问和
   双 stage 2 MiB leaf；寄存器哨兵及独立固定 SPA 的物理读回均正确。
2. 新 query 报告 execute-only VS leaf 结构有效，但真实 HLV.D 产生 **cause 13**，
   mepc/mtval 和无目的寄存器副作用正确。这证明没有把 current-valid 当作权限授权。
3. 对 G data leaf 注入 V=0，按之前捕获的 G layout 重新 pull 当前字节并同步，执行真实
   HFENCE.GVMA 后 HLV.D 产生 **cause 21**；mepc、mtval、mtval2=GPA>>2 和无副作用正确。

证据：`strict-iss-v1.log`、`strict-iss-loader.log`。后者含 glibc `calling init:`，确认实际
加载了本轮候选 `libptg.so` 和指定隔离 Handcar，而非仅在命令行写出库路径。
该消费者是独立 ABI/ISS 执行，不是生成期 Python 模板、完整 ELF 重放或生产 adapter 迁移。
宿主显式初始化不等于新增通用 RAM 分配器，也不承诺外部写入可原子回滚。

## 5. 维护者清单复跑与 FORCE 回归

为保留外部工作区和候选二进制，没有在 PTG 仓库执行会重建依赖的 make 目标。
按其显式清单执行了现有八个 native binary、公有 Python probe；两份 C99 示例在本轮
FORCE 输出目录重新编译，链接指定候选共享库并运行。

| 项目 | 本轮结果 | 证据（均在 `output/ptg-contracts-acceptance/`） |
| --- | --- | --- |
| 八个 native binary | 41、127、31、41、161、190、18、81 checks，全过，共 690 | `vendor-test_*.log` |
| 公有 Python probe | 49 checks 通过，包含库哈希 | `vendor-public-probe.log` |
| C99 query/export 示例 | 11 / 14 checks 通过 | `vendor-c-query.log`、`vendor-c-export.log` |
| FORCE full | rc=0，145 工具单测、预检、3 smoke、106 M1、15 旧 ctypes、990 generation/ISS | `full-azkh8dfv/workflow.json` |
| M1 原始目录 | 106/106 | `full-azkh8dfv/m1/m1-2hb27uh9` |
| Fault V2 原始目录 | 990/990 两执行阶段 | `full-azkh8dfv/fault_v2/run_polyf588` |
| Stress | **1026 passed，2 failed** | `vendor-stress.log` |

现有 native binary 复跑不是本轮冷构建来源证明；新的独立 ctypes 和 C++/C99 消费者均
直接加载/链接已核对哈希的共享库。维护者报告的其他 F1/F2/F3/F4、sanitizer、Z3 检查
不冒充本轮执行；本轮未重做全部 sanitizer/Catch2/冷构建。

Stress 的两个失败名称与回函一致：`at least 90% two-stage translations OK` 和
`Sv32x4 walk`。日志另有 `IOMMU verify: 0/10 passed` 诊断，不能据此声明 IOMMU 支持。
输出写在本轮隔离 `build/` 下，未覆盖 PTG 的旧 stress 文件。本轮没有重新构建 base HEAD
做逐字节比较，“这些是前存问题”的历史定位来源仍是维护者回函；不据此宣称 PTG 全局无回归。

旧 `ptg_mapping_query_probe.py` 也已复跑：B001/B002 对应标志为 false，而 legacy PA=0
歧义和精确键限制仍为 true，因此它仍退出 1，不能简单按此退出码否定新候选。
原始结果为 `legacy-query-probe.json`；该脚本的历史语义没有为求 PASS 而改写。

## 6. 复现本轮独立验收

在 FORCE 根目录 Bash 中，使用显式候选；输出路径换新名字，保留已有证据：

```bash
source ./setenv.bash
export PYTHONDONTWRITEBYTECODE=1
PTG_ROOT="/absolute/path/to/page_table_generator"
PTG_SO="$PTG_ROOT/build/libptg.so"
HANDCAR_SO="$PWD/output/handcar-pinned-build-v2/handcar_cosim.so"

python3.12 tests/riscv/ptg_mapping_export_acceptance.py \
  --ptg-lib "$PTG_SO" --report "$PWD/output/new-ptg-contract-report.json"

g++ -std=c++17 -Wall -Wextra -Werror \
  -I"$PTG_ROOT/include" -I"$PWD/utils/handcar" \
  tests/riscv/ptg_strict_export_iss.cc "$PTG_SO" \
  -Wl,-rpath,"$PTG_ROOT/build" -Wl,--export-dynamic -ldl \
  -o "$PWD/output/new-ptg-strict-export-iss"
LD_DEBUG=libs "$PWD/output/new-ptg-strict-export-iss" "$HANDCAR_SO"

python3.12 utils/regression/hypervisor_workflow.py --profile full \
  --handcar-so "$HANDCAR_SO" --ptg-lib "$PTG_SO" --jobs 8
```

本轮 C++ 消费者源 SHA-256：
`f596c63f3d0bee6af08a56308b6dbd20784ca49f697782174743cad328b591c4`；测试二进制 SHA-256：
`5b31b5be26d4b22eed46b55c9a48cceed3d5b91fd898d673335398b5aee3864f`。
Python 源哈希见 `downstream-final.json`；不同路径/工具链构建不保证二进制哈希相同。

## 7. 后续交接

- B001/B002 可按该候选哈希记为已验收修复；R001/R002 的版本化接口交付可接受。
- 下一步在 FORCE 生产 adapter 中接入 Query v1 / Strict Export v1，分别处理结构有效性、
  权限约束、logical/current、布局失效及故障后冻结 backing；不能简单替换函数名或读取
  legacy `last_error` 代替新状态码。
- A001 宿主地址所有权/RAM、A003 其他 legacy 配置/注册失败边界继续独立推进。
- 建议公共使用文档更明确写出：合法 G-stage PPN 并不足够，strict capture 还要求目标
  区间属于 PTG 声明的 placement 区域；这不等于宿主 RAM 已分配。SPA=0 也需此前提。
- 候选仍是未提交工作区产物；正式版本化交付需要维护者提供不可变源码身份和构建记录。
  本次通过只绑定上述二进制，不为后续不同哈希自动继承验收。

本轮未安装、未提交、未推送、未修改外部 PTG 源码或旧证据。两份原安装 Handcar 库仍为
`8ebad9706aeff632f18b5a77fb803829b687c25b95469e26b3f8eed8428ea786`。
