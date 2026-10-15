#include <cstdlib>
#include <dlfcn.h>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "Architectures.h"
#include "Constraint.h"
#include "ChoicesModerator.h"
#include "Generator.h"
#include "MemoryManager.h"
#include "PageTable.h"
#include "Page.h"
#include "Register.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Weffc++"
#include "SimLoader.h" // Keep the pinned consumer header unchanged.
#pragma GCC diagnostic pop
#include "TopLevelResourcesRISCV.h"
#include "TwoStageTranslationUnit.h"
#include "VmAddressSpaceRISCV.h"
#include "VmFactoryRISCV.h"
#include "VmGpaAddressSpace.h"
#include "VmasControlBlock.h"

using namespace Force;

// The optional standalone ISS check does not feed execution back into the no-ISS generator.
extern "C" void update_generator_memory(uint32_t, uint64_t, uint32_t, uint64_t,
                                        uint32_t, const char*, const char*) {}
extern "C" void update_generator_register(uint32_t, const char*, uint64_t, uint64_t, const char*) {}

static void require(bool condition, const char* message)
{
  if (!condition) throw std::runtime_error(message);
}

// Independent Sv39/Sv39x4 walk of bytes written by FORCE, not Page objects or mapper caches.
static uint64 walk(uint64 root, uint64 address, bool gstage, uint64 guestRoot = 0)
{
  if (gstage) require(address < (1ull << 41), "GPA exceeds Sv39x4 width");
  uint64 table = root;
  for (int level = 2; level >= 0; --level) {
    uint64 index = (address >> (12 + 9 * level)) & ((gstage && level == 2) ? 0x7ff : 0x1ff);
    uint64 slot = table + index * 8;
    if (guestRoot) slot = walk(guestRoot, slot, true);
    uint8 bytes[8] = {};
    MemoryManager::Instance()->GetMemoryBank(0)->ReadMemoryPartiallyInitialized(slot, 8, bytes);
    uint64 pte = 0;
    for (unsigned i = 0; i < 8; ++i) pte |= uint64(bytes[i]) << (8 * i);
    require((pte & 1) != 0 && (pte & 6) != 4, "invalid descriptor in native walk");
    require((pte >> 54) == 0, "reserved PTE bits set");
    table = ((pte >> 10) & ((1ull << 44) - 1)) << 12;
    if (pte & 0xe) {
      require(!gstage || (pte & 0x10), "G-stage leaf must have U=1");
      require((pte & 0xc6) == 0xc6, "data leaf must allow read/write with A/D set");
      uint64 mask = (1ull << (12 + 9 * level)) - 1;
      require((table & mask) == 0, "misaligned superpage descriptor");
      return table | (address & mask);
    }
    require((pte & 0xd0) == 0, "reserved non-leaf U/A/D bits set");
  }
  throw std::runtime_error("native walk exhausted levels");
}

