# Phase 1 - FORCE Python 集成层 · 实施方案

**日期**：2026-06-19
**状态**：待 review，未开始实施
**依据**：PTG_INTEGRATION_FEASIBILITY.md v1.5 + PTG 维护者所有 Issue 已修复
**预计周期**：5 个工作日

---

## 0. 上下文

PTG（page_table_generator）经 v1.4 验证全部 3105 项测试通过，Phase 0 无阻塞项。
本阶段目标：**让 FORCE Python 侧能用 PTG 作为页表后端生成 Sv39/Sv48/Sv57 等分页模式**。

不包含：两阶翻译（Phase 2）、多核（Phase 3）、替换 FORCE 内部 VmPagingMapper（Phase 4）。

---

## 1. Phase 1.1 — EPagingMode 枚举扩展（0.5 天）

### 1.1 目标

让 FORCE 支持 `Sv57` 和 `Sv57x4` 分页模式，与 PTG 的能力对齐（PTG 在 v1.4 已支持全部 8 种模式）。

### 1.2 现状（grep 结果）

```
riscv/inc/EnumsRISCV.h:161-168          enum class EPagingMode  (当前 6 个值)
riscv/inc/py_modules/PyEnumsRISCV.h:32-37  Python 绑定（只有 4 个值！）
riscv/src/EnumsRISCV.cc:637             unsigned char EPagingModeSize = 6;
riscv/src/EnumsRISCV.cc:642-647         EPagingMode_to_string 实现
riscv/src/InitialSetupRISCV.cc:148,151,154   switch case
riscv/src/VmasControlBlockRISCV.cc       10+ switch case（多处）
riscv/src/RegisterInitPolicyRISCV.cc:62,65,68  switch case
riscv/src/VmasControlBlockVS.cc:113      switch case
```

**注意**：Python 绑定缺 `Sv39x4` 和 `Sv48x4`，说明当前 Python 层只支持 S-stage 模式，不支持 G-stage 扩展模式 — 这是 Phase 2 的内容。Phase 1 仅扩展 `Sv57` / `Sv57x4` 的 C++ 侧枚举值，Python 绑定保持现状（Phase 2 时再扩展 G-stage 模式）。

### 1.3 改动清单

#### 文件 1：`riscv/inc/EnumsRISCV.h` (line 161-168)

```cpp
// 改动前
enum class EPagingMode : unsigned char {
    Bare = 0,
    Sv32 = 1,
    Sv39 = 2,
    Sv48 = 3,
    Sv39x4 = 4,
    Sv48x4 = 5,
};

// 改动后
enum class EPagingMode : unsigned char {
    Bare   = 0,
    Sv32   = 1,
    Sv39   = 2,
    Sv48   = 3,
    Sv57   = 4,    // 新增（注意：编号与 Sv39x4 冲突，需要调整）
    Sv39x4 = 8,    // 重编号：高 3 bit 表示 x4 扩展
    Sv48x4 = 9,
    Sv57x4 = 10,
};
```

**编号策略选择**：

| 方案 | 优点 | 缺点 |
|------|------|------|
| A: 连续编号 (0-7) | 紧凑 | Sv57=4 与 Sv39x4 冲突 |
| B: 高位标志位 (bit3=x4) | Sv39=2, Sv48=3, Sv57=4, Sv39x4=10, Sv48x4=11, Sv57x4=12 | 稀疏 |
| C: 保留现有编号仅追加 Sv57=6 Sv57x4=7 | 不影响现有序列化 | G-stage 扩展命名无系统规律 |

**建议方案 C**（最安全，向后兼容）：

```cpp
enum class EPagingMode : unsigned char {
    Bare   = 0,
    Sv32   = 1,
    Sv39   = 2,
    Sv48   = 3,
    Sv39x4 = 4,
    Sv48x4 = 5,
    Sv57   = 6,    // 新增
    Sv57x4 = 7,    // 新增
};
```

#### 文件 2：`riscv/src/EnumsRISCV.cc:637`

