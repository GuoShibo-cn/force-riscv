// Standalone downstream consumer: PTG constructs every PTE; Handcar executes the result.
#include <cstdint>
#include <cstring>
#include <dlfcn.h>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

#include "ptg/ptg.h"
#include "SimLoader.h"

extern "C" void update_generator_memory(uint32_t, uint64_t, uint32_t, uint64_t,
                                        uint32_t, const char*, const char*) {}
extern "C" void update_generator_register(uint32_t, const char*, uint64_t, uint64_t, const char*) {}

static void require(bool condition, const char* text)
{
  if (!condition) throw std::runtime_error(text);
}

struct Snapshot {
  std::vector<PtgExportBlockV1> blocks;
  std::vector<uint8_t> bytes;
};

static uint64_t capture(void* h, uint32_t ctx, int stage)
{
  PtgExportLayoutRequestV1 req;
  require(ptg_export_layout_v1_init(&req, sizeof(req)) == PTG_MAPPING_OK, "export init");
  req.stage = stage;
  uint64_t id = 0;
  require(ptg_export_layout_create_v1(h, ctx, &req, &id) == PTG_MAPPING_OK && id != 0,
          "strict layout capture");
  return id;
}

static Snapshot pull(void* h, uint64_t layout, int stage)
{
  uint32_t count = 0;
  uint64_t size = 0;
  require(ptg_export_layout_read_v1(h, layout, nullptr, 0, sizeof(PtgExportBlockV1),
          nullptr, 0, &count, &size) == PTG_MAPPING_OK, "strict preflight");
  require(count && size && size <= std::numeric_limits<size_t>::max(), "snapshot sizes");
  Snapshot result;
  result.blocks.resize(count);
  result.bytes.resize(size);
  require(ptg_export_layout_read_v1(h, layout, result.blocks.data(), count,
          sizeof(PtgExportBlockV1), result.bytes.data(), size, &count, &size) == PTG_MAPPING_OK,
          "strict pull");
  require(count == result.blocks.size() && size == result.bytes.size(), "snapshot changed");
  uint64_t offset = 0;
  for (const auto& block : result.blocks) {
    require(block.struct_size == sizeof(block) && block.abi_version == 1 && block.stage == stage,
            "block header");
    require(block.data_offset == offset && block.size <= size - offset, "block byte range");
    require(block.size <= static_cast<uint64_t>(std::numeric_limits<int>::max()), "block too large");
    if (stage == PTG_STAGE_VS) {
      require(block.source_kind == PTG_MAPPING_KIND_GPA &&
              block.source_address >= 0x50000000 && block.source_address < 0x50200000,
              "VS block must use GPA source domain");
      // Independently fixed G-stage superpage, not an expectation computed by PTG query/export.
      require(block.spa == 0xA4000000 + block.source_address - 0x50000000,
              "VS block must use predetermined backing SPA");
    } else {
      require(block.source_kind == PTG_MAPPING_KIND_SPA && block.source_address == block.spa,
              "G block must use SPA source domain");
    }
    offset += block.size;
  }
  require(offset == size, "snapshot trailing bytes");
  return result;
}