static void check_iss(const char* library, VmAddressSpaceRISCV& vs, VmGpaAddressSpace& gs)
{
  require(library[0] == '/', "Handcar candidate path must be absolute");
  SimDllApi api;
  api.sim_lib = dlopen(library, RTLD_NOW | RTLD_LOCAL);
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
  auto write = [&](const char* name, uint64 value) {
    require(api.write_simulator_register(0, name, value, ~0ull) == 0, "ISS register write failed");
  };
  auto read = [&](const char* name) {
    uint64_t value = 0, mask = 0;
    require(api.read_simulator_register(0, name, &value, &mask) == 0 && mask == ~0ull,
            "ISS register read failed");
    return value;
  };
  // Host initialization establishes only the allocated table RAM, never arbitrary CPU stores.
  for (const VmAddressSpaceRISCV* stage : {&vs, static_cast<VmAddressSpaceRISCV*>(&gs)}) {
    for (auto range : stage->GetVmConstraint(EVmConstraintType::PageTable)->GetConstraints()) {
      for (uint64_t address = range->LowerBound(); address <= range->UpperBound(); address += 0x1000) {
        uint8 bytes[4096];
        MemoryManager::Instance()->GetMemoryBank(0)->ReadMemoryPartiallyInitialized(address, sizeof(bytes), bytes);
        require(api.write_simulator_memory(0, &address, sizeof(bytes), bytes) == 0,
                "ISS table RAM initialization failed");
      }
    }
  }
  write("pmpaddr0", ~0ull >> 2);
  write("pmpcfg0", 0xf);
  write("mstatus", 0);
  write("hstatus", (2ull << 32) | (1ull << 8));
  write("vsatp", (8ull << 60) | (vs.GetControlBlock()->GetRootPageTable()->TableBase() >> 12));
  write("hgatp", (8ull << 60) | (1ull << 44) | (gs.GetControlBlock()->GetRootPageTable()->TableBase() >> 12));
  write("mtvec", 0x80000100);
  const uint32 instructions[] = {
    0x6c004073u | (11u << 15) | (10u << 7), // HLV.D x10, (x11)
    0x6e004073u | (11u << 15) | (12u << 20), // HSV.D x12, (x11)
    0x6c004073u | (11u << 15) | (13u << 7), // HLV.D x13, (x11)
  };
  uint8 code[sizeof(instructions)];
  for (unsigned i = 0; i < sizeof(code); ++i) code[i] = instructions[i / 4] >> (8 * (i % 4));
  uint64_t pc = 0x80000000;
  require(api.write_simulator_memory(0, &pc, sizeof(code), code) == 0, "ISS code initialization failed");
  for (uint64 gva : {0x40000ffCull, 0x50000ffCull, 0x60001050ull}) {
    uint64 mapped_pa = 0;
    uint32 bank = 0;
    require(vs.TranslateVaToPa(gva, mapped_pa, bank) == ETranslationResultType::Mapped, "missing ISS data mapping");
    uint64_t pa = mapped_pa;
    uint8 data[8];
    const uint64 before = 0x0123456789abcdefull, after = 0xfedcba9876543210ull;
    for (unsigned i = 0; i < 8; ++i) data[i] = before >> (8 * i);
    require(api.write_simulator_memory(0, &pa, sizeof(data), data) == 0, "ISS data RAM initialization failed");
    write("x11", gva);
    write("x12", after);
    write("PC", pc);
    for (unsigned i = 0; i < 3; ++i) {
      require(api.step_simulator(0, 1, 0) == 0, "ISS step failed");
      require(read("PC") == pc + 4 * (i + 1), "unexpected trap in generated page tables");
    }
    require(read("x10") == before && read("x13") == after, "HLV/HSV data mismatch");
    require(api.read_simulator_memory(0, &pa, sizeof(data), data) == 0, "ISS physical read failed");
    uint64 physical = 0;
    for (unsigned i = 0; i < 8; ++i) physical |= uint64(data[i]) << (8 * i);
    require(physical == after, "HSV did not reach expected SPA");
  }
  uint64_t unknown = 0x600000000ull;
  uint64_t store_pc = pc + 0x20;
  uint32 store = 0x3023u | (11u << 15) | (12u << 20); // SD x12, 0(x11)
  uint8 store_bytes[4];
  for (unsigned i = 0; i < 4; ++i) store_bytes[i] = store >> (8 * i);
  require(api.write_simulator_memory(0, &store_pc, 4, store_bytes) == 0, "store code initialization failed");
  write("x11", unknown);
  write("PC", store_pc);
  require(api.step_simulator(0, 1, 0) == 0, "unknown store step failed");
  require(read("mcause") == 7 && read("mepc") == store_pc && read("mtval") == unknown,
          "undeclared RAM store must fault");
  uint8 unknown_bytes[8];
  require(api.read_simulator_memory(0, &unknown, 8, unknown_bytes) != 0,
          "architectural store must not create RAM backing");
  api.terminate_simulator();
  dlclose(api.sim_lib);
  std::cout << "PASS: candidate " << library << ": 9 HLV/HSV steps, cross-page/high-GPA/superpage data; undeclared RAM store rejected" << std::endl;
}