```cpp
// 改动前
unsigned char EPagingModeSize = 6;

// 改动后
unsigned char EPagingModeSize = 8;
```

#### 文件 3：`riscv/src/EnumsRISCV.cc:639-660` (EPagingMode_to_string)

在 switch 中添加：
```cpp
case EPagingMode::Sv57:   return "Sv57";
case EPagingMode::Sv57x4: return "Sv57x4";
```

并在 `string_to_EPagingMode` 函数（同文件后续）添加反向映射。

#### 文件 4：`riscv/src/VmasControlBlockRISCV.cc`（约 10 处 switch case）

每处添加：

```cpp
case EPagingMode::Sv57:   /* 与 Sv48 逻辑类似，但 57-bit 地址空间 */
    // ...
case EPagingMode::Sv57x4: /* 与 Sv48x4 类似 */
    // ...
```

**注意**：`VmasControlBlockRISCV.cc:293` 已知有 bug —— `HighestVaBitCurrent` 返回 38 应为 40（Sv39x4 G-stage），Phase 1 修复同时可顺带验证。

#### 文件 5：`riscv/src/InitialSetupRISCV.cc:148,151,154`

```cpp
case EPagingMode::Sv57:
    // satp MODE=10, 57-bit VA space
    break;
case EPagingMode::Sv57x4:
    // hgatp MODE=10, 57-bit * 4 byte address
    break;
```

#### 文件 6：`riscv/src/RegisterInitPolicyRISCV.cc:62,65,68`

类似添加 case。

#### 文件 7：`riscv/src/VmasControlBlockVS.cc:113`

类似添加 case。

### 1.4 测试方法

```bash
cd /home/guoshibo/force-riscv
make -j           # 编译
make tests        # 编译 C++ 测试
./utils/regression/unit_tests.py   # 跑 C++ 单元测试
```

### 1.5 验收标准

- [ ] `make -j` 编译无错误、无新 warning
- [ ] `make tests` 编译通过
- [ ] C++ 单元测试通过（与当前 baseline 一致）
- [ ] Python ctypes 能访问 `EPagingMode.Sv57` / `EPagingMode.Sv57x4`（验证 PyEnumsRISCV）
- [ ] `EPagingMode_to_string(Sv57)` == "Sv57"
- [ ] `string_to_EPagingMode("Sv57x4")` == EPagingMode::Sv57x4

### 1.6 风险

- **向后兼容风险**：如果 FORCE 配置/序列化文件中持久化了 EPagingMode 编号（非字符串），改编号会破坏旧数据。
  - 缓解：检查 `arch_data/` 目录是否有持久化枚举值的文件（XML 中一般用字符串，风险低）。
- **遗漏 case**：grep 可能漏掉通过 int 强转使用的地方。
  - 缓解：开启 `-Wswitch-enum` 编译，强制所有 switch 处理新枚举值。

---

## 2. Phase 1.2 — WritePhysicalMemory Python API（0.5 天）

### 2.1 目标

让 FORCE 的 `GenThread` (Python 层) 能将二进制数据直接写入物理地址，用于 PTG 生成的页表镜像。

### 2.2 现状

- C++ 层 `SimAPI::WritePhysicalMemory` **已存在**：
  ```cpp
  // base/inc/SimAPI.h:165
  virtual void WritePhysicalMemory(uint32 memBank, uint64 address, uint32 size,
                                    const unsigned char *pBytes) = 0;
  ```
- C++ 内部已在用（`ResourcePeState.cc:226,245` / `GenInstructionAgent.cc:286`）
- Python 层 **不存在**封装

### 2.3 改动清单

#### 文件 1：`base/src/PyInterface.cc`（或 `py/base/PyInterface.cc`，需确认位置）

需要找到 FORCE 的 pybind11 接口入口，添加新方法。先 grep 确认路径：

```bash
find /home/guoshibo/force-riscv -name "PyInterface.cc" 2>/dev/null
# 备选名字：PyGenThread.cc / GenBinding.cc
```

添加封装：