int main(int argc, char** argv)
{
  void* h = nullptr;
  SimDllApi api;
  bool started = false;
  try {
    require(argc == 2 && argv[1][0] == '/', "usage: ptg_strict_export_iss /absolute/handcar.so");
    h = ptg_create();
    require(h != nullptr, "PTG create");
    ptg_register_pa_region(h, 0xA0000000, 0xB0000000);
#ifdef PTG_CHECK_ALLOCATION_PLACEMENT
    PtgPlacementConfigV1 policy;
    PtgLevelPlacementV1 levels[3];
    require(ptg_placement_config_v1_init(&policy, sizeof(policy)) == 0, "PA placement init");
    for (unsigned i = 0; i < 3; ++i) {
      require(ptg_level_placement_v1_init(&levels[i], sizeof(levels[i])) == 0, "level init");
      levels[i].level = 2 - i;
      levels[i].base = 0xA0010000 + i * 0x10000;
      levels[i].limit = levels[i].base + (i == 0 ? 0x4000 : 0x1000);
    }
    require(ptg_configure_pa_placement_v1(h, &policy, levels, 3, sizeof(levels[0])) == 0,
            "configure PA placement");
#endif
    ptg_register_gpa_region(h, 1, 0x50000000, 0x50200000);
#ifdef PTG_CHECK_ALLOCATION_PLACEMENT
    for (unsigned i = 0; i < 3; ++i) {
      levels[i].base = 0x50010000 + i * 0x4000;
      levels[i].limit = levels[i].base + 0x1000;
    }
    require(ptg_configure_gpa_placement_v1(h, 1, &policy, levels, 3, sizeof(levels[0])) == 0,
            "configure VMID GPA placement");
#endif
    const uint32_t ctx = ptg_context_create(h, 1, 1);
    ptg_context_gs_stage(h, ctx, 8);
    auto map = [&](int stage, uint64_t va, uint64_t pa, int level, uint8_t perm) {
      ptg_add_mapping(h, ctx, stage, va, pa, uint64_t(1) << (12 + 9 * level), level, perm);
      require(ptg_last_error(h) == PTG_OK, "PTG mapping setup");
    };
    map(PTG_STAGE_G, 0x50000000, 0xA4000000, 1, 0x73);
    ptg_context_vs_stage(h, ctx, 8);
    for (uint64_t off : {0ull, 0x1000ull, 0x2000ull}) {
      map(PTG_STAGE_VS, 0x40000000 + off, 0x60000000 + off, 0, off == 0x2000 ? 0x64 : 0x63);
      map(PTG_STAGE_G, 0x60000000 + off, 0xA8000000 + off, 0, 0x73);
    }
    map(PTG_STAGE_VS, 0x60000000, 0x62000000, 1, 0x63);
    map(PTG_STAGE_G, 0x62000000, 0xAA000000, 1, 0x73);

    PtgMappingQueryV1 query;
    require(ptg_mapping_query_v1_init(&query, sizeof(query)) == PTG_MAPPING_OK, "query init");
    query.stage = PTG_STAGE_VS;
    query.address = 0x40002000;
    PtgMappingRecordV1 record;
    uint32_t required = 0;
    require(ptg_mapping_query_v1(h, ctx, &query, &record, 1, sizeof(record), &required) == PTG_MAPPING_OK &&
            required == 1 && (record.valid_fields & PTG_MAPPING_VALID_CURRENT) &&
            record.output_kind == PTG_MAPPING_KIND_GPA && record.matched_pa == 0x60002000 &&
            record.raw_perm == 0x64, "execute-only leaf must be structurally queryable as GPA");

    const uint64_t vs_layout = capture(h, ctx, PTG_STAGE_VS);
    const uint64_t g_layout = capture(h, ctx, PTG_STAGE_G);
    const Snapshot vs = pull(h, vs_layout, PTG_STAGE_VS);
    const Snapshot gs = pull(h, g_layout, PTG_STAGE_G);
#ifdef PTG_CHECK_ALLOCATION_PLACEMENT
    const uint64_t old_vs = ptg_context_vsatp(h, ctx), old_g = ptg_context_hgatp(h, ctx);
    require(((old_vs & ((1ull << 44) - 1)) << 12) == 0x50010000 &&
            ((old_g & ((1ull << 44) - 1)) << 12) == 0xA0010000, "independent placed roots");
    policy.pt_base = 0xA0050000; policy.pt_limit = 0xA0060000;
    require(ptg_configure_pa_placement_v1(h, &policy, nullptr, 0, sizeof(levels[0])) == 0,
            "online PA policy update");
    policy.pt_base = 0x50020000; policy.pt_limit = 0x50040000;
    require(ptg_configure_gpa_placement_v1(h, 1, &policy, nullptr, 0, sizeof(levels[0])) == 0,
            "online GPA policy update");
    require(ptg_context_vsatp(h, ctx) == old_vs && ptg_context_hgatp(h, ctx) == old_g,
            "policy must not switch hardware roots");
    require(pull(h, vs_layout, PTG_STAGE_VS).bytes == vs.bytes &&
            pull(h, g_layout, PTG_STAGE_G).bytes == gs.bytes, "policy must preserve live snapshots");
#endif
    api.sim_lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!api.sim_lib) throw std::runtime_error(dlerror());
#define LOAD(name) api.name = reinterpret_cast<decltype(api.name)>(dlsym(api.sim_lib, #name)); require(api.name != nullptr, #name)
    LOAD(initialize_simulator);
    LOAD(terminate_simulator);
    LOAD(write_simulator_memory);
    LOAD(read_simulator_memory);
    LOAD(write_simulator_register);
    LOAD(read_simulator_register);
    LOAD(step_simulator);
#undef LOAD
    api.initialize_simulator("-p1 --isa=rv64imach_zicclsm --pc=0x80000000");
    started = true;
    auto write = [&](const char* reg, uint64_t value) {
      require(api.write_simulator_register(0, reg, value, ~uint64_t(0)) == 0, "ISS register write");
    };
    auto read = [&](const char* reg) {
      uint64_t value = 0, mask = 0;
      require(api.read_simulator_register(0, reg, &value, &mask) == 0 && mask == ~uint64_t(0),
              "ISS register read");
      return value;
    };
    auto load = [&](const Snapshot& snapshot) {
      for (const auto& block : snapshot.blocks) {
        require(api.write_simulator_memory(0, &block.spa, block.size,
                snapshot.bytes.data() + block.data_offset) == 0, "host table RAM initialization");
      }
    };
    load(vs);
    load(gs);
    write("pmpaddr0", ~uint64_t(0) >> 2);
    write("pmpcfg0", 0xf);
    write("mstatus", 0);
    write("vsstatus", 0);
    write("hstatus", (2ull << 32) | (1ull << 8));
    write("vsatp", ptg_context_vsatp(h, ctx));
    write("hgatp", ptg_context_hgatp(h, ctx));
    write("mtvec", 0x80001000);
    auto instruction = [&](uint64_t pc, uint32_t opcode) {
      uint8_t bytes[4];
      for (unsigned i = 0; i < 4; ++i) bytes[i] = opcode >> (8 * i);
      require(api.write_simulator_memory(0, &pc, 4, bytes) == 0, "host instruction RAM initialization");
    };
    const uint32_t hlv = 0x6c004073u | (11u << 15) | (10u << 7);
    instruction(0x80000000, hlv);
    instruction(0x80000004, 0x6e004073u | (11u << 15) | (12u << 20));
    instruction(0x80000008, 0x6c004073u | (11u << 15) | (13u << 7));
    const uint64_t inputs[][2] = {{0x40000ffc, 0xA8000ffc}, {0x60001050, 0xAA001050}};
    for (const auto& input : inputs) {
      const uint64_t before = 0x0123456789abcdefull, after = 0xfedcba9876543210ull;
      uint8_t bytes[8];
      for (unsigned i = 0; i < 8; ++i) bytes[i] = before >> (8 * i);
      require(api.write_simulator_memory(0, &input[1], 8, bytes) == 0, "host data RAM initialization");
      write("x11", input[0]); write("x12", after); write("PC", 0x80000000);
      for (unsigned i = 0; i < 3; ++i) {
        require(api.step_simulator(0, 1, 0) == 0 && read("PC") == 0x80000004 + 4 * i,
                "unexpected successful-path trap");
      }
      require(read("x10") == before && read("x13") == after, "HLV/HSV data mismatch");
      require(api.read_simulator_memory(0, &input[1], 8, bytes) == 0, "physical SPA read");
      uint64_t actual = 0;
      for (unsigned i = 0; i < 8; ++i) actual |= uint64_t(bytes[i]) << (8 * i);
      require(actual == after, "HSV missed independently expected SPA");
    }
    instruction(0x80000020, hlv);
    write("x11", 0x40002000); write("x10", 0x55); write("PC", 0x80000020);
    require(api.step_simulator(0, 1, 0) == 0 && read("mcause") == 13 &&
            read("mepc") == 0x80000020 && read("mtval") == 0x40002000 && read("x10") == 0x55,
            "query structural validity must not authorize HLV on execute-only VS leaf");

    PtgFaultRequestV2 fault;
    require(ptg_fault_request_v2_init(&fault, sizeof(fault)) == 0, "fault init");
    fault.stage = 2; fault.scope = 0; fault.address_kind = 0; fault.selection_mode = 1;
    fault.fault_cause = 1; fault.access_type = 0; fault.privilege = 2;
    fault.verification_mode = 0; fault.target_level = 0;
    fault.has_target_address = 1; fault.target_address = 0x60000000; fault.dry_run = 0;
    PtgFaultResultV2 mutation;
    require(ptg_inject_fault_v2(h, ctx, &fault, nullptr, 0, sizeof(mutation), &required) == 9 &&
            required == 1, "fault preflight");
    require(ptg_inject_fault_v2(h, ctx, &fault, &mutation, 1, sizeof(mutation), &required) == 0 &&
            (mutation.new_pte & 1) == 0, "G data leaf fault injection");
    load(pull(h, g_layout, PTG_STAGE_G));
    instruction(0x80000040, 0x62000073); // HFENCE.GVMA x0, x0
    instruction(0x80000044, hlv);
    write("x11", 0x40000000); write("x10", 0x66); write("PC", 0x80000040);
    require(api.step_simulator(0, 1, 0) == 0 && read("PC") == 0x80000044, "HFENCE.GVMA");
    require(api.step_simulator(0, 1, 0) == 0 && read("mcause") == 21 &&
            read("mepc") == 0x80000044 && read("mtval") == 0x40000000 &&
            read("mtval2") == (0x60000000 >> 2) && read("x10") == 0x66,
            "strict captured layout did not deliver current G fault bytes");
    require(ptg_export_layout_free_v1(h, vs_layout) == 0 &&
            ptg_export_layout_free_v1(h, g_layout) == 0, "layout release");
    api.terminate_simulator(); started = false;
    dlclose(api.sim_lib); api.sim_lib = nullptr;
    ptg_destroy(h); h = nullptr;
    std::cout << "PASS: strict PTG pull -> Handcar, cross-page/2MiB HLV-HSV, structural-only query, "
                 "VS cause13, frozen G mutation plus HFENCE cause21; 9 architectural steps\n";
#ifdef PTG_CHECK_ALLOCATION_PLACEMENT
    std::cout << "PASS: allocation placement policy and online non-relocation through Handcar\n";
#endif
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "FAIL: " << error.what() << '\n';
    if (started) api.terminate_simulator();
    if (api.sim_lib) dlclose(api.sim_lib);
    if (h) ptg_destroy(h);
    return 1;
  }
}
