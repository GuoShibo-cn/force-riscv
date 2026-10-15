// Historical reproducer using PTG private C++ interfaces. See the versioned
// PTG_FAULT_INJECTION_V2_*_ACCEPTANCE_FEEDBACK.md reports, not current CI coverage.
#include "src/core/context_manager.h"
#include "src/fault/fault_engine.h"

#include <cstdio>

using namespace ptg;

static MappingEntry mapping(uint64_t va, uint64_t pa, bool user = false) {
    MappingEntry entry;
    entry.va = va;
    entry.pa = pa;
    entry.size = 0x1000;
    entry.leaf_level = 0;
    entry.perm_r = true;
    entry.perm_w = true;
    entry.perm_x = true;
    entry.perm_u = user;
    entry.flag_a = true;
    entry.flag_d = true;
    return entry;
}

static bool actual_cause_repro() {
    PageTableAllocator allocator;
    allocator.register_region(0x10000000, 0x11000000);
    PageTableTree tree(SvMode::Sv39);
    tree.set_allocator(&allocator);
    tree.set_root_ppn(allocator.allocate_node(2, true, false) >> 12);
    tree.add_mapping(mapping(0x1000, 0x80001000, true));

    FaultExecutionInput input;
    input.tree = &tree;
    input.result_capacity = 1;
    input.request.stage = FaultStage::S;
    input.request.scope = FaultScope::Direct;
    input.request.address_kind = FaultAddressKind::StageNative;
    input.request.selection_mode = FaultSelectionMode::ExactOne;
    input.request.cause = FaultCause::NonLeafTerminal;
    input.request.access = FaultAccess::Read;
    input.request.privilege = FaultPrivilege::U;
    input.request.verification = FaultVerification::RequireFault;
    input.request.target_level = 2;
    input.request.has_target_address = true;
    input.request.target_address = 0x1000;
    input.context.stage_levels = tree.levels();

    const auto result = FaultEngine::execute(input);
    WalkOptions options;
    options.update_ad = false;
    options.privilege = WalkPrivilege::User;
    const auto observed = tree.walk_with_config(0x1000, AccessType::Read, VMConfig{}, options);
    const int reported = result.records.empty()
        ? -1 : static_cast<int>(result.records[0].actual_cause);
    std::printf("ACTUAL_CAUSE status=%d reported=%d observed=%d fault=%d\n",
                static_cast<int>(result.status), reported,
                static_cast<int>(observed.fault_cause), static_cast<int>(observed.fault));
    return result.status == FaultStatus::Ok &&
           reported == static_cast<int>(FaultCause::NonLeafTerminal) &&
           observed.fault_cause != FaultCause::NonLeafTerminal;
}

static bool precedence_repro() {
    ContextManager manager;
    manager.pa_allocator().register_region(0x80000000, 0x90000000);
    auto* context = manager.create_context(1, 7);
    auto* gstage = manager.register_g_stage(7, SvMode::Sv39);
    gstage->gpa_allocator().register_region(0x20000000, 0x20100000);
    manager.create_vs_stage(context->id(), SvMode::Sv39);
    manager.create_gs_stage(context->id(), SvMode::Sv39);
    context->vs_stage()->add_mapping(mapping(0x1000, 0x28000000));
    for (const auto* node : context->vs_stage()->nodes()) {
        context->gs_stage()->add_mapping(
            mapping(node->base_addr(),
                    0x81000000 + node->base_addr() - 0x20000000, true));
    }
    context->gs_stage()->add_mapping(mapping(0x28000000, 0x88000000, true));

    const auto vs_root = context->vs_stage()->resolve_pte_on_walk(0x1000, 2);
    const auto vs_leaf = context->vs_stage()->resolve_pte_on_walk(0x1000, 0);
    const auto g_for_root = context->gs_stage()->resolve_pte_on_walk(vs_root.pte_pa, 0);
    context->gs_stage()->write_pte_synced(
        g_for_root.node, g_for_root.index, g_for_root.pte & ~PTE_V);
    context->vs_stage()->write_pte_synced(
        vs_leaf.node, vs_leaf.index, vs_leaf.pte & ~PTE_V);

    WalkOptions options;
    options.update_ad = false;
    options.privilege = WalkPrivilege::VirtualSupervisor;
    const auto result = context->translate_detailed(0x1000, AccessType::Read, options);
    std::printf("PRECEDENCE fault=%d cause=%d scope=%d failing=0x%llx root_pte_gpa=0x%llx\n",
                static_cast<int>(result.fault), static_cast<int>(result.fault_cause),
                static_cast<int>(result.fault_scope),
                static_cast<unsigned long long>(result.failing_address),
                static_cast<unsigned long long>(vs_root.pte_pa));
    return result.fault == FaultType::LoadPageFault &&
           result.fault_scope == WalkFaultScope::Direct;
}