```cpp
// 在 GenThread pybind11 类中添加
.def("writePhysicalMemory", [](GenThread& self, uint64 memBank, uint64 address, py::bytes data) {
    std::string s = data;
    self.GetSimAPI().WritePhysicalMemory(
        memBank, address, static_cast<uint32>(s.size()),
        reinterpret_cast<const unsigned char*>(s.data()));
}, "Write raw bytes to physical memory (for PTG integration)")
```

#### 文件 2：`py/base/GenThread.py`（如果 Python 侧需要便利包装）

```python
def writePhysicalMemory(self, address, data_bytes, bank=0):
    """
    Write raw bytes directly to simulation physical memory.

    Args:
        address: uint64 physical address
        data_bytes: bytes object (e.g., PTG dump_binary output)
        bank: memory bank index (default: 0 == Default)
    """
    self.interface.writePhysicalMemory(bank, address, data_bytes)
```

### 2.4 测试方法

```python
# 单元测试
import GenThread
thread = GenThread.get_current()
thread.writePhysicalMemory(0x80000000, b"\x01\x02\x03\x04")
# 验证：通过 GenInstruction 读取该地址应返回相同字节
```

### 2.5 验收标准

- [ ] Python 层能调用 `GenThread.writePhysicalMemory(addr, bytes)`
- [ ] Spike 后续通过物理地址 walk 能读到这些字节
- [ ] 大数据测试（4KB page，32KB 页表）无崩溃
- [ ] 错误处理：无效地址 / 越界写入返回错误而非崩溃

### 2.6 风险

- **PyInterface 封装层未知**：需要先 grep 确认 FORCE 的 pybind11 绑定入口在哪。
  - 缓解：第一步先 `find` + `grep 'def_readonly\|PYBIND11_MODULE'` 定位。
- **内存 bank 约定**：FORCE 多内存银行模型下默认用 `EMemBankType::Default` (0)，但 PTG 输出是 SPA 线性空间，需要确认映射关系。
  - 缓解：Phase 1 仅支持 bank=0，Phase 2 扩展。

---

## 3. Phase 1.3 — PtgBackend Python 模块（2 天）

### 3.1 目标

为 FORCE 提供一个面向页表生成的 Python 类 `PtgBackend`，封装 PTG 的 ctypes 调用。

### 3.2 模块结构

```
py/riscv/paging/
├── __init__.py           (导出 PtgBackend)
├── PtgBackend.py          (核心封装，约 300 行)
└── tests/
    └── test_ptg_backend.py (单元测试)
```

### 3.3 文件 1：`py/riscv/paging/` 目录

新建。

### 3.4 文件 2：`py/riscv/paging/PtgBackend.py`

骨架设计（具体行数约 300 行）：

