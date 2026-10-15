# PTG Bug Report: load_to_force 写入 VS-stage 页表时使用错误的地址类型

## 问题描述

PTG 的 `load_to_force` 在写入 VS-stage 页表时，直接将 GPA 地址传给 `writePhysicalMemory`，但 FORCE 的 `writePhysicalMemory` 期望的是 PA 地址。

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

# 加载 VS-stage 页表
ptg.load_to_force(ctx, "VS", genThread)
# 加载 G-stage 页表
ptg.load_to_force(ctx, "G", genThread)
```

## 预期行为

`load_to_force(ctx, "VS", ...)` 应该：
1. 获取 VS-stage 页表节点的 GPA 地址
2. 通过 G-stage 转译将 GPA 转换为 PA
3. 调用 `writePhysicalMemory(PA, data)`

## 实际行为

`load_to_force(ctx, "VS", ...)` 直接：
1. 获取 VS-stage 页表节点的 GPA 地址
2. 调用 `writePhysicalMemory(GPA, data)`  ← 错误！应该是 PA

## 证据

FORCE 日志显示：
```
[WRITE_SIM_MEM] addr=0x80000000 len=4096 bytes=...  # GPA，不是 PA
[WRITE_SIM_MEM] addr=0x80001000 len=4096 bytes=...
[WRITE_SIM_MEM] addr=0x80002000 len=4096 bytes=...
```

但 vsatp 指向的根地址是 GPA 0x80000000，经过 G-stage 转译后应该映射到 PA 0x90004000（根据 G-stage PTE）。

Spike 访问 VS-stage 页表时：
```
[S2XLATE] gva=0x80200000 gpa=0x80000010 type=0 hgatp=0x8000100000090000 levels=3 ptbase=0x90000000 vs_pt=1
[PTE_LOAD] paddr=0x90000010 pte=0x24001401 (from sparse)  # G-stage 转译
[S2XLATE] SUCCESS: gpa=0x80000010 -> pa=0x90004010
[PTE_LOAD] paddr=0x90004010 pte=0x0 (from DRAM/MMIO)  # ← 这里没有数据！
```

Spike 期望在 PA 0x90004010 找到 VS-stage 页表数据，但 PTG 把数据写到了 GPA 0x80000000。

## 根因分析

`BinaryOutput::build_image` 使用 `node->base_addr()` 作为写入地址：

```cpp
tree.for_each_node([&](const PageTableNode* node) {
    uint64_t node_pa = node->base_addr();  // ← 对于 VS-stage，这是 GPA！
    // ...
    blocks[node_pa] = std::move(data);
});
```

对于 VS-stage 页表，`node->base_addr()` 返回 GPA（因为 `in_gpa_ = true`），但 `load_to_force` 需要 PA。

## 建议修复

### 方案 A：在 `load_to_force` 中进行地址转译

```python
def load_to_force(self, ctx_id, stage, gen_thread, mem_bank=0):
    stage_code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
    
    # 对于 VS-stage，需要先获取 G-stage 转译信息
    if stage_code == 1:  # VS-stage
        # 获取所有 VS-stage 节点的 GPA
        # 通过 G-stage 转译为 PA
        # 然后写入 PA 地址
        pass
    
    @WRITE_FN_TYPE
    def _write_callback(pa, data_ptr, size, userdata):
        buf = ctypes.string_at(data_ptr, size)
        gen_thread.writePhysicalMemory(pa, buf, mem_bank)
    
    self._lib.ptg_dump_binary_write(
        self._handle, ctx_id, stage_code, _write_callback, None
    )
```

### 方案 B：在 PTG C++ 层提供地址转译 API

```cpp
// 新增 API：获取 VS-stage 节点的 PA 地址
uint64_t ptg_translate_vs_node(void* h, uint32_t ctx_id, uint64_t gpa) {
    // 通过 G-stage 转译 GPA -> PA
}
```

### 方案 C：文档说明，要求用户手动处理

在文档中说明：对于两阶转译，用户需要先调用 `ptg_translate` 获取 VS-stage 节点的 PA，然后手动写入。

## 影响

- 无法使用 PTG 进行两阶转译测试
- VS-stage 页表数据被写入错误的地址

## 环境

- PTG version: master branch
- FORCE-RISCV version: feature/hypervisor-phase3 branch
