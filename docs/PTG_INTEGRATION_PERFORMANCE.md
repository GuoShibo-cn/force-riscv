# PTG 集成路径性能分析

## 1. 现状

### 集成架构
```
FORCE test template (Python)
  → PtgBackend.generate_random()          # kwargs→struct→ctypes
    → PtgHandle.random_generate()          # ctypes call
      → libptg: ptg_random_generate()      # C++ tree generation (83%)
  → PtgBackend.load_to_force()
    → PtgHandle.load_to_force()            # ctypes callback registration
      → libptg: ptg_dump_binary_write()    # C++ serialize + per-block cb (17%)
        → Python _write_callback()         # string_at + writePhysicalMemory
          → GenThread.writePhysicalMemory() # pybind11 bridge
            → SimAPI::WritePhysicalMemory()  # ISS memory write
```

### 测量数据 (N=1000 Sv39 4KB 映射)

| 组件 | 时间 | 占比 |
|------|------|------|
| random_generate (C++) | 4.57 ms | 83.4% |
| dump_binary_write | 0.91 ms | 16.6% |
| Python struct fill + lookups | <0.001 ms | <0.1% |
| ctypes 纯调用 | 0.00024 ms | <0.1% |
| **总计** | **~5.48 ms** | **100%** |

### 分 N 扩展规律

| N | gen (ms) | dump (ms) | blocks | per_block (us) |
|---|----------|-----------|--------|----------------|
| 10 | 0.024 | 0.077 | 11 | 7.0 |
| 100 | 0.166 | 0.477 | 68 | 7.0 |
| 500 | 1.451 | 0.901 | 129 | 7.0 |
| 1000 | 4.572 | 0.913 | 130 | 7.0 |

**关键发现：** `random_generate` 时间随 N 超线性增长；`dump_binary_write` 在 N≥500 后稳定在 ~0.9ms（block 数收敛 ~130）；每个 block 回调开销恒定 ~7.0 us（C++ 迭代 + ctypes 编组）；Python 端纯开销 < 0.1%。

## 2. 热点分析

**83.4% — PTG 核心建树 (random_generate).** C++ 计算密集（地址随机化、节点分配、权限设置），非集成路径问题。

**16.6% — dump_binary_write block 回调.** 130 个 block 通过 ctypes 回调逐个传回 Python。路径：`C++ serialize_write → fn(pa,data,size,userdata) → ctypes marshall → _write_callback → string_at → writePhysicalMemory → pybind11 → SimAPI`。核心瓶颈在 block 数量过多，非单次回调开销。

**<0.1% — Python struct 填充.** 34 个 PtgRandomConfig 字段通过 dict kwargs 赋值，耗时 0.7 us。可忽略。

**<0.1% — ctypes 调用编组.** 无参数调用 0.24 us，带 struct 指针 ~0.5 us。可忽略。

## 3. 优化方案

### 3.1 方案 A: 合并 PTG 输出 block（C++ 侧）★★★

**问题：** `ptg_dump_binary_write` 将页表拆成 130 个离散 block，每个 block 触发一次回调。

**方案：** 在 `BinaryOutput::serialize_write` 中合并相邻 block（`pa + size == next_pa`），使 block 数从 130 降至 ~4-5。

```cpp
void serialize_write(const PageTree& tree, WriteFn fn) {
    auto blocks = collect_blocks(tree);
    std::sort(blocks.begin(), blocks.end(),
              [](auto& a, auto& b) { return a.pa < b.pa; });
    Block merged = blocks[0];
    for (size_t i = 1; i < blocks.size(); i++) {
        if (merged.pa + merged.size == blocks[i].pa) {
            merged.size += blocks[i].size;
            merged.data = (uint8_t*)realloc(merged.data, merged.size);
            memcpy(merged.data + merged.size - blocks[i].size,
                   blocks[i].data, blocks[i].size);
        } else { fn(merged.pa, merged.data, merged.size, nullptr); merged = blocks[i]; }
    }
    fn(merged.pa, merged.data, merged.size, nullptr);
}
```

**预期效果：** dump 0.91ms → ~0.04ms (26x)；PTG 整体 ~16% 加速。工作量：中。