```python
"""PTG-based page table backend for FORCE-RISCV"""
import ctypes
import struct
from pathlib import Path


class PtgBackend:
    """
    Wraps libptg.so to provide page-table generation services
    to FORCE Python test templates.

    Usage:
        backend = PtgBackend()
        backend.set_paging_mode("Sv39")
        backend.set_physical_range(0x8000_0000, 0x9000_0000)
        ctx = backend.create_context(asid=1, vmid=0)
        backend.random_generate(ctx, min_mappings=50, max_mappings=100,
                                 per_leaf_only=1, target_count=0,
                                 fault_probability=0.0)
        satp = backend.load_to_force(ctx, gen_thread)
    """

    # --- 构造函数 / 生命周期 ---
    def __init__(self, lib_path=None):
        """加载 libptg.so，集中声明所有 argtypes 防 ctypes ABI 错误"""
        if lib_path is None:
            lib_path = Path("/home/guoshibo/page_table_generator/build/libptg.so")
        self.ptg = ctypes.CDLL(str(lib_path))
        self._setup_signatures()
        self.handle = self.ptg.ptg_create()

    def _setup_signatures(self):
        """集中声明 70+ 个函数的 argtypes + restype，防止 ctypes ABI 错误"""
        # 生命周期
        self.ptg.ptg_create.restype = ctypes.c_void_p
        self.ptg.ptg_destroy.argtypes = [ctypes.c_void_p]
        # ... 其余 70+ 函数签名

    def __del__(self):
        """自动销毁句柄（Python GC 时）"""
        if hasattr(self, "handle") and self.handle:
            self.ptg.ptg_destroy(self.handle)
            self.handle = None

    # --- 配置 API ---
    def set_paging_mode(self, mode: str):
        """mode ∈ {"Sv39", "Sv48", "Sv57"}"""
        # 映射字符串到 PTG 内部 int
        pass

    def set_physical_range(self, base: int, limit: int):
        """注册 SPA 区间供 PTG 分配"""
        pass

    # --- Context 管理 ---
    def create_context(self, asid: int = 0, vmid: int = 0):
        """创建新的 page context，返回 ctx_id"""
        pass

    # --- 生成 ---
    def random_generate(self, ctx, min_mappings, max_mappings,
                        per_leaf_only=0, target_count=0,
                        fault_probability=0.0, seed=0):
        """调用 ptg_random_generate，返回 PtgFaultStats"""
        pass

    # --- 加载到 FORCE ---
    def load_to_force(self, ctx, gen_thread):
        """
        用 ptg_dump_binary_write 回调，直接把页表字节写入 FORCE 物理内存，
        然后返回 satp/vsatp/hgatp 值供 initializeRegister 使用。
        """
        # 1. 注册回调把 bytes 写入 gen_thread
        # 2. 调用 ptg_dump_binary_write
        # 3. 返回 {"satp": X, "vsatp": Y, "hgatp": Z}
        pass

    # --- 注入 ---
    def inject_fault(self, ctx, fault_cause=1, target_count=0,
                     probability=0.0, per_leaf_only=0,
                     target_va=0, dry_run=0):
        """返回 (count, stats) """
        pass
```

### 3.5 文件 3：`py/riscv/paging/__init__.py`

```python
from .PtgBackend import PtgBackend

__all__ = ["PtgBackend"]
```

### 3.6 文件 4：`py/riscv/paging/tests/test_ptg_backend.py`

最小可运行测试（约 100 行）：

```python
import unittest
from riscv.paging import PtgBackend


class TestPtgBackend(unittest.TestCase):
    def test_create(self):
        b = PtgBackend()
        self.assertIsNotNone(b.handle)

    def test_s_stage_random(self):
        b = PtgBackend()
        b.set_paging_mode("Sv39")
        b.set_physical_range(0x80000000, 0x90000000)
        ctx = b.create_context(asid=1)
        stats = b.random_generate(ctx, min_mappings=50, max_mappings=100,
                                   per_leaf_only=1)
        self.assertGreater(stats.injected, 0)

    def test_inject_fault_dry_run(self):
        """dry_run=1 不应修改页表"""
        b = PtgBackend()
        b.set_paging_mode("Sv39")
        b.set_physical_range(0x80000000, 0x90000000)
        ctx = b.create_context()
        b.random_generate(ctx, min_mappings=50, max_mappings=100)
        c1, _ = b.inject_fault(ctx, target_count=10, dry_run=1)
        self.assertEqual(c1, 10)
        # 再 dry_run 应该还是 10（证明未被真正注入）
        c2, _ = b.inject_fault(ctx, target_count=10, dry_run=1)
        self.assertEqual(c2, 10)
```

### 3.7 测试方法

```bash
cd /home/guoshibo/force-riscv
source setenv.bash
PYTHONPATH=$PYTHONPATH:py/riscv/paging python3 -m unittest py.riscv.paging.tests.test_ptg_backend
```

### 3.8 验收标准

- [ ] `PtgBackend()` 能实例化 libptg.so
- [ ] `random_generate` 工作（返回正确的 stats）
- [ ] `inject_fault(dry_run=1)` 不修改页表（二次调用结果相同）
- [ ] `load_to_force` 能把数据写入 FORCE 内存（依赖 Phase 1.2）
- [ ] 所有 ctypes ABI 签名集中声明（无 core dump）

