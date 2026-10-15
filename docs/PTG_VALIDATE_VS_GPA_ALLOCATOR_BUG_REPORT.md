# PTG Bug Report: `ptg_validate()` 使用错误的 allocator 校验 VS-stage 节点

**报告日期**: 2026-08-01
**状态**: Fixed and verified
**严重程度**: Medium
**PTG 版本**: `407dfecb3f35c31bc4b876fdd7bcc8a2d11898a8`
**报告方**: FORCE-RISCV Hypervisor/PTG integration

## Bug Summary

当两阶段 context 的 GPA 和 PA 区间不重叠时，`ptg_validate()` 会把所有合法的
VS-stage 页表节点报告为 `invalid_addr_nodes`，并错误地返回 `all_ok=0`。

实际两阶段翻译可以成功，其他 validation 指标也全部为 0。该问题仅影响 validation
结果，但会导致调用方 CI、生成测试和健康检查误判合法 context 为无效。

## Minimal Reproduction

以下用例只使用 PTG 原生 C API，不依赖 FORCE、Python wrapper 或 ISS：

```cpp
#include <cstdio>

#include "ptg/ptg.h"

int main() {
    void* handle = ptg_create();
    ptg_register_pa_region(handle, 0xA0000000, 0xB0000000);
    ptg_register_gpa_region(handle, 1, 0x80000000, 0x90000000);

    uint32_t ctx = ptg_context_create(handle, 1, 1);
    ptg_context_vs_stage(handle, ctx, 8);  // Sv39
    ptg_context_gs_stage(handle, ctx, 8);  // Sv39x4
    ptg_context_set_vm_config(handle, ctx, 1, 1, 1, 0, 0);
    ptg_context_set_gs_vm_config(handle, ctx, 1, 1, 1, 1, 0);

    ptg_add_mapping(handle, ctx, 1, 0x80200000, 0x80200000,
                    0x200000, 0, 0x7F);
    ptg_add_mapping(handle, ctx, 2, 0x80200000, 0xA0200000,
                    0x200000, 0, 0x7F);

    PtgValidateResult result = ptg_validate(handle, ctx);
    char report[256] = {};
    ptg_validate_report(handle, ctx, report, sizeof(report));
    std::printf("%s\n", report);
    std::printf("invalid_addr_nodes=%u all_ok=%u\n",
                result.invalid_addr_nodes, result.all_ok);

    uint8_t fault = 0xFF;
    uint64_t spa = ptg_translate(handle, ctx, 0x80200000, 0, &fault);
    std::printf("translate: spa=0x%llx fault=%u\n",
                static_cast<unsigned long long>(spa), fault);

    ptg_destroy(handle);
    return 0;
}
```

构建和运行：

```bash
g++ -std=c++17 -Wall -Wextra -I include \
    ptg_validate_vs_allocator_repro.cpp build/libptg.a \
    -o build/ptg_validate_vs_allocator_repro
build/ptg_validate_vs_allocator_repro
```

## Expected Behavior

VS-stage 页表节点由该 VMID 的 GPA allocator 分配，且全部位于已注册区间
`[0x80000000, 0x90000000)`，因此预期：

```text
invalid_addr_nodes=0 all_ok=1
translate: spa=0xa0200000 fault=0
```

## Actual Behavior

```text
nodes=7 ptes=5120 valid=10 leaf=5 nonleaf=5 orphans=0 \
invalid_addr=3 invalid_pte=0 missing_flags=0 \
gpa_unreachable=0 gpa_overlap=0 all_ok=0
invalid_addr_nodes=3 all_ok=0
translate: spa=0xa0200000 fault=0
```

关键事实：

- 两阶段翻译成功，返回正确 SPA `0xA0200000`，`fault=0`。
- `invalid_pte_count=0`。
- `orphan_nodes=0`。
- `gpa_unreachable=0`。
- `gpa_overlap_count=0`。
- `leaf_missing_flags=0`。
- 唯一失败项是 3 个 VS-stage 节点被误报为地址非法。

## Root Cause

`src/api/ptg_api.cpp` 的 `ptg_validate()` 获取了全局 PA allocator，并使用它校验
S、VS、G 三棵树：

