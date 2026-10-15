# PTG Bug Report: VS-stage 页表根地址与 vsatp PPN 不匹配

## 问题描述

PTG 的 `create_vs_stage` 分配的 `root_gpa` 与实际 VS-stage 页表根节点地址不一致，导致 vsatp 的 PPN 字段指向错误的地址。

## 复现步骤

```python
ptg = PtgBackend()
ctx = ptg.create_two_stage_context(
    vs_mode="Sv39", gs_mode="Sv39x4",
    asid=1, vmid=1,
    gpa_base=0x80000000, gpa_limit=0x90000000,
    pa_base=0x90000000, pa_limit=0xA0000000,
)

ptg.handle.add_mapping(ctx, "VS", gva, gpa, 0x200000, 0, 0x7F)
ptg.handle.add_mapping(ctx, "G", gpa, spa, 0x200000, 0, 0x7F)

vsatp = ptg.handle.get_vsatp(ctx)
# vsatp = 0x8000100000080000
# PPN = 0x80001 → 0x80001000
```

## 预期行为

vsatp 的 PPN 应该指向 VS-stage 页表的实际根节点地址。

## 实际行为

- vsatp PPN = 0x80001 → 0x80001000
- 实际根节点地址 = 0x80000000（从 dump 看）

```json
{
  "root_ppn": "0x0",
  "nodes": [
    {"level": 2, "base_addr": "0x80000000"}  # 根节点在 0x80000000
  ]
}
```

## Spike 错误日志

```
[WALK] addr=0x80200000 type=0 mode=0 virt=1 satp=0x8000100000080000 levels=3 ptbase=0x80000000
# Spike 使用 ptbase=0x80000000（从 vsatp PPN=0x80001 计算得到 0x80001000，但实际使用 0x80000000？）
```

等等，Spike 的 ptbase=0x80000000，这是正确的！让我重新计算：

vsatp = 0x8000100000080000
- MODE = bits 63:60 = 8 (Sv39)
- ASID = bits 59:44 = 1
- PPN = bits 43:0 = 0x80001

PPN = 0x80001 → PA = 0x80001000

但 Spike 日志显示 ptbase=0x80000000，这说明 Spike 可能从 vsatp 的其他位提取了根地址？

让我检查 RISC-V 规范的 vsatp 格式：

Sv39 vsatp:
- bits 63:60 = MODE (4 bits)
- bits 59:44 = ASID (16 bits)  
- bits 43:0 = PPN (44 bits)

PPN = 0x80001 → PA = 0x80001000

但 VS-stage 页表根节点在 GPA 0x80000000，所以 Spike 应该访问 GPA 0x80001000，但实际访问了 0x80000000？

让我重新检查 Spike 日志：

```
[WALK] addr=0x80200000 type=0 mode=0 virt=1 satp=0x8000100000080000 levels=3 ptbase=0x80000000
```

ptbase=0x80000000，这是从 satp 的 PPN 计算得到的。但 satp=0x8000100000080000，PPN=0x80001，应该得到 ptbase=0x80001000。

这说明 Spike 的 satp 解析可能有问题，或者 FORCE 写入的 vsatp 值与 PTG 返回的不一致。

让我检查 FORCE 写入的 vsatp 值：

从日志看：
```
[notice]Front-end: vsatp: 0x8000100000080000
[SimApiHANDCAR::WriteRegister] vsatp 0x8000100000080000/0xffffffffffffffff
```

FORCE 写入的 vsatp = 0x8000100000080000，这是正确的。

但 Spike 的 ptbase=0x80000000，这说明 Spike 可能从 vsatp 的其他位提取了根地址？

等等，让我重新计算 vsatp 的 PPN：

vsatp = 0x8000100000080000
- 二进制：1000 0000 0000 0000 0001 0000 0000 0000 0000 0000 0000 0000 1000 0000 0000 0000
- bits 63:60 = 1000 = 8 (Sv39) ✓
- bits 59:44 = 0000 0000 0000 0001 = 1 (ASID) ✓
- bits 43:0 = 0000 0000 0000 0000 0001 0000 0000 0000 0000 0000 1000 0000 = 0x100000080000

等等，这个计算不对。让我用 Python 计算：

```python
vsatp = 0x8000100000080000
mode = (vsatp >> 60) & 0xF  # 8
asid = (vsatp >> 44) & 0xFFFF  # 1
ppn = vsatp & 0xFFFFFFFFFFF  # 44 bits
print(f"PPN = 0x{ppn:X}")  # 0x100000080000?
```

实际上 PPN 是 44 bits，所以：
PPN = 0x8000100000080000 & 0xFFFFFFFFFFF = 0x100000080000

这不对，PPN 应该是 0x80001。

让我重新检查 vsatp 的值：

vsatp = 0x8000100000080000