### 3.9 风险

- **libptg.so 路径硬编码**：Phase 1 先用绝对路径，Phase 2 改环境变量。
- **回调函数签名**：`ptg_dump_binary_write` 的 C 函数指针回调需要在 Python 层用 `ctypes.CFUNCTYPE` 声明。
  - 缓解：先写最小原型，跑通再扩展到通用类。
- **错误处理**：CTypes 调用出错时只返回 0，需要把 `ptg_get_last_error` 也封装起来。

---

## 4. Phase 1.4 — setupPagingMode 集成 + 端到端测试（2 天）

### 4.1 目标

让 FORCE 现有的分页模式设置路径可以走 PTG 后端，并跑一个"单阶 Sv39 + spike walk"端到端验证。

### 4.2 现状（需要先 grep 验证）

Python 层分页设置路径目前未知，可能需要先 grep：

```bash
grep -rn "setupPagingMode\|mPagingMode\|paging_mode\|EPagingMode" py/riscv
```

### 4.3 改动清单

**Step 4.1：调研**（0.5 天）

1. 找 `setupPagingMode` 或等价函数
2. 找 FORCE 的 `PageGenChoicesAdapter` / `ChoicesModifier` 如何驱动分页生成
3. 找 Spike walk 触发点（是否自动？是否需要 `setOption` MMU=1）

**Step 4.2：扩展 EnvRISCV.setupPagingMode**（0.5 天）

在现有函数中添加分支：

```python
def setupPagingMode(self, mode: EPagingMode, backend: str = "default"):
    if backend == "ptg":
        from riscv.paging import PtgBackend
        self.ptg_backend = PtgBackend()
        self.ptg_backend.set_paging_mode(mode)
        self.ptg_backend.set_physical_range(...)
    else:
        # 默认 FORCE 内部路径
        ...
```

**Step 4.3：端到端 PoC**（0.5 天）

新建测试脚本 `examples/riscv/ptg_basic_force.py`：

```python
"""FORCE PTG 集成端对端 PoC：单阶 Sv39 + Spike walk"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence


class MainSequence(Sequence):
    def generate(self, **kargs):
        # 1. 用 PTG 生成 Sv39 页表
        from riscv.paging import PtgBackend
        ptg = PtgBackend()
        ptg.set_paging_mode("Sv39")
        ptg.set_physical_range(0x80000000, 0x90000000)
        ctx = ptg.create_context(asid=1)
        ptg.random_generate(ctx, min_mappings=50, max_mappings=100,
                            per_leaf_only=1)
        satp = ptg.load_to_force(ctx, self.genThread)

        # 2. 写入 satp 寄存器
        self.genThread.initializeRegister("satp", "", satp)

        # 3. 生成一条使用虚拟地址的指令
        # 让 Spike 走页表翻译路径
        self.genInstruction("LD##RISCV")
        # ...


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
```

运行：

```bash
bin/friscv -t examples/riscv/ptg_basic_force.py --cfg config/riscv_rv64.config
```

**Step 4.4：验证 Spike walk 结果**（0.5 天）

1. 检查 `.S` 文件，确认 LD 指令访问的 VA 被 Spike walk 成功翻译
2. 检查 `sim.log`，确认无 Unexpected Page Fault
3. 对照测试：把 PTG 生成的页表换成 FORCE 内部生成的，对比结果一致性

### 4.4 验收标准

- [ ] FORCE 能通过 `setupPagingMode(... , backend="ptg")` 切换到 PTG 路径
- [ ] `ptg_basic_force.py` 跑通：生成 .ELF + .S 文件
- [ ] Spike 能 walk PTG 生成的 Sv39 页表，翻译出正确的 PA
- [ ] 与 FORCE 内部生成路径对比：翻译结果一致（satp 不同但翻译出的 PA 相同）

### 4.5 风险

- **Spike walk 可能失败**：
  - 原因 A：Spike 默认 MMU=0，需 `setOption "MMU" "1"`
  - 原因 B：Spike PTE Cache 命中旧值（需 SFENCE 刷新）
  - 原因 C：Spike 物理地址空间未覆盖 PTG 分配的 SPA
  - 缓解：先用 `--log-level=debug` 跑，看具体错误路径。