### 3.2 方案 B: 改用 ptg_dump_binary_blocks + 批量写入（Python 侧）★★☆

**问题：** 130 次 ctypes 回调跨边界，每次需 `string_at` + `writePhysicalMemory`。

**方案：** 改用 `ptg_dump_binary_blocks` 一次性获取所有 block，合并后批量写入。

```python
def load_to_force_fast(self, ctx_id, stage, gen_thread, mem_bank=0):
    stage_code = STAGE_MAP.get(stage, stage) if isinstance(stage, str) else stage
    blocks_ptr = self._lib.ptg_dump_binary_blocks(self._handle, ctx_id, stage_code)
    if not blocks_ptr: return
    blocks = blocks_ptr.contents
    pa, data = blocks.blocks[0].pa, bytearray()
    for i in range(blocks.num_blocks):
        b = blocks.blocks[i]
        if pa + len(data) == b.pa and len(data) < 1024*1024:
            data.extend(ctypes.string_at(b.data, b.size))
        else:
            gen_thread.writePhysicalMemory(pa, bytes(data), mem_bank)
            pa, data = b.pa, bytearray(ctypes.string_at(b.data, b.size))
    if data:
        gen_thread.writePhysicalMemory(pa, bytes(data), mem_bank)
    self._lib.ptg_free_blocks(blocks_ptr)
```

**预期效果：** 节省 ~67 us（回调 31 us + string_at 36 us）；dump path ~8% 加速。工作量：低。

### 3.3 方案 C: 消除 string_at 中间拷贝 ★★☆

**问题：** `string_at(data_ptr, size)` 创建 Python bytes → `writePhysicalMemory` 再转回 `std::string`，冗余拷贝 2x。

**方案：** 在 `PyVirtualMemory.h` 新增 `writePhysicalMemoryDirect`，直接接受裸指针。

```cpp
// PyVirtualMemory.h
.def("writePhysicalMemoryDirect",
    [](uint32_t mem_bank, uint64_t address, uintptr_t data_ptr, size_t size) {
      auto* gen = Scheduler::Instance()->LookUpGenerator(ThreadContext().GetThreadId());
      gen->GetSimAPI()->WritePhysicalMemory(mem_bank, address, size,
          reinterpret_cast<const unsigned char*>(data_ptr));
    })
```

```python
# PtgBackend.py
@WRITE_FN_TYPE
def _write_callback(pa, data_ptr, size, userdata):
    VirtualMemory.writePhysicalMemoryDirect(mem_bank, pa,
        ctypes.cast(data_ptr, ctypes.c_void_p).value, size)
```

**预期效果：** 节省 ~38 us (130×0.29us)；dump path ~4% 加速。工作量：低-中。

### 3.4 方案 D: C++ 侧直接桥接 ★★☆

**问题：** load_to_force 全路径经 Python 中转。

**方案：** 创建 pybind11 函数接收 PTG handle + ctx_id + stage，C++ 回调中直接写 SimAPI。

**预期效果：** dump path ~12% 加速。工作量：高（不推荐，收益/成本比低）。

## 4. 实施建议

| 优先级 | 方案 | PTG 整体加速 | 工作量 | 推荐 |
|--------|------|-------------|--------|------|
| 1 | **A: Block 合并 (C++)** | ~16% | 中 | ✅ 优先实施 |
| 2 | **C: 消除 string_at 拷贝** | ~0.7% | 低-中 | ✅ 快速 win |
| 3 | **B: 改用 blocks API** | ~1.3% | 低 | ⏸ 备选 |
| 4 | **D: C++ 直接桥接** | ~2% | 高 | ⏸ 不推荐 |

**路线图：** Phase 1 实施方案 C（低风险）；Phase 2 实施方案 A（高回报）；Phase 3 可选 B。

## 5. 结论

当前 PTG Python 集成路径（ctypes wrapper + callback bridge）**已经非常高效**。Python 层开销 < 0.1%。主要集成开销来自 `ptg_dump_binary_write` 的 130 个离散 block（16.6%）。**核心优化方向不在 Python 侧，在减少 PTG 输出 block 数量** — 将 block 从 130 合并到 ~5 可使 dump 阶段加速 ~26x，PTG 整体加速 ~16%。