static bool noncanonical_repro() {
    PageTableAllocator allocator;
    allocator.register_region(0x10000000, 0x11000000);
    PageTableTree tree(SvMode::Sv39);
    tree.set_allocator(&allocator);
    tree.set_root_ppn(allocator.allocate_node(2, true, false) >> 12);
    tree.add_mapping(mapping(0x1000, 0x80001000));
    const uint64_t bad = (1ULL << 39) | 0x1000;
    const auto canonical = tree.resolve_pte_on_walk(0x1000, 0);
    const auto aliased = tree.resolve_pte_on_walk(bad, 0);
    std::printf("NONCANONICAL status=%d canonical_pte=0x%llx aliased_pte=0x%llx\n",
                static_cast<int>(aliased.status),
                static_cast<unsigned long long>(canonical.pte_pa),
                static_cast<unsigned long long>(aliased.pte_pa));
    return aliased.status == PteResolveStatus::Found &&
           aliased.pte_pa == canonical.pte_pa;
}

static bool dry_run_callback_repro() {
    PageTableAllocator allocator;
    allocator.register_region(0x10000000, 0x11000000);
    PageTableTree tree(SvMode::Sv39);
    tree.set_allocator(&allocator);
    tree.set_root_ppn(allocator.allocate_node(2, true, false) >> 12);
    tree.add_mapping(mapping(0x1000, 0x80001000));
    MemoryModel model;
    tree.set_memory_model(&model);
    tree.sync_to_model();
    unsigned callbacks = 0;
    model.on_pte_write([&](uint64_t, uint64_t, size_t) { ++callbacks; });

    FaultExecutionInput input;
    input.tree = &tree;
    input.result_capacity = 1;
    input.request.stage = FaultStage::S;
    input.request.scope = FaultScope::Direct;
    input.request.address_kind = FaultAddressKind::StageNative;
    input.request.selection_mode = FaultSelectionMode::ExactOne;
    input.request.cause = FaultCause::InvalidPTE;
    input.request.access = FaultAccess::Read;
    input.request.privilege = FaultPrivilege::S;
    input.request.verification = FaultVerification::RequireFault;
    input.request.target_level = 0;
    input.request.has_target_address = true;
    input.request.target_address = 0x1000;
    input.request.dry_run = true;
    input.context.stage_levels = tree.levels();
    const auto result = FaultEngine::execute(input);
    std::printf("DRY_CALLBACK status=%d callbacks=%u\n",
                static_cast<int>(result.status), callbacks);
    return result.status == FaultStatus::Ok && callbacks == 2;
}

static bool sv32_high_address_regression() {
    PageTableAllocator allocator;
    allocator.register_region(0x10000000, 0x11000000);
    PageTableTree tree(SvMode::Sv32);
    tree.set_allocator(&allocator);
    tree.set_root_ppn(allocator.allocate_node(1, true, false) >> 12);
    const bool added = tree.add_mapping(mapping(0x80000000, 0x20000000));
    const auto resolved = tree.resolve_pte_on_walk(0x80000000, 0);
    const auto walked = tree.walk(0x80000000, AccessType::Read);
    std::printf("SV32_HIGH added=%d resolved=%d hit=%d fault=%d\n",
                added, static_cast<int>(resolved.status), walked.hit,
                static_cast<int>(walked.fault));
    return !added && resolved.status != PteResolveStatus::Found && !walked.hit;
}

static bool sv32_invalid_sign_extension_alias() {
    PageTableAllocator allocator;
    allocator.register_region(0x10000000, 0x11000000);
    PageTableTree tree(SvMode::Sv32);
    tree.set_allocator(&allocator);
    tree.set_root_ppn(allocator.allocate_node(1, true, false) >> 12);
    const bool added = tree.add_mapping(mapping(0x1000, 0x20000000));
    const uint64_t malformed = 0xFFFFFFFF00001000ULL;
    const auto canonical = tree.resolve_pte_on_walk(0x1000, 0);
    const auto aliased = tree.resolve_pte_on_walk(malformed, 0);
    const auto walked = tree.walk(malformed, AccessType::Read);
    std::printf("SV32_BAD_SIGN added=%d status=%d canonical_pte=0x%llx "
                "aliased_pte=0x%llx hit=%d\n",
                added, static_cast<int>(aliased.status),
                static_cast<unsigned long long>(canonical.pte_pa),
                static_cast<unsigned long long>(aliased.pte_pa), walked.hit);
    return added && aliased.status == PteResolveStatus::Found && walked.hit &&
           aliased.pte_pa == canonical.pte_pa;
}

int main() {
    const bool cause = actual_cause_repro();
    const bool precedence = precedence_repro();
    const bool canonical = noncanonical_repro();
    const bool callback = dry_run_callback_repro();
    const bool sv32 = sv32_high_address_regression();
    const bool sv32_bad_sign = sv32_invalid_sign_extension_alias();
    std::printf("REPRO cause=%d precedence=%d noncanonical=%d callback=%d sv32=%d "
                "sv32_bad_sign=%d\n",
                cause, precedence, canonical, callback, sv32, sv32_bad_sign);
    return cause && precedence && canonical && callback && sv32 && sv32_bad_sign ? 0 : 1;
}