int main()
{
  try {
    const char* seed = std::getenv("FORCE_M2_SEED");
    std::vector<std::string> options = {
      FORCE_TEST_ROOT "/bin/friscv", "--noiss", "--cfg",
      FORCE_TEST_ROOT "/config/riscv_rv64_twostage.config", "--test",
      FORCE_TEST_ROOT "/utils/smoke/test_force.py", "--seed", seed ? seed : "1",
      "--log", "error"
    };
    std::vector<char*> argv;
    for (auto& option : options) argv.push_back(&option[0]);
    initialize_top_level_resources_RISCV(argv.size(), argv.data());
    auto memory = MemoryManager::Instance();
    memory->AddMemoryRange(0, 0x80000000, 0xbfffffff);
    memory->ConfigureMemoryBanks();
    memory->SetupPageTableRegions();
    Generator* gen = Architectures::Instance()->DefaultArchInfo()->CreateGenerator(0);
    gen->InitializeRegister("privilege", "", 3);
    gen->InitializeRegister("mstatus", "", 0);
    gen->InitializeRegister("vsstatus", "", 0);
    gen->InitializeRegister("hstatus", "", 2ull << 32);
    gen->InitializeRegister("vsatp", "MODE", 8);
    gen->InitializeRegister("hgatp", "MODE", 8);
    gen->InitializeRegister("hgatp", "VMID", 1);
    auto choices = gen->GetChoicesModerator(EChoicesType::PagingChoices);
    for (const auto& suffix : {"S#stage 1", "H#stage 2"}) {
      choices->DoChoicesModification(std::string("Page size#4K granule#") + suffix,
                                    {{"4K", 100}, {"2M", 0}, {"1G", 0}});
    }

    {
      VmFactoryRISCV vs_factory(EVmRegimeType::VS);
      VmFactoryRISCV gs_factory(EVmRegimeType::HS);
      std::unique_ptr<VmAddressSpaceRISCV> vs(static_cast<VmAddressSpaceRISCV*>(
        vs_factory.CreateAddressSpace(vs_factory.CreateVmasControlBlock(EMemBankType::Default))));
      std::unique_ptr<VmGpaAddressSpace> gs(static_cast<VmGpaAddressSpace*>(
        gs_factory.CreateAddressSpace(gs_factory.CreateVmasControlBlock(EMemBankType::Default))));
      gs->Setup(gen);
      vs->Setup(gen);
      auto vs_root = vs->GetControlBlock()->GetRootPageTable();
      auto gs_root = gs->GetControlBlock()->GetRootPageTable();
      require(gs_root != vs_root, "VS and G roots must not alias");
      require(gs_root->RootTableSize() == 0x4000, "Sv39x4 root must be 16 KiB");
      require((gs_root->TableBase() & 0x3fff) == 0, "G-stage root must be 16 KiB aligned");
      require(vs_root->RootTableSize() == 0x1000, "VS root must remain 4 KiB");
      require(!vs->CompatiblePageTableContext(gs.get()) && !gs->CompatiblePageTableContext(vs.get()),
              "VS and G must reject root aliasing in both directions");
      require(!gs->VaInAddressErrorRange((1ull << 41) - 1) &&
              gs->VaInAddressErrorRange(1ull << 41) && gs->VaInAddressErrorRange(~0ull),
              "G-stage must use unsigned 41-bit GPA bounds");
      TwoStageTranslationUnit unit(vs.get(), gs.get());
      unit.SetupFullTranslation(0x40000ff8, 0x90000ff8, 0xa0000ff8, 0x1010, false);
      uint64 pa = 0;
      require(unit.ValidateTranslationChain(0x40002007, pa), "complete chain missing");
      require(pa == 0xa0002007, "wrong composed physical address");
      for (uint64 offset : {0ull, 7ull, 8ull, 0x1007ull, 0x1008ull, 0x100full}) {
        auto gpa = walk(vs_root->TableBase(), 0x40000ff8 + offset, false);
        require(gpa == 0x90000ff8 + offset, "wrong VS descriptor address");
        require(walk(gs_root->TableBase(), gpa, true) == 0xa0000ff8 + offset,
                "wrong G descriptor address");
        auto guest_gpa = walk(vs_root->TableBase(), 0x40000ff8 + offset, false,
                              gs_root->TableBase());
        require(guest_gpa == gpa, "VS page-table backing was not translated through G-stage");
      }
      unit.SetupFullTranslation(0x50000ff8, (1ull << 40) | 0x90000ff8, 0xa1000ff8, 0x1010, false);
      auto high_gpa = walk(vs_root->TableBase(), 0x50001000, false, gs_root->TableBase());
      require(high_gpa == ((1ull << 40) | 0x90001000), "high GPA lost in VS descriptor");
      require(walk(gs_root->TableBase(), high_gpa, true) == 0xa1001000, "x4 root index lost GPA bits");
      for (const auto& suffix : {"S#stage 1", "H#stage 2"}) {
        choices->DoChoicesModification(std::string("Page size#4K granule#") + suffix,
                                      {{"4K", 0}, {"2M", 100}, {"1G", 0}});
      }
      unit.SetupFullTranslation(0x60001050, 0x92001050, 0xa2001050, 8, false);
      require(vs->GetPage(0x60001050)->PageSize() == 0x200000 &&
              gs->GetPage(0x92001050)->PageSize() == 0x200000, "expected 2 MiB leaves");
      auto large_gpa = walk(vs_root->TableBase(), 0x60001050, false, gs_root->TableBase());
      require(walk(gs_root->TableBase(), large_gpa, true) == 0xa2001050, "superpage byte walk mismatch");
      bool conflict = false;
      try {
        unit.SetupFullTranslation(0x70000000, vs_root->TableBase(), 0xa3000000, 8, false);
      }
      catch (const std::runtime_error& error) {
        conflict = std::string(error.what()) == "two-stage-mapping-conflict";
      }
      require(conflict && unit.IsEnabled() && !vs->GetPage(0x70000000),
              "VS table backing must not be silently remapped");
      const char* handcar = std::getenv("FORCE_M2_HANDCAR_SO");
      if (handcar) check_iss(handcar, *vs, *gs);
    }
    delete gen;
    destroy_top_level_resources_RISCV();
    std::cout << "PASS: native two-stage allocation" << std::endl;
    return 0;
  }
  catch (const std::exception& error) {
    std::cerr << "FAIL: native two-stage allocation: " << error.what() << std::endl;
    return 1;
  }
}