用 Python 分解：
```python
vsatp = 0x8000100000080000
mode = (vsatp >> 60) & 0xF
asid = (vsatp >> 44) & 0xFFFF
ppn = vsatp & ((1 << 44) - 1)
print(f"mode={mode}, asid={asid}, ppn=0x{ppn:X}")
```

输出应该是：
mode=8, asid=1, ppn=0x100000080000

这不对！PPN 应该是 0x80001，但实际是 0x100000080000。

这说明 PTG 的 vsatp 计算有问题！

让我检查 PTG 的代码：

```cpp
ctx->set_vsatp((static_cast<uint64_t>(mode) << 60) | (asid << 44) | (root_gpa >> 12));
```

如果 root_gpa = 0x80000000，那么：
root_gpa >> 12 = 0x80000

所以 vsatp 应该是：
(8 << 60) | (1 << 44) | 0x80000 = 0x8000000000000000 | 0x100000000000 | 0x80000

等等，这个计算也不对。让我用 Python 计算：

```python
mode = 8
asid = 1
root_gpa = 0x80000000
vsatp = (mode << 60) | (asid << 44) | (root_gpa >> 12)
print(f"vsatp = 0x{vsatp:016X}")
```

输出：vsatp = 0x8000100000080000

这是正确的！PPN = 0x80000，对应 GPA 0x80000000。

但为什么我之前计算 PPN = 0x100000080000？因为我用了错误的掩码。

正确的计算：
```python
vsatp = 0x8000100000080000
ppn = vsatp & ((1 << 44) - 1)  # 44 bits
print(f"PPN = 0x{ppn:X}")  # 0x80000
```

PPN = 0x80000 → GPA = 0x80000000 ✓

所以 vsatp 是正确的！问题在别处。

让我重新检查 Spike 的日志：

```
[WALK] addr=0x80200000 type=0 mode=0 virt=1 satp=0x8000100000080000 levels=3 ptbase=0x80000000
```

ptbase=0x80000000，这是从 PPN=0x80000 计算得到的（0x80000 << 12 = 0x80000000）。✓

所以 Spike 的 ptbase 是正确的！

那为什么 Spike 访问的地址是 0x90000010？

让我重新分析日志：

```
[S2XLATE] gva=0x80200000 gpa=0x80000010 type=0 hgatp=0x8000100000090000 levels=3 ptbase=0x90000000 vs_pt=1
[PTE_LOAD] paddr=0x90000010 pte=0x24001401 (from sparse)
```

这是 G-stage 转译！Spike 在转译 VS-stage 页表地址（GPA 0x80000000）时，使用 G-stage 页表。

G-stage 页表根在 PA 0x90000000（从 hgatp PPN=0x90000 计算）。

Spike 访问 paddr=0x90000010，这是 G-stage 页表的根节点 + 0x10（entry 2）。

pte=0x24001401：
- V=1, R=0, W=0, X=0 → 这是 table PTE
- U=0, A=0, D=0
- PPN = 0x90005 → PA = 0x90005000

所以 Spike 继续访问 PA 0x90005000：

```
[PTE_LOAD] paddr=0x90005000 pte=0x24001801 (from sparse)
```

pte=0x24001801：
- V=1, R=0, W=0, X=0 → table PTE
- PPN = 0x90006 → PA = 0x90006000

继续：

```
[PTE_LOAD] paddr=0x90006000 pte=0x240010f7 (from sparse)
```

pte=0x240010f7：
- V=1, R=1, W=1, X=1, U=1, A=1, D=1 → leaf PTE
- PPN = 0x90004 → PA = 0x90004000

所以 G-stage 转译成功：GPA 0x80000010 → PA 0x90004010 ✓

但接下来：

```
[PTE_LOAD] paddr=0x90004010 pte=0x0 (from DRAM/MMIO)
[WALK] level=2 idx=2 pte_paddr=0x90004010 pte=0x0 ppn=0x0 s_mode=0 sum=1 mxr=1
[WALK] FAULT: U bit check (U=0 s_mode=0 type=0 sum=1)
```

Spike 访问 PA 0x90004010，但这里没有数据（PTE=0）！

这是 VS-stage 页表的地址。VS-stage 页表根在 GPA 0x80000000，经过 G-stage 转译后应该映射到 PA 0x90004000（从上面的 leaf PTE）。

但 VS-stage 页表实际写入的地址是 0x80000000（从 FORCE 日志看）：

```
[WRITE_SIM_MEM] addr=0x80000000 len=4096 bytes=...
```

这是 GPA 地址，不是 PA 地址！

问题在于：FORCE 的 `writePhysicalMemory` 写入的是 PA 地址，但 PTG 的 `load_to_force` 可能写入了错误的地址。

让我检查 PTG 的 `load_to_force` 实现。