```cpp
auto& pa_alloc = handle->ctx_mgr.pa_allocator();
if (ctx->s_stage())  check_tree(ctx->s_stage(), pa_alloc);
if (ctx->vs_stage()) check_tree(ctx->vs_stage(), pa_alloc);  // wrong allocator
if (ctx->gs_stage()) check_tree(ctx->gs_stage(), pa_alloc);
```

但 VS-stage 节点不是从 PA allocator 分配的。`ContextManager::create_vs_stage()` 明确
使用当前 VMID 对应的 `GStageContext::gpa_allocator()`：

```cpp
auto* gsc = get_g_stage(ctx->vmid());
uint64_t root_gpa = gsc->gpa_allocator().allocate_node(...);

auto* tree = new PageTableTree(mode, false, true);
tree->set_allocator(&gsc->gpa_allocator());
```

因此，只要 GPA 和 PA 注册区间不重叠，所有 VS-stage 节点都会被 PA allocator 拒绝。
本用例有 3 个 VS-stage 节点，所以 `invalid_addr_nodes=3`。

## Existing Test Gap

当前 `make verify` 结果为：

```text
2092 passed, 0 failed
```

`tests/verify.cpp` 的 `test_two_stage_c_api_auto_gstage_verify()` 只断言：

```cpp
CHECK(vr.gpa_unreachable == 0, "auto G-stage: all VS nodes reachable");
// 注意：不检查 all_ok
```

因此该回归未覆盖 VS-stage allocator 合法性，也不会发现 `all_ok=0`。

## Suggested Fix

S-stage 和 G-stage 节点继续使用 PA allocator；VS-stage 节点应使用当前 VMID 的
GPA allocator。例如：

```cpp
auto& pa_alloc = handle->ctx_mgr.pa_allocator();
if (ctx->s_stage()) check_tree(ctx->s_stage(), pa_alloc);

if (ctx->vs_stage()) {
    auto* gsc = handle->ctx_mgr.get_g_stage(ctx->vmid());
    if (gsc) {
        check_tree(ctx->vs_stage(), gsc->gpa_allocator());
    }
}

if (ctx->gs_stage()) check_tree(ctx->gs_stage(), pa_alloc);
```

如果维护方希望避免 validation 层重新查找 allocator，也可以给
`PageTableTree` 增加只读 allocator 访问接口，并使用树实际绑定的 allocator 校验。

## Acceptance Criteria

1. 使用互不重叠的 GPA/PA 区间运行上述原生 C API 用例。
2. `ptg_translate()` 继续返回 `SPA=0xA0200000, fault=0`。
3. `ptg_validate()` 返回 `invalid_addr_nodes=0`。
4. `ptg_validate()` 返回 `all_ok=1`。
5. 在 `tests/verify.cpp` 增加两阶段回归，明确断言以上结果。
6. `make verify` 全部通过。

## FORCE-RISCV Impact

FORCE 的 PTG 两阶段端到端测试已经成功执行：

```text
GVA 0x80200000 -> GPA 0x80200000 -> SPA 0xA0200000
x2 = 0xDEADBEEFCAFE1234
Mem R VA 0x80200000 PA 0xA0200000
```

修复前，FORCE 不能把 `PtgValidateResult.all_ok` 作为强门槛，只能单独检查其余可靠字段
并记录 `invalid_addr_nodes` 假阳性；维护方修复后已恢复对 `all_ok` 的直接断言。

## Reporter Verification

**验证日期**: 2026-08-02
**维护方回复**: `PTG_VALIDATE_VS_GPA_ALLOCATOR_BUG_REPLY.md`

维护方修复已通过报告方复测：

```text
PTG make verify:       2096 passed, 0 failed
NodeRegistry:            39 passed, 0 failed
Native reproduction: invalid_addr_nodes=0, all_ok=1
Native translation:  SPA=0xA0200000, fault=0
FORCE HLV.D result:   x2=0xDEADBEEFCAFE1234
Handcar callback:     VA=0x80200000, PA=0xA0200000
FORCE smoke:          3 instructions, SUCCESS
```

FORCE 侧已删除 `invalid_addr_nodes` 假阳性豁免，并恢复直接断言
`PtgValidateResult.all_ok == 1`。当前验证针对 PTG 基线 `407dfec` 上的维护方工作树修复；
维护方尚未提供单独的修复 commit ID。
