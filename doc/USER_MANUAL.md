# FORCE-RISCV 用户手册

> 版本：2.0（基于 v0.8 用户手册和完整源码分析）
>
> 最后更新：2026-06-10

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [环境配置与构建](#3-环境配置与构建)
4. [快速入门](#4-快速入门)
5. [测试模板编写指南](#5-测试模板编写指南)
6. [Python API 参考](#6-python-api-参考)
7. [配置系统](#7-配置系统)
8. [回归测试框架](#8-回归测试框架)
9. [已知问题与限制](#9-已知问题与限制)
10. [附录](#10-附录)

---

## 1. 项目概述

FORCE-RISCV 是一个 RISC-V 指令序列生成器（Instruction Sequence Generator, ISG），用于处理器设计验证。它通过随机化选择指令、寄存器、地址和数据来生成测试用例，能够以极少的用户输入生成有效的测试序列。

### 1.1 核心特性

- **支持的 ISA 扩展**：RV64G (IMAFDCZicsr_Zifencei)、RV32G、V extension 1.0、Zfh（半精度浮点）
- **特权级支持**：完整的 U/S/M 特权级支持，H-extension（Hypervisor）部分支持
- **虚拟内存**：Sv48、Sv39、Sv32 分页模式，支持 4KB/2MB/1GB/512GB 页面
- **C 扩展**：支持压缩指令（RV32C/RV64C）
- **原子操作**：支持 LR/SC 和 AMO 指令系列
- **异常处理**：快速异常处理（Fast handlers）和综合异常处理（Comprehensive handlers），可配置异常委托
- **特权模式切换**：通过 SystemCallSequence 实现完整的 U/S/M 模式切换
- **多核/多线程**：支持多进程/多线程指令生成，线程同步原语
- **模拟器集成**：与 Handcar（基于 Spike 的 ISS）集成，生成后可立即验证
- **后生成执行**：fpix_riscv 后生成执行器，在生成完成后执行指令流
- **两阶地址翻译**：支持 H-extension 的两阶翻译（GVA→GPA→SPA）

### 1.2 输出格式

- `*.ELF`：二进制测试文件，可输入到 RTL 仿真器
- `*.S`：反汇编文本文件，便于调试查看生成的指令流
- `gen.log`：生成过程的详细日志
- `sim.log`：模拟器日志，包含指令流和寄存器/内存读写
- `fpix_sim.log`：后生成执行日志

---

## 2. 系统架构

### 2.1 目录结构

```
force-riscv/
├── base/                    # 架构无关的 C++ 框架层
│   ├── inc/                 # 基类头文件
│   └── src/                 # 基类实现
├── riscv/                   # RISC-V 架构特定实现
│   ├── arch_data/           # XML 架构数据
│   │   ├── instr/           # 指令定义 XML
│   │   ├── reg/             # 寄存器定义 XML
│   │   ├── general/         # 通用配置 XML（choices, variables）
│   │   └── paging/          # 分页定义 XML
│   ├── inc/                 # C++ 头文件
│   └── src/                 # C++ 源码
├── py/                      # Python 框架层
│   ├── base/                # 架构无关的 Python 基类
│   │   ├── Sequence.py      # 核心序列 API（630 行）
│   │   ├── GenThread.py     # 生成线程基类
│   │   ├── ChoicesModifier.py # 权重修改器（104 行）
│   │   ├── SequenceLibrary.py # 序列库（135 行）
│   │   └── Utils.py         # 工具类（LoopControlBase）
│   ├── riscv/               # RISC-V 特定的 Python 实现
│   │   ├── EnvRISCV.py      # RISC-V 环境
│   │   ├── GenThreadRISCV.py # RISC-V 生成线程（171 行）
│   │   ├── AssemblyHelperRISCV.py # RISC-V 汇编辅助（442 行）
│   │   ├── SystemCallSequence.py  # 系统调用序列（263 行）
│   │   ├── Utils.py         # RISC-V 工具（LoadGPR64, LoopControl）
│   │   └── ModifierUtils.py # 修改器工具（PageFaultModifier）
│   └── DV/riscv/            # 领域验证
│       ├── trees/           # 指令树（843 行）
│       └── sequences/       # 可复用序列库
├── handcar/                 # Handcar ISS（Spike 封装 + 补丁）
├── utils/
│   ├── handcar/             # Handcar C++ 封装层
│   ├── regression/          # 回归测试框架
│   │   ├── master_run.py    # 主回归运行器（865 行）
│   │   ├── master_init.py   # 命令行参数定义
│   │   ├── forrest_run.py   # 任务执行器
│   │   └── classes/         # 框架类
│   ├── builder/             # 指令/寄存器/测试构建器
│   └── smoke/               # 烟雾测试
├── fpix/                    # 后生成指令执行器
├── config/                  # XML 架构配置文件
├── tests/riscv/             # 回归测试模板
│   ├── exception_handlers/
│   ├── privilege_switch/
│   ├── multiprocessing/
│   ├── paging/
│   ├── vector/
│   └── state_transition/
├── examples/riscv/          # 示例测试模板
├── unit_tests/              # C++ 单元测试
│   ├── base/
│   ├── riscv/
│   └── fpix/
└── bin/                     # 构建产物
```

### 2.2 核心组件

| 组件 | 说明 |
|------|------|
| `bin/friscv` | 主程序 — RISC-V 指令序列生成器 |
| `bin/SimApiHANDCAR.so` | 模拟器 API 层，由 friscv 在运行时加载 |
| `bin/handcar_cosim.so` | Handcar ISS 核心库（基于 Spike） |
| `fpix/bin/fpix_riscv` | 后生成指令执行器 |
| `py/base/Sequence.py` | 核心 API 类 — 所有测试模板的基类 |
| `py/riscv/GenThreadRISCV.py` | RISC-V 生成线程实现 |
| `py/riscv/AssemblyHelperRISCV.py` | RISC-V 汇编辅助类 — 高级指令生成 |
| `py/riscv/SystemCallSequence.py` | 系统调用序列 — 特权级切换 |
| `py/DV/riscv/trees/instruction_tree.py` | 指令树定义 |
| `py/base/ChoicesModifier.py` | 权重修改器 |
| `py/base/SequenceLibrary.py` | 序列库 |

### 2.3 运行时加载链

```
bin/friscv  --dlopen-->  bin/SimApiHANDCAR.so  --dlopen-->  utils/handcar/handcar_cosim.so
```

### 2.4 生成流程

1. `friscv` 读取 `--cfg` 指定的 XML 配置文件
2. 加载指令定义、寄存器定义、分页定义、choices 权重文件
3. 导入并执行 Python 测试模板（`*_force.py`）
4. 模板中的 `gen_thread_initialization()` 执行初始化配置
5. `MainSequence.generate()` 被调用，生成指令序列
6. 生成过程中，Handcar ISS 模拟器验证每条指令的正确性
7. 生成完成后，输出 `.ELF` 和 `.S` 文件
8. 可选：`fpix_riscv` 后生成执行器运行整个指令流

---

## 3. 环境配置与构建

### 3.1 系统要求

| 组件 | 最低版本 | 说明 |
|------|----------|------|
| g++ | 5.1 | C++ 编译器 |
| Python 3 | 3.6.1 | Python 解释器（需要包含 importlib） |
| Python 开发头文件 | 对应版本 | `Python.h`（用于 pybind11 和 seedgen） |

### 3.2 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FORCE_CC` | `g++` | C++ 编译器路径 |
| `FORCE_PYTHON_VER` | 自动检测 | Python 版本号（如 `3.11`） |
| `FORCE_PYTHON_INC` | `/usr/include/python{VER}` | Python 头文件目录 |
| `FORCE_PYTHON_LIB` | `/usr/lib/x86_64-linux-gnu/` | Python 库目录 |

### 3.3 构建步骤

#### 3.3.1 一键构建（推荐）

```bash
./setup
```

`setup` 脚本执行顺序：
1. 检查 g++ 和 Python 版本
2. 设置环境变量（`source setenv.bash`）
3. 执行 `make -j`（构建核心程序）
4. 执行 `make -j tests`（构建测试基础设施）
5. 运行主回归测试
6. 运行 C++ 单元测试

#### 3.3.2 手动构建

```bash
# 1. 设置环境（必须在运行任何 Python 工具前执行）
source setenv.bash

# 2. 构建核心程序
make -j

# 3. 构建测试基础设施（生成测试模板 + 构建 seedgen）
make tests
```

**重要**：`setenv.bash` 必须用 `source` 执行，不能用 `./setenv.bash`。后者会创建子 shell，退出后环境失效。

`setenv.bash` 添加的 PYTHONPATH：
- `3rd_party/py`（pybind11）
- `utils/`
- `utils/builder/`
- `utils/builder/test_builder/`
- `utils/builder/shared/`
- `utils/regression/`

#### 3.3.3 构建产物

| 产物 | 说明 |
|------|------|
| `bin/friscv` | 主程序 |
| `bin/SimApiHANDCAR.so` | 模拟器 API 层 |
| `bin/handcar_cosim.so` | Handcar ISS（预编译） |
| `fpix/bin/fpix_riscv` | 后生成执行器 |

### 3.4 friscv 命令参考

`bin/friscv` 是 FORCE-RISCV 的主程序：

| 选项 | 说明 |
|------|------|
| `--cfg, -c <path>` | 配置文件路径（必需） |
| `--test, -t <path>` | 指定测试模板文件（必需） |
| `--seed, -s <hex>` | 指定随机种子（如 `0x123`） |
| `--options, -o <string>` | 指定测试选项字符串 |
| `--log, -l <level>` | 指定日志级别（如 `info`） |
| `--dump, -d <option>` | 指定转储选项 |
| `--noasm` | 不输出汇编代码文件 |
| `--img` | 输出内存和寄存器镜像 |
| `--noiss, -n` | 生成时不运行 ISS 模拟 |
| `--max-instr, -m <N>` | 最大模拟指令数 |
| `--num-chips, -P <N>` | 芯片数量 |
| `--num-cores, -C <N>` | 每芯片核心数 |
| `--num-threads, -T <N>` | 每核心线程数 |
| `--outputwithseed, -w` | 在输出文件名中包含种子 |
| `--failOverride, -f` | 操作数覆写无效时报错 |
| `--global-modifier, -g <path>` | 全局修改文件路径 |
| `--help` | 打印帮助信息 |

使用示例：

```bash
# 基本使用
bin/friscv -t my_test_force.py --cfg config/riscv_rv64.config

# 指定种子和选项
bin/friscv -s 0xABCD -t my_test_force.py --cfg config/riscv_rv64.config -o "PrivilegeLevel=1"

# 多核生成
bin/friscv -C 4 -T 1 -t multi_force.py --cfg config/riscv_rv64.config

# 不运行模拟器（仅生成）
bin/friscv -n -t my_test_force.py --cfg config/riscv_rv64.config

# 输出带种子的文件名
bin/friscv -w -t my_test_force.py --cfg config/riscv_rv64.config
```

### 3.5 重建 Handcar（可选）

正常情况下无需重建 Handcar。仅在修改 Handcar 本身时执行：

```bash
cd handcar
./regenerate_and_build.bash
```

### 3.6 生成枚举类

在修改了 `arch_data/` 中的 XML 文件后，需要重新生成枚举类：

```bash
make enums
```

---

## 4. 快速入门

### 4.1 运行烟雾测试

```bash
source setenv.bash
bin/friscv -t utils/smoke/test_force.py --cfg config/riscv_rv64.config
```

输出文件（在当前目录）：
- `test_force.Default.ELF` — 二进制测试
- `test_force.Default.S` — 反汇编文本
- `sim.log` — 模拟器日志

### 4.2 最简单的测试模板

创建 `my_first_force.py`：

```python
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence

class MainSequence(Sequence):
    def generate(self, **kargs):
        self.genInstruction("ADD##RISCV")
        self.genInstruction("SUB##RISCV")

MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
```

运行：

```bash
bin/friscv -t my_first_force.py --cfg config/riscv_rv64.config
```

### 4.3 使用示例模板

```bash
# 运行示例
bin/friscv -t examples/riscv/basic_random_01_force.py --cfg config/riscv_rv64.config

# 运行回归测试
./utils/regression/master_run.py -f examples/riscv/_def_fctrl.py \
    -c utils/regression/config/_riscv_rv64_fcfg.py -k all
```

### 4.4 验证结果

运行后检查：
1. 是否生成了 `.ELF` 和 `.S` 文件
2. `.S` 文件中的指令是否正确
3. `sim.log` 中是否有错误信息

### 4.5 RV32 用法

```bash
# 直接运行
bin/friscv -t my_test_force.py --cfg config/riscv_rv32.config

# 回归运行
./utils/regression/master_run.py -f tests/riscv/_rv32_fctrl.py \
    -c utils/regression/config/_riscv_rv32_fcfg.py -k all
```

---

## 5. 测试模板编写指南

### 5.1 模板结构

每个测试模板是一个 Python 文件，文件名必须以 `_force.py` 结尾。标准结构包含三个必须的模块级变量：

```python
# 1. 导入
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence

# 2. 主序列类
class MainSequence(Sequence):
    def generate(self, **kargs):
        # 测试逻辑
        pass

# 3. 模块级赋值（必须）
MainSequenceClass = MainSequence    # 主序列类
GenThreadClass = GenThreadRISCV      # 生成线程类
EnvClass = EnvRISCV                  # 环境类
```

可选模块级变量：

```python
# 初始化函数（在 MainSequence.generate() 之前执行）
def gen_thread_initialization(gen_thread):
    pass
GenThreadInitialization = gen_thread_initialization
```

### 5.2 指令生成基础

#### 5.2.1 生成单条指令

```python
# 基本格式：MNEMONIC##RISCV
self.genInstruction("ADD##RISCV")

# 带 ISA 变体：MNEMONIC#FORM#RISCV
self.genInstruction("SRLI#RV64I#RISCV")     # RV64 专用
self.genInstruction("SRLI#RV32I#RISCV")     # RV32 专用
self.genInstruction("CSRRW#register#RISCV") # CSR 寄存器形式
```

#### 5.2.2 手动指定操作数

```python
# 指定目标寄存器和源寄存器
self.genInstruction("ADD##RISCV", {"rd": 5, "rs1": 6, "rs2": 7})

# 指定 Load/Store 目标地址
self.genInstruction("LD##RISCV", {"LSTarget": 0x80000000})

# 指定 CSR 寄存器
self.genInstruction("CSRRW#register#RISCV", {"rd": 0, "csr": 0x140})

# 跳过限制检查
self.genInstruction("JAL##RISCV", {"rd": 0, "simm20": 0x100, "NoRestriction": 1})

# 关闭分支预测（Branch-Not-Taken）
self.genInstruction("BNE##RISCV", {"rs1": 5, "rs2": 0, "simm12": offset, "NoBnt": 1})
```

#### 5.2.3 操作数键参考

| 键名 | 适用指令类型 | 说明 |
|------|-------------|------|
| `rd` | 所有 | 目标寄存器索引 |
| `rs1` | 所有 | 源寄存器 1 索引 |
| `rs2` | R-type | 源寄存器 2 索引 |
| `simm12` | I-type | 12 位有符号立即数 |
| `simm20` | U-type | 20 位有符号立即数 |
| `shamt` | shift | 移位量 |
| `csr` | CSR | CSR 寄存器地址 |
| `LSTarget` | Load/Store | 加载/存储目标地址 |
| `uimm5` | Vector | 5 位无符号立即数 |
| `zimm10` | Vector | 10 位 vtype 编码 |
| `NoRestriction` | 所有 | 1=跳过限制检查 |
| `NoBnt` | Branch | 1=不生成 BNT 序列 |
| `NoSkip` | 所有 | 1=不允许跳过该指令 |
| `SpeculativeBnt` | MetaInstr | 是否启用推测性 BNT（默认 True） |

### 5.3 指令选择 18 种模式

#### 模式 1：确定性选择

```python
class MainSequence(Sequence):
    def generate(self, **kargs):
        self.genInstruction("ADD##RISCV")
        self.genInstruction("SUB##RISCV")
        self.genInstruction("LD##RISCV")
        self.genInstruction("SD##RISCV")
```

#### 模式 2：从指令树加权随机选择

```python
from DV.riscv.trees.instruction_tree import RV_G_instructions

class MainSequence(Sequence):
    def generate(self, **kargs):
        for _ in range(100):
            instr = self.pickWeighted(RV_G_instructions)
            self.genInstruction(instr)
```

#### 模式 3：按功能单元选择

```python
from DV.riscv.trees.instruction_tree import (
    ALU_Int_All_instructions,
    LDST_All_instructions,
    BranchJump_instructions,
    ALU_Float_Double_instructions,
    ALU_M_instructions,
    RV_A_instructions,
)

class MainSequence(Sequence):
    def generate(self, **kargs):
        for _ in range(50):
            self.genInstruction(self.pickWeighted(LDST_All_instructions))
        for _ in range(50):
            self.genInstruction(self.pickWeighted(ALU_Int_All_instructions))
        for _ in range(10):
            self.genInstruction(self.pickWeighted(BranchJump_instructions))
```

#### 模式 4：使用 InstructionMap.pick()

```python
from DV.riscv.trees.instruction_tree import RV_G_map

class MainSequence(Sequence):
    def generate(self, **kargs):
        for _ in range(100):
            instr = RV_G_map.pick(self.genThread)
            self.genInstruction(instr)
```

#### 模式 5：RV32/RV64 自适应

```python
from DV.riscv.trees.instruction_tree import RV_G_instructions, RV32_G_instructions

class MainSequence(Sequence):
    def generate(self, **kargs):
        if self.getGlobalState("AppRegisterWidth") == 32:
            instr_tree = RV32_G_instructions
        else:
            instr_tree = RV_G_instructions
        for _ in range(100):
            self.genInstruction(self.pickWeighted(instr_tree))
```

#### 模式 6：choice() 随机选择

```python
class MainSequence(Sequence):
    def generate(self, **kargs):
        instrs = ["ADD##RISCV", "SUB##RISCV", "SLLI#RV64I#RISCV",
                  "ADDI##RISCV", "XORI##RISCV"]
        for _ in range(10):
            for _ in range(self.random32(0, 5)):
                self.genInstruction(self.choice(instrs))
```

#### 模式 7：sample() 随机采样

```python
class MainSequence(Sequence):
    def generate(self, **kargs):
        from DV.riscv.trees.instruction_tree import ALU_Int32_instructions
        instr_list = list(ALU_Int32_instructions.keys())
        sublist = self.sample(instr_list, 5)
        for instr in sublist:
            self.genInstruction(instr)
```

#### 模式 8：寄存器依赖链

```python
class MainSequence(Sequence):
    def generate(self, **kwargs):
        for _ in range(10):
            rec_id1 = self.genInstruction("ADD##RISCV")
            obj1 = self.queryInstructionRecord(rec_id1)
            target_reg = obj1["Dests"]["rd"]
            if target_reg == 0:
                continue
            # ADDs result feeds SUBs rs1
            rec_id2 = self.genInstruction("SUB##RISCV", {"rs1": target_reg})
            obj2 = self.queryInstructionRecord(rec_id2)
            src_reg = obj2["Srcs"]["rs1"]
            if src_reg == target_reg:
                self.notice("RAW dependency created")
```

#### 模式 9：页边界跨越

```python
from DV.riscv.trees.instruction_tree import LDST_All_instructions

class MainSequence(Sequence):
    def generate(self, **kargs):
        for _ in range(100):
            instr = self.pickWeighted(LDST_All_instructions)
            # 获取两个相邻 4K 页面
            page_addr = self.genVA(Size=0x2000, Align=0x1000)
            target_addr = page_addr + 0xFFC  # 靠近页边界
            self.genInstruction(instr, {"LSTarget": target_addr})
```

#### 模式 10：汇编辅助类

```python
from riscv.AssemblyHelperRISCV import AssemblyHelperRISCV

class MainSequence(Sequence):
    def generate(self, **kargs):
        asm = AssemblyHelperRISCV(self)
        (r1, r2) = self.getRandomGPRs(2, exclude="0")

        asm.genMoveImmediate(r1, 42)
        asm.genAddImmediate(r2, r1, 100)
        asm.genShiftLeftImmediate(r1, 4)
        asm.genAndRegister(r1, r2)
        asm.genReadSystemRegister(r1, "mscratch")
        asm.genWriteSystemRegister("mscratch", r2)
        asm.genConditionalBranch(r1, r2, 16, "EQ")
        asm.genExceptionReturn(priv_level)  # MRET/SRET
```

#### 模式 11：特权级切换

```python
class MainSequence(Sequence):
    def generate(self, **kargs):
        self.systemCall({
            "Function": "SwitchPrivilegeLevel",
            "PrivilegeLevel": 1,  # S-mode
            "InterruptMask": 1,
            "SkipAddrValidation": 0,
        })
```

#### 模式 12：异常处理

```python
class MainSequence(Sequence):
    def generate(self, **kargs):
        result = self.exceptionRequest("SystemCall", {
            "PrivilegeLevel": 1,
        })
```

#### 模式 13：异常委托

```python
def gen_thread_initialization(gen_thread):
    from base.ChoicesModifier import ChoicesModifier
    delegation = ChoicesModifier(gen_thread)
    delegation.modifyRegisterFieldValueChoices(
        "medeleg.Load page fault", {"0x0": 0, "0x1": 50}
    )
    delegation.commitSet()

GenThreadInitialization = gen_thread_initialization
```

#### 模式 14：分页故障（PageFaultSequence）

```python
from PageFaultSequence import PageFaultSequence
from riscv.ModifierUtils import PageFaultModifier

class MainSequence(PageFaultSequence):
    def __init__(self, gen_thread, name=None):
        super().__init__(gen_thread, name)
        self._mInstrList = ("LD##RISCV", "SD##RISCV")
        self._mExceptionCodes = (13, 15)

    def createPageFaultModifier(self):
        return PageFaultModifier(self.genThread,
                                 self.getGlobalState("AppRegisterWidth"))

    def getInstructionList(self):
        return self._mInstrList

    def getExceptionCodes(self):
        return self._mExceptionCodes
```

#### 模式 15：循环控制

```python
from riscv.Utils import LoopControl

class MainSequence(Sequence):
    def generate(self, **kargs):
        (loop_reg,) = self.getRandomRegisters(1, "GPR", "0")
        ctrl = LoopControl(self.genThread)
        ctrl.start(LoopReg=loop_reg, LoopCount=5)
        for _ in range(10):
            self.genInstruction("ADD##RISCV")
        ctrl.end()
```

#### 模式 16：多线程共享

```python
class MainSequence(Sequence):
    def generate(self, **kargs):
        with self.threadLockingContext():
            if not self.hasSharedThreadObject("ShrAddr"):
                pa = self.genPA(Size=8, Align=8, Type="D", Shared=1)
                self.setSharedThreadObject("ShrAddr", pa)
        addr = self.getSharedThreadObject("ShrAddr")
        va = self.genVAforPA(Size=8, Align=8, Type="D", PA=addr, CanAlias=1)
```

#### 模式 17：向量（VSETIVLI）

```python
from VectorTestSequence import VectorVsetvlTestSequence

class MainSequence(VectorVsetvlTestSequence):
    def __init__(self, aGenThread, aName=None):
        super().__init__(aGenThread, aName)
        self._mInstrList = ("VSETIVLI##RISCV",)

    def _getInstructionList(self):
        return self._mInstrList

    def _generateInstructionParameters(self):
        return {"uimm5": self.mAvl, "zimm10": self.mVtype}

    def _get_max_avl(self):
        return 0x1F
```

#### 模式 18：状态转换

```python
import StateTransition
from Enums import EStateElementType, EStateTransitionOrderMode, EStateTransitionType
from State import State

class MainSequence(Sequence):
    def generate(self, **kargs):
        StateTransition.registerStateTransitionHandler(
            MyHandler(self.genThread),
            EStateTransitionType.Explicit,
            (EStateElementType.GPR,),
        )
        StateTransition.setDefaultStateTransitionOrderMode(
            EStateTransitionType.Boot,
            EStateTransitionOrderMode.ByStateElementType,
            order,
        )
        state = State()
        StateTransition.transitionToState(state)
```

### 5.4 序列编排

#### 5.4.1 子序列

```python
class MainSequence(Sequence):
    def generate(self, **kargs):
        seq = MySubSequence(self.genThread)
        seq.run()

class MySubSequence(Sequence):
    def generate(self, **kargs):
        for _ in range(10):
            self.genInstruction("ADD##RISCV")
```

#### 5.4.2 序列生命周期

```python
class MySequence(Sequence):
    def setup(self, **kargs):
        # 在 generate() 之前调用
        pass
    def generate(self, **kargs):
        # 主生成逻辑
        pass
    def cleanUp(self, **kargs):
        # 在 generate() 之后调用
        pass
```

#### 5.4.3 入口函数

```python
class MySequence(Sequence):
    def __init__(self, gen_thread):
        super().__init__(gen_thread)
        self.entryFunction = self.myEntry
    def myEntry(self, arg1, arg2, **kargs):
        self.generate(**kargs)
    def generate(self, **kargs):
        pass

seq = MySequence(self.genThread)
seq.run(arg1=10, arg2=20)  # 调用 myEntry(10, 20)
```

#### 5.4.4 序列库

```python
from base.SequenceLibrary import SequenceLibrary

class MainSequence(Sequence):
    def generate(self, **kargs):
        lib = MySequenceLibrary(self.genThread)
        lib.chooseOne().run()
        for seq in lib.getPermutated():
            seq.run()

class MySequenceLibrary(SequenceLibrary):
    def createSequenceList(self):
        self.seqList = [
            ("Bunch_of_ALU", "DV.riscv.sequences.BasicSequences",
             "ALU sequence", 20),
        ]
```

### 5.5 权重修改

#### 5.5.1 修改 GPR 选择概率

```python
from base.ChoicesModifier import ChoicesModifier

class MainSequence(Sequence):
    def generate(self, **kargs):
        cm = ChoicesModifier(self.genThread)
        cm.modifyOperandChoices("GPRs", {"x10": 60, "x11": 60})
        cm.commitSet()
        for _ in range(100):
            self.genInstruction("ADD##RISCV")
        cm.revert()
```

#### 5.5.2 初始化钩子修改

```python
def gen_thread_initialization(gen_thread):
    cm = ChoicesModifier(gen_thread)
    cm.modifyOperandChoices("GPRs", {"x10": 40, "x11": 40})
    cm.commitSet()
GenThreadInitialization = gen_thread_initialization
```

#### 5.5.3 五种修改类型

```python
cm = ChoicesModifier(self.genThread)

# 1. 操作数选择
cm.modifyOperandChoices("GPRs", {"x10": 60})

# 2. 寄存器字段值选择
cm.modifyRegisterFieldValueChoices("medeleg.Load page fault", {"0x0": 0, "0x1": 50})

# 3. 分页选择
cm.modifyPagingChoices("PageSize", {"4KB": 50, "2MB": 50})

# 4. 通用选择
cm.modifyGeneralChoices("Privilege Switch - Target Privilege",
                        {"U": 20, "S": 30, "M": 50})

# 5. 依赖选择
cm.modifyDependenceChoices("DependenceType", {"ReadAfterWrite": 50})
cm.commitSet()
```

#### 5.5.4 自定义 ChoicesModifier 子类

```python
class MyModifier(ChoicesModifier):
    def update(self, **kwargs):
        self.modifyOperandChoices("GPRs", {"x10": 60, "x11": 60})
        self.modifyGeneralChoices("Privilege Switch - Target Privilege",
                                  {"U": 0, "S": 50, "M": 50})

mod = MyModifier(self.genThread)
mod.apply()  # update() + commitSet()
```

### 5.6 寄存器操作参考

```python
# 获取寄存器
gpr = self.getRandomGPR(exclude="0")
(r1, r2, r3) = self.getRandomGPRs(3, exclude="0")
(reg,) = self.getRandomRegisters(1, "GPR", "0")
gpr = self.getRandomGPRForAccess("Write", exclude="0")

# 读写寄存器
self.writeRegister("mscratch", 0x456)
self.writeRegister("satp", "MODE", 8)  # 按字段写入
(val, valid) = self.readRegister("mscratch")
(mode_val, valid) = self.readRegister("satp", "MODE")

# 初始化
self.initializeRegister("mscratch", 0x123)
self.initializeRegisterFields("satp", {"MODE": 8, "PPN": 0})
self.randomInitializeRegister("mscratch")
self.randomInitializeRegisterFields("mstatus", {"MIE", "MPP"})
mask = self.getRegisterFieldMask("mstatus", ["MIE", "MPP"])

# 预留/释放
self.reserveRegister("x5")
self.reserveRegisterByIndex(64, 5, "GPR")
self.unreserveRegister("x5")
self.unreserveRegisterByIndex(64, 5, "GPR")
if self.isRegisterReserved("x5"):
    pass
```

### 5.7 地址生成参考

```python
# 虚拟地址
va = self.genVA(Size=8, Align=8, Type="D")

# 物理地址
pa = self.genPA(Size=8, Align=8, Type="D", Shared=1)

# 地址转换
va = self.genVAforPA(Size=8, Align=8, Type="D", PA=pa, CanAlias=1)

# 页信息
info = self.getPageInfo(addr, "Virtual", 0)

# 地址验证
valid = self.verifyVirtualAddress(vaddr, 4, False)

# 最大地址
max_pa = self.getMaxPhysicalAddress()
max_va = self.getMaxVirtualAddress()
```

### 5.8 内存操作参考

```python
# 初始化内存
self.initializeMemory(addr=0x80000000, bank=0, size=1024,
                      data=my_data, is_instr=False, is_virtual=False)

# 预留内存
self.reserveMemory(Name="MyReg", Range="0x80000000-0x80000FFF",
                   Bank=0, IsVirtual=False)
self.reserveMemoryRange(Name="MyReg", Start=0x80000000,
                        Size=0x1000, Bank=0, IsVirtual=False)

# 释放
self.unreserveMemory(Name="MyReg", Bank=0)
self.unreserveMemoryRange(Name="MyReg", Start=0x80000000,
                          Size=0x1000, Bank=0)
```

### 5.9 加载立即数（LoadGPR64）

```python
from riscv.Utils import LoadGPR64

class MainSequence(Sequence):
    def generate(self, **kargs):
        (reg,) = self.getRandomRegisters(1, "GPR", "0")
        loader = LoadGPR64(self.genThread)
        loader.load(reg, 0xDEADBEEFCAFEBABE)
        loader.load(reg, 0xCAFEBABE)  # RV32 自动截断
```

### 5.10 VM/MMU 操作

```python
self.updateVm()
ctx = self.getVmCurrentContext()
delta = self.getVmContextDelta()
self.genVmContext()
```

### 5.11 线程管理

```python
# 共享对象
self.setSharedThreadObject("data", my_obj)
obj = self.getSharedThreadObject("data")

# 同步
with self.threadLockingContext():
    pass  # 临界区
self.synchronizeWithBarrier()

# 线程组
groups = self.queryThreadGroup()
gid = self.getThreadGroupId()
self.partitionThreadGroup("ByChip")
self.setThreadGroup(0, "Main", [0, 1, 2, 3])
free = self.getFreeThreads()
total = self.getThreadNumber()
```

### 5.12 状态查询

```python
# 全局状态
reg_width = self.getGlobalState("AppRegisterWidth")

# PE 状态
pc = self.getPEstate("PC")
priv = self.getPEstate("PrivilegeLevel")
self.setPEstate("PrivilegeLevel", 1)

# 测试选项
(no_handler, valid) = self.getOption("NoHandler")

# 限制值
max_instr = self.getLimitValue("MaxInstructions")
```

### 5.13 查询与调试

```python
# 指令记录
rec_id = self.genInstruction("ADD##RISCV")
rec = self.queryInstructionRecord(rec_id)
# rec = {"Dests": {"rd": 5}, "Srcs": {"rs1": 6, "rs2": 7}, ...}

# 异常记录
count = self.queryExceptionRecordsCount(exc_id)
records = self.queryExceptionRecords(exc_id)
exceptions = self.queryExceptions()

# 资源熵
entropy = self.queryResourceEntropy("GPR")

# 日志（推荐使用 Log 模块）
import Log
Log.notice("message")
Log.warn("warning")
Log.info("info")
Log.debug("debug")

# 对象转储
self.dumpPythonObject({"key": 0xABCD}, a_hex=True)
```

### 5.14 BNT 和 ERET 挂钩

```python
self.setBntHook(bnt_type="MyBntHandler")
self.revertBntHook(bnt_id=0)

self.setEretPreambleSequence("MyEretSeq", eretGlobal=True)
self.revertEretPreambleSequence(eretGlobal=True)
```

### 5.15 配置变量操作

```python
self.modifyVariable("Inter-Dependency Window", "1-30:100", "Choice")
val = self.getVariable("System Physical Address Range", "String")
reload_val = self.getRegisterReloadValue("mscratch")
field_info = self.genRegisterFieldInfo("mstatus", ["MIE", "MPP"])
```

### 5.16 宏指令和数据生成

```python
self.genMacro("MyMacro", {"param1": "value1"})
self.genInstrOrSequence("ADD##RISCV")
self.genInstrOrSequence(MySubSequence)
data = self.genData({"size": 8, "pattern": "Random"})
pages = self.genFreePagesRange(Size=0x1000, Align=0x1000)
```

### 5.17 两阶分页（H-extension）

```python
# 在 GenThreadRISCV 中调用
gen_thread.setupVsStagePaging(mode="Sv39")
gen_thread.setupGStagePaging(mode="Sv39x4")
gen_thread.setupTwoStageVm()
```

### 5.18 完整的测试示例

#### 完整示例 1：基本随机测试

```python
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from DV.riscv.trees.instruction_tree import RV_G_instructions

class MainSequence(Sequence):
    def generate(self, **kargs):
        for _ in range(100):
            instr = self.pickWeighted(RV_G_instructions)
            self.genInstruction(instr)

MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
```

#### 完整示例 2：ChoicesModifier + 使用计数

```python
from DV.riscv.trees.instruction_tree import RV_G_instructions
from base.ChoicesModifier import ChoicesModifier
from base.Sequence import Sequence
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV

class MainSequence(Sequence):
    def generate(self, **kwargs):
        usage = {}
        for _ in range(1000):
            instr = self.pickWeighted(RV_G_instructions)
            rec_id = self.genInstruction(instr)
            obj = self.queryInstructionRecord(rec_id)
            if "Dests" in obj and "rd" in obj["Dests"]:
                name = "x%d" % obj["Dests"]["rd"]
                usage[name] = usage.get(name, 0) + 1
        for name in sorted(usage):
            self.notice("Usage %s: %d" % (name, usage[name]))

def gen_thread_initialization(gen_thread):
    cm = ChoicesModifier(gen_thread)
    cm.modifyOperandChoices("GPRs", {"x10": 40, "x11": 40, "x12": 60, "x13": 60})
    cm.commitSet()

GenThreadInitialization = gen_thread_initialization
MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
```

#### 完整示例 3：特权级切换

```python
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence

class MainSequence(Sequence):
    def generate(self, **kargs):
        if self.getGlobalState("AppRegisterWidth") == 32:
            instrs = ["ADD##RISCV", "ADDI##RISCV", "LUI##RISCV"]
        else:
            instrs = ["ADDW##RISCV", "ADDI##RISCV", "LUI##RISCV"]
        ret_instrs = ["MRET##RISCV"]
        for _ in range(10):
            for _ in range(self.random32(0, 5)):
                self.genInstruction(self.choice(instrs))
        self.genInstruction(self.choice(ret_instrs), {"NoSkip": 1})
        for _ in range(10):
            for _ in range(self.random32(0, 5)):
                self.genInstruction(self.choice(instrs))

MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
```

#### 完整示例 4：多线程基础

```python
import RandomUtils
from DV.riscv.trees.instruction_tree import RV32I_map, RV64I_map
from base.Sequence import Sequence
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV

class MainSequence(Sequence):
    def generate(self, **kargs):
        for _ in range(RandomUtils.random32(250, 300)):
            if self.getGlobalState("AppRegisterWidth") == 32:
                instr = RV32I_map.pick(self.genThread)
            else:
                instr = RV64I_map.pick(self.genThread)
            self.genInstruction(instr)

MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
```

#### 完整示例 5：多线程信号量

```python
import RandomUtils
from DV.riscv.trees.instruction_tree import BranchJump_map, RV_G_map, RV32_G_map
from base.Sequence import Sequence
from riscv.EnvRISCV import EnvRISCV
from riscv.GenSemaphoreRISCV import GenSemaphore32RISCV, GenSemaphore64RISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from riscv.Utils import LoadGPR64

class MainSequence(Sequence):
    def generate(self, **kargs):
        addr32 = self._genSharedVa("Addr32")
        addr64 = self._genSharedVa("Addr64")
        sema32 = GenSemaphore32RISCV(self.genThread, "Sem32", 1)
        if self.getGlobalState("AppRegisterWidth") == 64:
            sema64 = GenSemaphore64RISCV(self.genThread, "Sem64", 1)
        for _ in range(3):
            with sema32:
                self._do_excl_store_load(addr32)
        sema32.cleanUp()

    def _genSharedVa(self, name):
        with self.threadLockingContext():
            if self.hasSharedThreadObject(name):
                pa = self.getSharedThreadObject(name)
            else:
                pa = self.genPA(Size=8, Align=8, Type="D", Shared=1)
                self.setSharedThreadObject(name, pa)
        return self.genVAforPA(Size=8, Align=8, Type="D", PA=pa, CanAlias=1)

    def _do_excl_store_load(self, addr):
        src = self.getRandomGPR(exclude="0")
        self.reserveRegister("x%d" % src)
        loader = LoadGPR64(self.genThread)
        val = RandomUtils.random64()
        loader.load(src, val)
        self.genInstruction("SD##RISCV", {"rs2": src, "LSTarget": addr})
        self.unreserveRegister("x%d" % src)
        for _ in range(RandomUtils.random32(5, 10)):
            self.genInstruction(RV_G_map.pick(self.genThread))

MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
```

#### 完整示例 6：页故障

```python
from PageFaultSequence import PageFaultSequence
from base.ChoicesModifier import ChoicesModifier
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from riscv.ModifierUtils import PageFaultModifier

class MainSequence(PageFaultSequence):
    def __init__(self, gen_thread, name=None):
        super().__init__(gen_thread, name)
        self._mInstrList = ("LD##RISCV", "SD##RISCV")
        self._mExceptionCodes = (13, 15)
        self._mExceptionSubCodes = {}

    def createPageFaultModifier(self):
        return PageFaultModifier(self.genThread,
                                 self.getGlobalState("AppRegisterWidth"))

    def getInstructionList(self):
        return self._mInstrList

    def getExceptionCodes(self):
        return self._mExceptionCodes

def gen_thread_initialization(gen_thread):
    (delegate_opt, valid) = gen_thread.getOption("DelegateExceptions")
    if valid and delegate_opt == 1:
        delegation = ChoicesModifier(gen_thread)
        delegation.modifyRegisterFieldValueChoices(
            "medeleg.Load page fault", {"0x0": 0, "0x1": 50})
        delegation.modifyRegisterFieldValueChoices(
            "medeleg.Store/AMO page fault", {"0x0": 0, "0x1": 50})
        delegation.commitSet()

GenThreadInitialization = gen_thread_initialization
MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
```

#### 完整示例 7：AssemblyHelper 验证

```python
import RandomUtils
from base.Sequence import Sequence
from riscv.AssemblyHelperRISCV import AssemblyHelperRISCV
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from riscv.Utils import LoadGPR64

class MainSequence(Sequence):
    def generate(self, **kargs):
        asm = AssemblyHelperRISCV(self)
        (d, s1, s2) = self.getRandomGPRs(3, exclude="0")
        loader = LoadGPR64(self.genThread)
        sv1 = RandomUtils.random64()
        sv2 = RandomUtils.random64()
        loader.load(s1, sv1)
        loader.load(s2, sv2)

        # Test immediate operations
        asm.genMoveImmediate(d, 42)
        asm.genAddImmediate(d, 100)
        asm.genAndImmediate(d, 0xFF)
        asm.genOrImmediate(d, 0xF00)
        asm.genXorImmediate(d, 0xABC)

        # Test shift operations
        asm.genShiftLeftImmediate(d, 4)
        asm.genShiftRightImmediate(d, 2)

        # Test register operations
        asm.genMoveRegister(d, s1)
        asm.genAddRegister(d, s1, s2)
        asm.genSubRegister(d, s1, s2)
        asm.genAndRegister(d, s1)
        asm.genOrRegister(d, s1)
        asm.genNotRegister(d)

        # Test CSR operations
        asm.genReadSystemRegister(d, "mscratch")
        asm.genWriteSystemRegister("mscratch", s1)

MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
```

#### 完整示例 8：EntryPoint

```python
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence

class TestUtil(Sequence):
    def __init__(self, gen_thread):
        super().__init__(gen_thread)
        self.entryFunction = self.load
        self.testValue = 0

    def load(self, arg1, arg2, **kargs):
        self.testValue = arg1 + arg2
        self.generate(**kargs)

    def generate(self, **kargs):
        for (key, value) in sorted(kargs.items()):
            self.notice("%s=%s" % (key, value))
        self.notice("testValue=%d" % self.testValue)

class MainSequence(Sequence):
    def generate(self, **kargs):
        util = TestUtil(self.genThread)
        util.run(arg1=1, arg2=4, arg3=423)
        util.entryFunction = None
        util.run(arg1=1, arg2=9, arg3=32)

MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
```

#### 完整示例 9：SequenceLibrary

```python
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from base.SequenceLibrary import SequenceLibrary

class MainSequence(Sequence):
    def generate(self, **kargs):
        lib = MySeqLib(self.genThread)
        for _ in range(4):
            lib.chooseOne().run()
        for seq in lib.getPermutated():
            seq.run()

class MySeqLib(SequenceLibrary):
    def createSequenceList(self):
        self.seqList = [
            ("Bunch_of_ALU_Int", "DV.riscv.sequences.BasicSequences",
             "ALU Int", 20),
            ("Bunch_of_LDST", "DV.riscv.sequences.BasicSequences",
             "LDST", 20),
        ]

MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
```

#### 完整示例 10：序列排列（um_sequences_01_force.py）

```python
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from DV.riscv.trees.instruction_tree import ALU_Int32_instructions
from DV.riscv.trees.instruction_tree import ALU_Float_Double_instructions

class MainSequence(Sequence):
    def generate(self, **kwargs):
        I100Sequence(self.genThread).run()
        F100Sequence(self.genThread).run()

class I100Sequence(Sequence):
    def generate(self, **kargs):
        for _ in range(100):
            self.genInstruction(self.pickWeighted(ALU_Int32_instructions))

class F100Sequence(Sequence):
    def generate(self, **kargs):
        for _ in range(100):
            self.genInstruction(self.pickWeighted(ALU_Float_Double_instructions))

MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
```

---

## 6. Python API 参考

### 6.1 Sequence 类（py/base/Sequence.py）

所有测试模板的基类。提供完整的指令生成、寄存器操作、地址生成和随机化 API。

#### 6.1.1 生命周期方法

**`__init__(self, gen_thread, name=None)`**

| 参数 | 类型 | 说明 |
|------|------|------|
| `gen_thread` | GenThread | 生成线程对象 |
| `name` | str/None | 序列名称（可选） |

**`setup(self, **kargs)`** — 在 `generate()` 之前调用。

**`generate(self, **kargs)`** — 主生成方法。

**`cleanUp(self, **kargs)`** — 在 `generate()` 之后调用。

**`run(self, **kargs)`** — 执行序列。如果 `entryFunction` 为 None，按 `setup()` → `generate()` → `cleanUp()` 顺序执行。

**`getResult(self)`** — 返回序列结果。基类返回 None。

#### 6.1.2 指令生成方法

**`genInstruction(self, instr_name, kargs=dict())`** → int

| 参数 | 类型 | 说明 |
|------|------|------|
| `instr_name` | str | 指令名称（如 `"ADD##RISCV"`） |
| `kargs` | dict | 操作数指定字典 |
| **返回** | int | 指令记录 ID |

**`genMetaInstruction(self, instr_name, kargs=dict())`** → int

| 参数 | 类型 | 说明 |
|------|------|------|
| `instr_name` | str | 指令名称 |
| `kargs` | dict | 参数（自动添加 `SpeculativeBnt=True`） |
| **返回** | int | 指令记录 ID |

**`genSequence(self, my_type, kargs={})`**

| 参数 | 类型 | 说明 |
|------|------|------|
| `my_type` | str | 序列类型名称 |
| `kargs` | dict | 序列参数 |

**`genMacro(self, item, param)`**

| 参数 | 类型 | 说明 |
|------|------|------|
| `item` | str/Macro | 宏名称或 Macro 对象 |
| `param` | str | 宏参数字符串 |

**`genInstrOrSequence(self, item, kargs=dict())`** → int/Sequence/None

自动识别指令字符串或序列对象并执行。

| 参数 | 类型 | 说明 |
|------|------|------|
| `item` | str/Sequence/type | 指令名、序列实例或序列类 |
| `kargs` | dict | 参数 |

#### 6.1.3 查询方法

**`queryInstructionRecord(self, rec_id)`** → dict

| 参数 | 类型 | 说明 |
|------|------|------|
| `rec_id` | int | 指令记录 ID |
| **返回** | dict | 包含 Dests、Srcs、Name、Address 等 |

**`queryExceptionRecordsCount(self, exception_id)`** → int

**`queryExceptionRecords(self, exception_id)`** → list

**`queryExceptions(self, **kargs)`** → list

**`queryResourceEntropy(self, resource_type)`** → float

| 参数 | 类型 | 说明 |
|------|------|------|
| `resource_type` | str | 如 "GPR" |

**`queryExceptionVectorBaseAddress(self, vector_type)`** → int

**`queryHandlerSetMemory(self, bank)`** → dict

**`queryThreadGroup(self, aGroupId=None)`** → list

| 参数 | 类型 | 说明 |
|------|------|------|
| `aGroupId` | int/None | 组 ID，None=全部 |

**`getThreadGroupId(self, aThreadId=None)`** → int

**`getFreeThreads(self)`** → list

#### 6.1.4 VM/MMU 方法

**`getVmContextDelta(self, **kargs)`** → dict
**`genVmContext(self, **kargs)`** → int
**`getVmCurrentContext(self, **kargs)`** → dict
**`updateVm(self, **kargs)`**
**`verifyVirtualAddress(self, vaddr, size, is_instr)`** → bool
**`confirmSpace(self, size)`**

#### 6.1.5 状态方法

**`setGlobalState(self, state_name, state_value)`**

| 参数 | 类型 | 说明 |
|------|------|------|
| `state_name` | str | 如 "AppRegisterWidth" |
| `state_value` | int | |

**`getGlobalState(self, state_name)`** → int

**`getLimitValue(self, limit_name)`** → int

**`setPEstate(self, state_name, state_value)`**

| 参数 | 类型 | 说明 |
|------|------|------|
| `state_name` | str | "PC", "PrivilegeLevel" |
| `state_value` | int | |

**`getPEstate(self, state_name)`** → int

**`getOption(self, optName)`** → tuple

返回 `(value, valid)`，valid 为 bool。

#### 6.1.6 随机化方法

**`pickWeighted(self, weighted_dict)`** → str

| 参数 | 类型 | 说明 |
|------|------|------|
| `weighted_dict` | dict | `{key: weight}` 格式 |

**`pickWeightedValue(self, weighted_dict)`** → object

**`choice(self, items)`** → object

| 参数 | 类型 | 说明 |
|------|------|------|
| `items` | list/dict/str/tuple | 选项集合 |

**`choicePermutated(self, items)`** → generator

**`sample(self, items, sample_size)`** → list

**`getPermutated(self, weighted_dict, skip_weight_check=False)`** → generator

#### 6.1.7 寄存器方法

**`getRandomRegisters(self, number, reg_type, exclude="", no_skip=False)`** → tuple

| 参数 | 类型 | 说明 |
|------|------|------|
| `number` | int | 寄存器数量 |
| `reg_type` | str | "GPR", "FPR" 等 |
| `exclude` | str | 排除索引，逗号分隔 |
| `no_skip` | bool | 无可用时是否报错 |

**`getRandomRegistersForAccess(self, number, reg_type, access, exclude="", no_skip=False)`** → tuple

| 参数 | 类型 | 说明 |
|------|------|------|
| `access` | str | "Read" 或 "Write" |

**`getRandomGPRs(self, number, exclude="", no_skip=False)`** → tuple（自动排除 x31）

**`getRandomGPRsForAccess(self, number, access, exclude="", no_skip=False)`** → tuple

**`getRandomGPR(self, exclude="", no_skip=False)`** → int

**`getRandomGPRForAccess(self, access, exclude="", no_skip=False)`** → int

**`readRegister(self, name, field="")`** → tuple

| 返回 | 说明 |
|------|------|
| (value, valid) | valid 为 bool |

**`writeRegister(self, name, value, field="", update=False)`**

**`initializeRegister(self, name, value, field="")`**

**`initializeRegisterFields(self, register_name, field_value_map)`**

| 参数 | 类型 | 说明 |
|------|------|------|
| `field_value_map` | dict | `{field: value}` |

**`randomInitializeRegister(self, name, field="")`**

**`randomInitializeRegisterFields(self, register_name, field_list)`**

**`getRegisterFieldMask(self, register_name, field_list)`** → int

**`isRegisterReserved(self, name, access="Write", resv_type="User")`** → bool

**`reserveRegisterByIndex(self, size, index, reg_type, access="Write")`**

**`reserveRegister(self, name, access="Write")`**

**`unreserveRegisterByIndex(self, size, index, my_type, access="Write")`**

**`unreserveRegister(self, name, access="Write", reserve_type="User")`**

#### 6.1.8 地址方法

**`genPA(self, **kargs)`** → int

| 参数 | 说明 |
|------|------|
| `Size` | 地址区域大小 |
| `Align` | 对齐要求 |
| `Type` | "D"=数据, "I"=指令 |
| `Shared` | 1=共享 |

**`genVA(self, **kargs)`** → int

**`genVMVA(self, **kargs)`** → int

**`genVAforPA(self, **kargs)`** → int

| 参数 | 说明 |
|------|------|
| `PA` | 物理地址 |
| `CanAlias` | 1=允许别名 |

#### 6.1.9 内存方法

**`initializeMemory(self, addr, bank, size, data, is_instr, is_virtual)`**

**`reserveMemory(self, Name, Range, Bank, IsVirtual=False)`**

**`reserveMemoryRange(self, Name, Start, Size, Bank, IsVirtual=False)`**

**`unreserveMemory(self, Name, Range="", Bank=0, IsVirtual=False)`**

**`unreserveMemoryRange(self, Name, Start, Size, Bank, IsVirtual=False)`**

#### 6.1.10 地址计算方法

**`getRegisterInfo(self, name, index)`** → dict
**`getPageInfo(self, addr, addr_type, bank)`** → dict
**`getMaxPhysicalAddress(self)`** → int
**`getMaxVirtualAddress(self)`** → int
**`getMaxAddress(self, addr_type="Virtual")`** → int
**`getBranchOffset(self, br_addr, target_addr, offset_size, shift)`** → int
**`validAddressMask(self, addr, is_instr)`** → int

#### 6.1.11 寄存器索引/值方法

**`getRegisterIndex(self, registerName)`** → int
**`getRegisterReloadValue(self, registerName, fieldConstraints={})`** → int
**`genRegisterFieldInfo(self, registerName, fieldConstraints)`** → dict

#### 6.1.12 系统调用方法

**`systemCall(self, callDetails)`**
**`selfHostedDebug(self, params)`**
**`exceptionRequest(self, requestName, kargs)`** → dict
**`virtualMemoryRequest(self, requestName, parameters={})`**

#### 6.1.13 变量方法

**`modifyVariable(self, name, value, var_type)`**

| 参数 | 类型 | 说明 |
|------|------|------|
| `var_type` | str | "String", "Value", "Choice" |

**`getVariable(self, name, var_type)`** → str

#### 6.1.14 BNT/ERET 方法

**`setBntHook(self, **kargs)`**
**`revertBntHook(self, bnt_id=0)`**
**`setEretPreambleSequence(self, eretSequence, eretGlobal=True)`**
**`revertEretPreambleSequence(self, eretGlobal=True)`**

#### 6.1.15 数据生成方法

**`genData(self, kargs)`**
**`genFreePagesRange(self, **kargs)`** → tuple

#### 6.1.16 线程方法

**`setSharedThreadObject(self, name, a_object)`**
**`getSharedThreadObject(self, name)`** → object
**`hasSharedThreadObject(self, name)`** → bool
**`threadLockingContext(self)`** → context manager
**`synchronizeWithBarrier(self, **kargs)`**
**`partitionThreadGroup(self, aPolicy, **kargs)`**
**`setThreadGroup(self, aId, aJob, aThreads)`**
**`getThreadNumber(self)`** → int
**`lockThreadScheduler(self)`**
**`unlockThreadScheduler(self)`**

#### 6.1.17 日志方法

**`error(self, err_msg)`** — 终止测试
**`notice(self, msg)`**（已弃用）→ `Log.notice()`
**`warn(self, msg)`**（已弃用）→ `Log.warn()`
**`debug(self, msg)`**（已弃用）→ `Log.debug()`
**`info(self, msg)`**（已弃用）→ `Log.info()`
**`trace(self, msg)`**（已弃用）→ `Log.trace()`

#### 6.1.18 内部方法

**`dumpPythonObject(self, a_object, a_hex=False)`**

### 6.2 ChoicesModifier 类（py/base/ChoicesModifier.py）

**`__init__(self, gen_thread, name=None)`**

**`modifyOperandChoices(self, tree_name, mod_dict)`** — 操作数选择（类型 0）
**`modifyRegisterFieldValueChoices(self, tree_name, mod_dict)`** — 寄存器字段值（类型 1）
**`modifyPagingChoices(self, tree_name, mod_dict)`** — 分页（类型 2）
**`modifyGeneralChoices(self, tree_name, mod_dict)`** — 通用（类型 3）
**`modifyDependenceChoices(self, tree_name, mod_dict)`** — 依赖（类型 4）

**`commitSet(self)`** → int — 提交所有修改，返回 commit ID
**`registerSet(self)`** → int — 注册但不提交
**`revert(self, commitId=None)`** — 恢复修改
**`apply(self, **kwargs)`** — update() + commitSet()
**`register(self, **kwargs)`** — update() + registerSet()
**`update(self, **kwargs)`** — 子类重写
**`getChoicesTreeInfo(self, tree_name, tree_type)`** → dict

### 6.3 GenThreadRISCV 类（py/riscv/GenThreadRISCV.py）

**`setupBootRegion(self)`** — 设置启动指令内存
**`setupEssentials(self)`** — 核心初始化
**`getInitialPC(self)`** → int
**`getBootPC(self)`** → int
**`setDefaultStateTransitionHandlers(self)`**
**`assignSetupSequences(self)`**
**`installHandlers(self)`**
**`installAddressTable(self)`**
**`setupVsStagePaging(self, mode="Sv39")`**
**`setupGStagePaging(self, mode="Sv39x4")`**
**`setupTwoStageVm(self)`**

### 6.4 AssemblyHelperRISCV 类（py/riscv/AssemblyHelperRISCV.py）

**`genIncrementExceptionReturnAddress(scratch_reg, priv_reg)`**
**`genProvidedExceptionReturnAddress(scratch_reg, recovery_reg, priv_reg)`**
**`genRelativeBranchToAddress(target_addr)`**
**`genRelativeBranch(br_offset)`**
**`genRelativeBranchToLabel(br_offset, label)`**
**`genRelativeBranchWithLinkToAddress(target_addr)`**
**`genRelativeBranchWithLink(br_offset)`**
**`genReturn()`**
**`genMoveImmediate(reg_idx, imm)`**
**`genShiftLeftImmediate(dest, amount, src=None)`**
**`genShiftRightImmediate(dest, amount, src=None)`**
**`getInstrForm()`** → str
**`genAndImmediate(dest, imm, src=None)`**
**`genOrImmediate(dest, imm, src=None)`**
**`genXorImmediate(dest, imm, src=None)`**
**`genAddImmediate(dest, imm, src=None)`**
**`genMoveRegister(dest, src)`**
**`genAndRegister(dest, src1, src2=None)`**
**`genOrRegister(dest, src1, src2=None)`**
**`genNotRegister(dest, src=None)`**
**`genAddRegister(dest, src1, src2=None)`**
**`genSubRegister(dest, subtrahend, minuend=None)`**
**`genReadSystemRegister(dest, sysreg_name)`**
**`genWriteSystemRegister(sysreg_name, src)`**
**`genConditionalBranchToAddress(lh, rh, target, cond)`**
**`genConditionalBranchToLabel(lh, rh, offset, cond, label)`**
**`genConditionalBranch(lh, rh, offset, cond)`**
**`genExceptionReturn(priv_level)`**
**`genPrivilegeLevelInstructions(levels, count, scratch, priv_reg)`** → generator

### 6.5 SystemCallSequence 类（py/riscv/SystemCallSequence.py）

**`generate(self, **kwargs)`**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `Function` | "SwitchPrivilegeLevel" | 功能 |
| `PrivilegeLevel` | "Random" | 目标特权级 |
| `TargetAddr` | 随机 | 恢复地址 |
| `SkipAddrValidation` | 0 | 跳过验证 |
| `AddrChoicesModID` | None | choices 修改集 ID |
| `InterruptMask` | "Random" | 中断掩码 |
| `SUM` | "Random" | SUM 位（不支持） |
| `MXR` | "Random" | MXR 位（不支持） |
| `MPRV` | "Random" | MPRV 位（不支持） |

### 6.6 Utils 类（py/riscv/Utils.py）

**`LoadGPR64.load(aRegIndex, aValue)`** — 加载 64 位值到 GPR

| 参数 | 类型 | 说明 |
|------|------|------|
| `aRegIndex` | int | 目标 GPR 索引 |
| `aValue` | int | 64 位值 |

**`LoopControl.start(LoopReg, LoopCount)`** — 开始循环

| 参数 | 类型 | 说明 |
|------|------|------|
| `LoopReg` | int | 循环计数器 GPR 索引 |
| `LoopCount` | int | 循环次数 |

**`LoopControl.end()`** — 结束循环

### 6.7 SequenceLibrary 类（py/base/SequenceLibrary.py）

**`createSequenceList(self)`** — 注册序列列表
**`chooseOne(self)`** → Sequence — 随机选一个
**`getPermutated(self, skip_weight_check=False)`** → generator

---

## 7. 配置系统

### 7.1 配置文件

配置文件是 XML 格式，位于 `config/` 目录：

| 文件 | 说明 |
|------|------|
| `riscv_rv64.config` | **默认** RV64 配置（Sv48 分页，V+H 扩展） |
| `riscv_rv32.config` | RV32 配置（Sv32 分页） |
| `riscv_rv64_sv39.config` | RV64 Sv39 分页配置 |
| `riscv_rv64_twostage.config` | RV64 两阶地址翻译配置（H 扩展） |
| `riscv-cva6.config` | CVA6 目标配置（遗留格式，可能已损坏） |

### 7.2 配置文件完整结构

```xml
<config_file>
  <limits>
    ...
  </limits>
  <instruction_files>...</instruction_files>
  <default_classes>...</default_classes>
  <register_files>...</register_files>
  <choices_files>...</choices_files>
  <paging_files>...</paging_files>
  <variable_files>...</variable_files>
  <memory_file/>
  <simulator_api_module/>
  <bnt_file/>
  <simulator_shared_object/>
  <simulator_config_string/>
  <simulator_standalone/>
</config_file>
```

### 7.3 Limits 完整参考

| limit name | 默认值 | 说明 |
|------------|--------|------|
| `ThreadsLimit` | 4 | 每核心最大线程数 |
| `CoresLimit` | 4 | 每芯片最大核心数 |
| `ChipsLimit` | 32 | 最大芯片数 |
| `PhysicalAddressLimit` | 0xffffffffffff | 物理地址上限 |
| `MaxInstructions` | 100000 | 最大模拟指令数 |
| `DependencyHistoryLimit` | 32 | 依赖历史记录大小 |
| `BranchNotTakenLimit` | 3 | BNT 最大深度 |
| `SpeculativeBntLevelLimit` | 3 | 推测性 BNT 级数限制 |
| `SpeculativeBntInstructionLimit` | 128 | 推测性 BNT 指令数限制 |
| `MaxPhysicalVectorLen` | 512 | 最大物理向量长度（位） |
| `MaxVectorElementWidth` | 64 | 最大向量元素宽度（位） |

### 7.4 operand_choices.xml — 所有 choices 名称

| Choices 名称 | 类型 | 说明 |
|-------------|------|------|
| `GPRs` | RegisterOperand | x0-x31 全部 32 个通用寄存器 |
| `Nonzero GPRs` | RegisterOperand | x1-x31（排除 x0） |
| `GPRs not x0, x2` | RegisterOperand | 排除 x0 和 x2（sp） |
| `Prime GPRs` | RegisterOperand | x8-x15（主要/临时 GPR） |
| `32-bit SIMD/FP registers` | RegisterOperand | S0-S31 单精度浮点 |
| `16-bit SIMD/FP registers` | RegisterOperand | H0-H31 半精度浮点 |
| `64-bit SIMD/FP registers` | RegisterOperand | D0-D31 双精度浮点 |
| `Prime 64-bit SIMD/FP registers` | RegisterOperand | D8-D15 主要双精度 |
| `128-bit SIMD/FP registers` | RegisterOperand | Q0-Q31 四精度浮点 |
| `Vector registers` | RegisterOperand | v0-v31 向量寄存器 |
| `Nonzero vector registers` | RegisterOperand | v1-v31（排除 v0） |
| `Integer data pattern` | ChoicesOperand | 13 种整数数据模式 |
| `Floating-point data pattern` | ChoicesOperand | 8 种浮点数据模式 |
| `FP-SIMD register data choices` | ChoicesOperand | 整数/浮点数据选择 |
| `Use addressing preamble` | ChoicesOperand | 地址前导使用 |
| `PC alignment` | ChoicesOperand | PC 对齐（对齐/未对齐） |
| `Data alignment` | ChoicesOperand | 数据对齐（3 种） |
| `Load data` | ChoicesOperand | 加载数据类型（3 种） |
| `Branch type choice` | ChoicesOperand | 分支类型（近/远） |
| `Ordered data alignment` | ChoicesOperand | 有序数据对齐（3 种） |
| `Rounding mode` | ImmediateOperand | 舍入模式（RNE/RTZ/RDN/RUP/RMM/DYN） |
| `Ret choice` | ChoicesOperand | 返回类型（合法/非法） |
| `Vector mask` | ImmediateOperand | 向量掩码 |
| `SP alignment` | ChoicesOperand | SP 对齐 |
| `Read after read address reuse` | ChoicesOperand | RAR 地址重用 |
| `Read after write address reuse` | ChoicesOperand | RAW 地址重用 |
| `Write after read address reuse` | ChoicesOperand | WAR 地址重用 |
| `Write after write address reuse` | ChoicesOperand | WAW 地址重用 |
| `Fence mode` | ImmediateOperand | Fence 模式（none/TSO） |
| `Barrier option` | ImmediateOperand | Barrier 选项（16 种 PI/O 组合） |

### 7.5 general_choices.xml — 所有 Choices 名称

| Choices 名称 | 说明 |
|-------------|------|
| `Starting jump` | 启动跳转方式（Branch/RET） |
| `Ending test` | 测试结束方式（Tube/BranchToSelf） |
| `Privilege Switch - Target Privilege` | 特权切换目标（U/S/H/M） |
| `Privilege level switch to lower or same level` | 同级/低级切换方式（ECALL/xRET） |
| `Privilege Switch - Default Target State` | 默认目标状态（Same/Random） |
| `Privilege Switch - Interrupt Mask` | 中断掩码 |
| `Privilege Switch - SUM Bit` | SUM 位 |
| `Privilege Switch - MXR Bit` | MXR 位 |
| `Privilege Switch - MPRV Bit` | MPRV 位 |
| `Reloading register alignment` | 寄存器重载对齐（Quad/ Double/Word/Byte） |
| `Reloading register methods` | 重载方法（Move/Load） |
| `Resolving free page range methods` | 空闲页范围解析（low/high/cross range） |
| `Redirect Trap - Instruction address misaligned` | 指令地址未对齐陷阱重定向 |
| `Redirect Trap - Instruction access fault` | 指令访问错误陷阱重定向 |
| `Redirect Trap - Illegal instruction` | 非法指令陷阱重定向 |
| `Redirect Trap - Breakpoint` | 断点陷阱重定向 |
| `Redirect Trap - Load address misaligned` | 加载地址未对齐陷阱重定向 |
| `Redirect Trap - Load access fault` | 加载访问错误陷阱重定向 |
| `Redirect Trap - Store/AMO address misaligned` | 存储地址未对齐陷阱重定向 |
| `Redirect Trap - Store/AMO access fault` | 存储访问错误陷阱重定向 |
| `Redirect Trap - Environment call from U-mode` | U 模式环境调用重定向 |
| `Redirect Trap - Environment call from S-mode` | S 模式环境调用重定向 |
| `Redirect Trap - Instruction page fault` | 指令页故障重定向 |
| `Redirect Trap - Load page fault` | 加载页故障重定向 |
| `Redirect Trap - Store/AMO page fault` | 存储页故障重定向 |
| `Skip Generation - Vector AMO` | 向量 AMO 跳过生成 |
| `Reset vstart` | 异常后 vstart 重置 |

### 7.6 variables_rv64.xml — 完整变量列表

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `Inter-Dependency Window` | Choice | `1-20:90,21-30:10` | 指令间依赖窗口 |
| `Source Entropy Window` | String | `15-3` | 源熵窗口 |
| `Target Entropy Window` | String | `9-2` | 目标熵窗口 |
| `Debug Single-Step Step-Factor` | Value | `5` | 单步调试因子 |
| `Register Fields Ignored update` | String | `""` | 忽略更新的寄存器字段 |
| `Ret Preamble Sequence Class` | String | `""` | RET 前导序列类 |
| `Unpredictable Registers` | String | `mepc` | 不可预测寄存器 |
| `System Physical Address Range` | String | `0x0-0xffffffffff` | 系统物理地址范围 |
| `Streaming address error` | Value | `1` | 流式地址错误使能 |
| `Branch address error` | Value | `0` | 分支地址错误使能 |
| `Enable register reloading` | Value | `1` | 寄存器重载使能 |
| `Reloading registers number` | String | `20-15` | 重载寄存器数量范围 |
| `Address table memory size` | Value | `0x1000` | 地址表内存大小 |
| `Address table memory address range` | String | `0x0-0xffffffffff` | 地址表地址范围 |
| `Default page table physical memory range` | String | `0x0-0x800000000000` | 默认页表物理内存范围 |
| `Page tables number per block allocating` | Value | `0x200` | 每块分配的页表数 |
| `No data page fault allowed` | Value | `0` | 禁止数据页故障 |
| `No instruction page fault allowed` | Value | `0` | 禁止指令页故障 |
| `Semaphore Physical Address Range` | String | `0x0-0xffffffffff` | 信号量地址范围 |
| `Initial Vector Strided Preamble Address Block Size` | Value | `0x8000` | 向量跨步前导块大小 |
| `Exception Stack Address Range` | String | `0x0-0xffffffffff` | 异常栈地址范围 |

### 7.7 测试选项参考

通过 `--options` 或控制文件 `generator` 传递的选项：

| 选项 | 值 | 说明 |
|------|-----|------|
| `PrivilegeLevel` | 0, 1, 2 | 0=M, 1=S, 2=U |
| `FlatMap` | 0, 1 | 1=平坦映射（不分页） |
| `handlers_set` | "Fast", "Comprehensive" | 异常处理器类型 |
| `MMU` | 0, 1 | 是否启用 MMU |
| `NoHandler` | 0, 1 | 是否安装异常处理器 |
| `NoSkip` | 0, 1 | 不允许跳过 |
| `DelegateExceptions` | 0, 1 | 是否启用异常委托 |
| `enable_paging` | 0, 1 | 是否启用分页 |

### 7.8 rv64.config 指令定义文件

| 文件路径 | 说明 |
|---------|------|
| `riscv/arch_data/instr/g_instructions.xml` | RV64G 基础指令 |
| `riscv/arch_data/instr/g_instructions_rv64.xml` | RV64 特有指令 |
| `riscv/arch_data/instr/c_instructions.xml` | 压缩指令（C 扩展） |
| `riscv/arch_data/instr/c_instructions_rv64.xml` | RV64 压缩指令 |
| `riscv/arch_data/instr/v_instructions.xml` | 向量指令（V 扩展） |
| `riscv/arch_data/instr/priv_instructions.xml` | 特权指令 |
| `riscv/arch_data/instr/zfh_instructions.xml` | 半精度浮点指令 |
| `riscv/arch_data/instr/zfh_instructions_rv64.xml` | RV64 Zfh 扩展 |

### 7.9 配置对比

| 特性 | rv64 | rv32 | rv64_sv39 | rv64_twostage |
|------|------|------|-----------|---------------|
| 基础 ISA | RV64 | RV32 | RV64 | RV64 |
| V 扩展 | ✅ | ✅ | ✅ | ❌ |
| H 扩展 | ✅ | ❌ | ❌ | ✅ |
| Zfh 扩展 | ✅ | ✅ | ✅ | ✅ |
| 分页模式 | Sv48 | Sv32 | Sv39 | Sv39+Sv39x4 |
| 两阶翻译 | ❌ | ❌ | ❌ | ✅ |

---

## 8. 回归测试框架

### 8.1 框架组件

| 组件 | 脚本 | 说明 |
|------|------|------|
| 主回归运行器 | `utils/regression/master_run.py` | 解析控制文件，调度测试任务 |
| 任务执行器 | `utils/regression/forrest_run.py` | 执行单个测试（被 master_run 调用） |
| 单元测试运行器 | `utils/regression/unit_tests.py` | 编译并运行 C++ 单元测试 |

### 8.2 master_run.py 命令行参数大全

#### 通用选项

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `-f, --control-name=` | `_def_fctrl.py` | 控制文件路径或文件名 |
| `-d, --control-dir=` | `<test-base>/tests` | 控制文件目录 |
| `-c, --config=` | `_riscv_rv64_fcfg.py` | 配置文件路径 |
| `-r, --num-runs=` | 1 | 重复运行次数 |
| `-z, --seed=` | None | 全局随机种子 |
| `--no-archive` | False | 移除之前的输出目录 |

#### 持久化选项（不可在控制文件中覆盖）

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `-o, --test-base=` | `../../tests` | 测试根目录 |
| `-s, --run-dir=` | `.` | 客户端应用程序目录 |
| `-n, --run-name=` | `forrest_run.py` | 客户端应用程序名称 |
| `-j, --run-launcher=` | `local` | 启动方式（lsf/local） |
| `-x, --process-max=` | 16 | 最大并发进程数 |
| `--target-dir=` | `<cwd>/output` | 输出基础目录 |
| `--sum-level=` | 1 | 汇总级别（0=静默, 1=失败, 2=全部失败, 3=全部） |
| `-m, --mode=` | `regress` | 模式：mock/regress/perf/count |

#### 持久化选项（可在控制文件中覆盖）

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `-t, --timeout=` | 600 | 任务超时秒数 |
| `--num-chips=` | 1 | 芯片数（1-32） |
| `--num-cores=` | 1 | 核心数（1-4） |
| `--num-threads=` | 1 | 线程数（1-4） |
| `--max-instr=` | 10000 | 最大指令数 |
| `--min-instr=` | 1 | 最小指令数 |
| `--no-sim` | False | 不运行模拟器 |
| `--max-fails=` | 10 | 最大失败次数后停止 |
| `-k, --keep=` | `""` | 保留输出文件（"all"=全部保留） |

#### 非持久化选项

| 选项 | 说明 |
|------|------|
| `--iss=` | ISS 选项字典（如 `--iss={"path":"bla/bla"}`） |
| `--generator=` | 生成器选项字典（如 `--generator={"--options":"MMU=1"}`） |

#### 其他选项

| 选项 | 说明 |
|------|------|
| `-e, --expire=` | 输出保留天数 |
| `-l, --msg-lev=` | 消息级别（crit/err/warn/info/dbg/user/trace/all/nomsg） |
| `--client-lev=` | 客户端日志级别 |

### 8.3 运行回归测试

```bash
source setenv.bash

# 运行全部 RV64 测试
./utils/regression/master_run.py \
    -f tests/riscv/_def_fctrl.py \
    -c utils/regression/config/_riscv_rv64_fcfg.py -k all

# 运行全部 RV32 测试
./utils/regression/master_run.py \
    -f tests/riscv/_rv32_fctrl.py \
    -c utils/regression/config/_riscv_rv32_fcfg.py -k all

# 运行示例测试
./utils/regression/master_run.py \
    -f examples/riscv/_def_fctrl.py \
    -c utils/regression/config/_riscv_rv64_fcfg.py -k all

# 仅计数不执行
./utils/regression/master_run.py -f examples/riscv/_def_fctrl.py -m count

# 限制并发进程数
./utils/regression/master_run.py -f examples/riscv/_def_fctrl.py -x 4

# 指定全局种子
./utils/regression/master_run.py -f examples/riscv/_def_fctrl.py -z 0x12345678

# 不运行模拟器
./utils/regression/master_run.py -f examples/riscv/_def_fctrl.py --no-sim
```

### 8.4 控制文件完整语法

```python
control_items = [
    {
        "fname": "test_template_force.py",   # 模板文件名（必需）
        "options": {                           # 选项
            "max-instr": 50000,                # 最大指令数
            "min-instr": 100,                  # 最小指令数
            "iterations": 3,                   # 迭代次数
            "num-cores": 4,                    # 核心数
            "num-threads": 1,                  # 线程数
            "num-chips": 1,                    # 芯片数
            "no-sim": False,                   # 不模拟
            "seed": "0x123",                   # 种子
            "suffix": "_v1",                   # 文件名后缀
            "timeout": 600,                    # 超时秒数
            "group": "smoke",                  # 分组名称
            "control-dir": ".",                # 控制文件目录
        },
        "generator": {                         # 传递给 friscv 的选项
            "--cfg": "config/riscv_rv64.config",
            "--options": '"PrivilegeLevel=1"',
            "--seed": "0x456",
        },
    },
    # 通配符匹配所有模板
    {"fname": "*_force.py"},
]
```

#### options 键完整列表

| 键 | 类型 | 默认值 | 说明 |
|----|------|--------|------|
| `group` | str | `"default"` | 分组名称 |
| `iterations` | int | 1 | 测试迭代次数 |
| `min-instr` | int | 1 | 最小通过指令数 |
| `max-instr` | int | 10000 | 最大指令数 |
| `num-chips` | int | 1 | 芯片数（1-32） |
| `num-cores` | int | 1 | 核心数（1-4） |
| `num-threads` | int | 1 | 线程数（1-4） |
| `no-sim` | bool | False | 不运行模拟 |
| `seed` | str/None | None | 随机种子 |
| `suffix` | str/None | None | 输出文件后缀 |
| `timeout` | int | 600 | 超时秒数 |
| `control-dir` | str | `"."` | 控制文件目录 |

#### generator 键说明

generator 字典的键值对直接作为命令行参数传递给 friscv：

```python
"generator": {
    "--cfg": "config/riscv_rv64.config",   # 必需
    "--options": '"MMU=1 PrivilegeLevel=1"',
    "--seed": "0x123",
    "--max-instr": "50000",
}
```

### 8.5 控制文件示例（examples/riscv/_def_fctrl.py）

```python
control_items = [
    {
        "fname": "basic_random_01_force.py",
        "options": {"max-instr": 50000, "iterations": 1},
        "generator": {
            "--cfg": "config/riscv_rv64.config",
            "--options": '"MMU=1"',
        },
    },
    {"fname": "*_force.py"},  # 通配符
]
```

### 8.6 输出目录结构

```
output/regression/
  <template_name>/
    00000/                           # 迭代索引
      <template>.Default.ELF         # 生成的 ELF
      <template>.Default.S           # 反汇编
      gen.log                        # 生成日志
      sim.log                        # 生成阶段 ISS 日志
      fpix_sim.log                   # ISS 执行日志（后生成）
    regression_summary.log           # 汇总报告
```

### 8.7 消息级别参考

| 级别 | 值 | 说明 |
|------|-----|------|
| `crit` | 0x0001 | 关键错误消息 |
| `err` | 0x0002 | 非关键错误消息 |
| `warn` | 0x0004 | 警告消息 |
| `info` | 0x0008 | 运行信息消息 |
| `noinfo` | 0x0080 | 抑制 info 标签 |
| `dbg` | 0x0010 | 调试信息 |
| `user` | 0x0020 | 特殊消息 |
| `trace` | 0x0040 | 调用栈跟踪 |
| `all` | 0xFFFF | 全部消息 |
| `nomsg` | 0x0000 | 仅系统消息 |

使用示例：`-l +dbg-warn` 开启调试并关闭警告。

### 8.8 C++ 单元测试

```bash
# 构建测试二进制
make tests

# 运行全部单元测试
./utils/regression/unit_tests.py

# 带清理和失败输出
./utils/regression/unit_tests.py --clean --print-failures
```

---

## 9. 已知问题与限制

### 9.1 配置问题

| 问题 | 说明 | 规避方法 |
|------|------|----------|
| RV32 配置失败 | `cycleh` 寄存器不存在（handcar 构建为 RV64） | 使用 RV64 配置 |
| Sv39 配置失败 | 缺少 H-extension 分页 choices 树 | 使用默认 rv64 或 twostage 配置 |
| CVA6 配置损坏 | 引用不存在的旧路径 | 不使用该配置 |

### 9.2 构建问题

| 问题 | 说明 | 规避方法 |
|------|------|----------|
| seedgen 构建失败 | 缺少 `Python.h` | 安装 Python 开发包：`apt install python3-dev` |
| handcar_cosim.so 预编译 | 仓库中包含预编译的 .so | 正常无需重建 |

### 9.3 功能限制

| 限制 | 说明 |
|------|------|
| H-extension 不完整 | 两阶翻译链路有 7 个 CRITICAL 级缺口 |
| PMP 未实现 | 物理内存保护功能未实现 |
| 中断寄存器未实现 | mip/mie/sip/sie 等未实现 |
| Sv57 未定义 | 无 Sv57 分页支持 |
| SUM/MXR/MPRV | SystemCallSequence 中的这些字段当前不支持 |
| Fast exception handlers | 与 SystemCallSequence 不兼容 |
| 无 URET | URET 指令在 Trap_Return 中有定义但未完全验证 |
| V 扩展不完整 | 向量指令树标记为 "pending" |
| 所有日志 API 已弃用 | 推荐使用 `Log.notice()` 等替代 `Sequence` 的方法 |

### 9.4 文档状态

| 文档 | 位置 |
|------|------|
| 用户手册 v2.0 | `doc/USER_MANUAL.md`（本文档） |
| 新指令添加教程 | `doc/force_new_instr_tutorial.pdf` |
| 陷阱委托与重定向 | `doc/Traps_Delegation_Redirection.pdf` |
| H-extension 差距分析 | `H_EXTENSION_VIRTUALIZATION_GAP_ANALYSIS.md` |
| 两阶翻译测试报告 | `TWO_STAGE_TEST_REPORT.md` |
| 性能分析报告 | `docs/performance_bottleneck_analysis.md` |

---

## 10. 附录

### 10.1 指令名称格式

```python
"ADD##RISCV"                 # 基本格式
"SRLI#RV64I#RISCV"           # 带变体（RV64 专用）
"SRLI#RV32I#RISCV"           # 带变体（RV32 专用）
"CSRRW#register#RISCV"       # CSR 寄存器形式
"FADD.H#Half-precision#RISCV" # 半精度浮点变体
```

### 10.2 完整指令树变量列表

来源：`py/DV/riscv/trees/instruction_tree.py`

#### 基础指令树

| 变量名 | 说明 | 指令数 |
|--------|------|--------|
| `RV32I_instructions` | RV32I 基础整数指令 | 41 |
| `RV64I_instructions` | RV64I 附加指令 | 15 |
| `RV32F_instructions` | 单精度浮点（RV32F） | 27 |
| `RV64F_instructions` | RV64 单精度浮点扩展 | 4 |
| `RV32D_instructions` | 双精度浮点（RV32D） | 26 |
| `RV64D_instructions` | RV64 双精度浮点扩展 | 6 |
| `ZFH32_instructions` | 半精度浮点（Zfh） | 33 |
| `ZFH64_instructions` | RV64 半精度浮点扩展 | 4 |
| `ZFH_instructions` | 全部半精度浮点 | 37 |
| `RV32M_instructions` | 整数乘除法（RV32M） | 8 |
| `RV64M_instructions` | RV64 乘除法扩展 | 5 |
| `ALU_M_instructions` | 全部乘除法指令 | 13 |
| `RV32A_instructions` | 原子操作（RV32A） | 11 |
| `RV64A_instructions` | RV64 原子操作 | 11 |
| `RV_A_instructions` | 全部原子操作 | 22 |
| `Zicsr_instructions` | CSR 指令 | 6 |
| `Zifencei_instructions` | FENCE.I 指令 | 1 |
| **`RV_G_instructions`** | **RV64G 全部指令** | **136** |
| **`RV32_G_instructions`** | **RV32G 全部指令** | **113** |

#### Load/Store 指令树

| 变量名 | 说明 |
|--------|------|
| `LD_Int_instructions` | 整数 Load（6 条） |
| `LD_Int32_instructions` | RV32 整数 Load（5 条） |
| `ST_Int_instructions` | 整数 Store（4 条） |
| `ST_Int32_instructions` | RV32 整数 Store（3 条） |
| `LD_Float_instructions` | 浮点 Load（2 条） |
| `ST_Float_instructions` | 浮点 Store（2 条） |
| `LDST_Int_instructions` | 整数 Load+Store |
| `LDST_Int32_instructions` | RV32 整数 Load+Store |
| `LDST_Float_instructions` | 浮点 Load+Store |
| `LDST_IntFloat_instructions` | 全部非向量 Load+Store |
| `LDST_Byte_instructions` | 字节 Load/Store |
| `LDST_Half_instructions` | 半字 Load/Store |
| `LDST_Word_instructions` | 字 Load/Store（含压缩） |
| `LDST_Double_instructions` | 双字 Load/Store（含压缩） |
| `LDST_C_instructions` | 压缩 Load/Store |
| `LDST_IFC_instructions` | 全部非向量（含压缩） |
| **`LDST_All_instructions`** | **全部 Load/Store** |

#### ALU 指令树

| 变量名 | 说明 |
|--------|------|
| `ALU_Int32_instructions` | RV32I 整数 ALU |
| `ALU_Int64_instructions` | RV64I 整数 ALU |
| **`ALU_Int_All_instructions`** | **全部整数 ALU（含乘除/压缩）** |
| `ALU_Int32_All_instructions` | RV32 全部整数 ALU |
| `ALU_Float_Single_instructions` | 单精度浮点 ALU |
| `ALU_Float_Double_instructions` | 双精度浮点 ALU |
| `ALU_Float_All_instructions` | 全部浮点 ALU |
| `FCVT_instructions` | 浮点格式转换 |

#### 分支跳转指令树

| 变量名 | 说明 |
|--------|------|
| `BranchJump_instructions` | 分支跳转指令（8 条） |
| `BranchJump_C_instructions` | 压缩分支跳转（5 条） |

#### 压缩指令（C 扩展）

| 变量名 | 说明 |
|--------|------|
| `ALU_Int_C_instructions` | 压缩整数 ALU（20 条） |
| `ALU_Int32_C_instructions` | RV32 压缩整数 ALU（15 条） |
| `RV_C_instructions` | 全部压缩指令 |

#### 特殊指令树

| 变量名 | 说明 |
|--------|------|
| `Trap_Return_instructions` | 陷阱返回（MRET, SRET） |
| `HLV_instructions` | Hypervisor Load |
| `HSV_instructions` | Hypervisor Store |
| `HFENCE_instructions` | Hypervisor FENCE |
| `Hypervisor_instructions` | 全部 H 扩展指令 |
| **`RV_ALL_NoVector_instructions`** | **全部非向量 RISC-V 指令** |

#### InstructionMap 对象

每个 `*_instructions` 字典都有对应的 `*_map` InstructionMap 对象，
支持 `.pick(gen_thread)` 方法进行加权随机选择。

### 10.3 常用 API 速查表

| 功能 | API |
|------|-----|
| 生成指令 | `self.genInstruction("ADD##RISCV")` |
| 随机选指令 | `self.pickWeighted(instructions_dict)` |
| 获取 GPR | `self.getRandomGPR(exclude="0")` |
| 读寄存器 | `(val, valid) = self.readRegister("mscratch")` |
| 写寄存器 | `self.writeRegister("x5", 0x100)` |
| 初始化内存 | `self.initializeMemory(addr, 0, size, data, False, False)` |
| 生成虚拟地址 | `self.genVA(Size=8, Align=8, Type="D")` |
| 生成物理地址 | `self.genPA(Size=8, Align=8, Type="D")` |
| 获取全局状态 | `self.getGlobalState("AppRegisterWidth")` |
| 获取 PE 状态 | `self.getPEstate("PC")` |
| 修改 choices | `ChoicesModifier().modifyOperandChoices(...)` |
| 生成循环 | `LoopControl().start(reg, 10)` / `.end()` |
| 加载立即数 | `LoadGPR64().load(reg, 0xDEADBEAF)` |
| 汇编辅助 | `AssemblyHelperRISCV(self).genAddImmediate(d, 100)` |
| 特权切换 | `self.systemCall({"Function":"SwitchPrivilegeLevel",...})` |
| 查询指令 | `self.queryInstructionRecord(rec_id)` |
| 日志 | `import Log; Log.notice("msg")` |
| 错误 | `self.error("fatal error")` |

### 10.4 文件命名约定

| 后缀 | 说明 |
|------|------|
| `*_force.py` | 测试模板 |
| `*_fctrl.py` | 回归控制文件 |
| `*_fcfg.py` | 回归配置文件 |
| `*_frun.py` | 运行控制文件 |
| `*.Default.ELF` | 生成的 ELF 文件 |
| `*.Default.S` | 生成的反汇编文件 |

### 10.5 相关文档

| 文档 | 位置 |
|------|------|
| 用户手册 v2.0 | `doc/USER_MANUAL.md` |
| 用户手册 v0.8（旧版） | `doc/FORCE-RISCV_User_Manual-v0.8.pdf` |
| 新指令添加教程 | `doc/force_new_instr_tutorial.pdf` |
| 陷阱委托与重定向 | `doc/Traps_Delegation_Redirection.pdf` |
| H-extension 差距分析 | `H_EXTENSION_VIRTUALIZATION_GAP_ANALYSIS.md` |
| 两阶翻译测试报告 | `TWO_STAGE_TEST_REPORT.md` |
| 性能分析报告 | `docs/performance_bottleneck_analysis.md` |

### 10.6 索引

| 主题 | 章节 |
|------|------|
| API 参考 | 第 6 章 |
| 构建指南 | 第 3 章 |
| 配置系统 | 第 7 章 |
| 回归测试 | 第 8 章 |
| 测试模板 | 第 5 章 |
| 快速入门 | 第 4 章 |
| 已知问题 | 第 9 章 |
| 指令树 | 附录 10.2 |
| Choices 名称 | 第 7.4-7.5 节 |
| 命令行参数 | 第 3.4 节, 第 8.2 节 |
| 序列库 | 第 5.4.4 节 |
| 多线程 | 第 5.15 节 |
| 异常处理 | 第 5.13 节 |
| 两阶分页 | 第 5.17 节 |