- **Python 层分页配置点未知**：
  - 缓解：Step 4.1 先调研清楚，如果根本不存在 `setupPagingMode` 这种接口，可能需要新建入口。

---

## 5. 实施顺序 + 依赖

```
Day 1:
  ├─ Phase 1.1 枚举扩展（C++ 编译 + 单元测试）
  │         ↓
  │      make -j 通过
  │
  └─ Phase 1.2 WritePhysicalMemory Python API
           ↓
        Python 单元测试通过

Day 2:
  └─ Phase 1.3 PtgBackend 模块（不依赖 Phase 1.1，只依赖 PTG 和 ctypes）
           ↓
        PtgBackend 单元测试通过（离线，不调 FORCE）

Day 3:
  └─ Phase 1.4 Step 4.1 调研 + Step 4.2 扩展 EnvRISCV

Day 4:
  └─ Phase 1.4 Step 4.3 端到端 PoC 脚本 + 调试

Day 5:
  └─ Phase 1.4 Step 4.4 验证 Spike walk + Phase 1 收尾
```

**独立路径**：Phase 1.1 和 1.2 可并行，Phase 1.3 独立进行。

---

## 6. 依赖

| 项 | 来源 | 备注 |
|----|------|------|
| PTG `libptg.so` | `/home/guoshibo/page_table_generator/build/` | 已 build，v1.5 验证通过 |
| FORCE 主工程 | `/home/guoshibo/force-riscv/` | 已 build，`bin/friscv` 存在 |
| Spike 二进制 | `/home/guoshibo/force-riscv/handcar/` 或预编译 | 待确认 |
| Python ≥ 3.6.1 | env | 已有 |

---

## 7. 风险总结

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| EPagingMode 编号改坏 | 中 | 中 | 方案 C（追加编号），不破坏旧数据 |
| Spike walk 失败 | 高 | 高 | 先调研 MMU 配置，分阶段调试 |
| ctypes ABI 错误 | 中 | 高 | `_setup_signatures` 集中声明（已在 PTG PoC 教训中） |
| Python 层分页入口未找到 | 中 | 中 | Step 4.1 先调研，必要时新建入口 |
| Phase 1.2 影响其他内存路径 | 低 | 高 | 仅添加新方法，不改现有方法 |

---

## 8. 验收总览

- [ ] **Phase 1.1**：`make -j` 通过，EPagingMode.Sv57 / Sv57x4 在 C++ 和 Python 均可访问
- [ ] **Phase 1.2**：Python 层能调用 `GenThread.writePhysicalMemory`
- [ ] **Phase 1.3**：`PtgBackend` 离线单元测试全部通过
- [ ] **Phase 1.4**：`ptg_basic_force.py` 端到端跑通，Spike walk 正确翻译

**Phase 1 完成标志**：4 个子任务验收全部打 ✅，且 FORCE 回归测试套件无新失败。

---

## 附录 A：参考文档

- `PTG_INTEGRATION_FEASIBILITY.md` v1.5（PTG Issue 全集）
- `/home/guoshibo/page_table_generator/docs/ISSUES_FORCE_INTEGRATION.md`（P9-P13 详细报告）
- `/home/guoshibo/force-riscv/doc/USER_MANUAL.md`（FORCE 用户手册）

## 附录 B：预估文件改动量

| 子任务 | 修改文件数 | 新增文件数 | 预估行数 |
|--------|-----------|-----------|---------|
| Phase 1.1 | 5 | 0 | ~30 行改动 |
| Phase 1.2 | 2 | 0 | ~20 行改动 |
| Phase 1.3 | 0 | 4 | ~500 行新增 |
| Phase 1.4 | 1 | 1 | ~100 行新增 |
| **总计** | **8** | **5** | **~650 行** |

---

**文档版本**：v1.0
**状态**：待 review
**作者**：Sisyphus
