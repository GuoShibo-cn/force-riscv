// Use the actual FORCE/fpix loader function types and caller-owned buffers.
#include "../../utils/handcar/SimLoader.h"
#include <cassert>
#include <cstring>
#include <dlfcn.h>
#include <iostream>
#include <string>
#include <vector>

extern "C" void update_generator_memory(uint32_t, uint64_t, uint32_t, uint64_t,
    uint32_t, const char*, const char*) {}
extern "C" void update_generator_register(uint32_t, const char*, uint64_t, uint64_t, const char*) {}

struct TrapRecord {
  uint64_t cause, epc, tval, target;
  uint32_t from_priv, to_priv;
  std::string name;
};
static std::vector<TrapRecord> traps;
extern "C" void handcar_trace_trap(uint32_t cpu, uint64_t cause, uint64_t epc,
    uint64_t tval, uint64_t, uint64_t, uint64_t target, uint32_t from_priv,
    uint32_t, uint32_t to_priv, uint32_t, const char* name) {
  assert(cpu == 0);
  traps.push_back({cause, epc, tval, target, from_priv, to_priv, name});
}

int main(int argc, char** argv) {
  assert(argc >= 2);
  SimDllApi api;
  api.sim_lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
  if (!api.sim_lib) { std::cerr << dlerror() << '\n'; return 1; }
#define LOAD(name) api.name = reinterpret_cast<decltype(api.name)>(dlsym(api.sim_lib, #name)); assert(api.name)
  LOAD(initialize_simulator);
  LOAD(terminate_simulator);
  LOAD(get_disassembly);
  LOAD(get_disassembly_for_target);
  LOAD(read_simulator_register);
  LOAD(write_simulator_register);
  LOAD(read_simulator_memory);
  LOAD(write_simulator_memory);
  LOAD(step_simulator);
#undef LOAD
  auto fpix_write = reinterpret_cast<decltype(api.write_simulator_register)>(
      dlsym(api.sim_lib, "write_simulator_register_fpix"));
  auto fpix_read = reinterpret_cast<decltype(api.read_simulator_register)>(
      dlsym(api.sim_lib, "read_simulator_register_fpix"));
  auto initialize_memory = reinterpret_cast<int (*)(int, const uint64_t*, int, uint64_t)>(
      dlsym(api.sim_lib, "initialize_simulator_memory"));
  auto translate = reinterpret_cast<int (*)(int, const uint64_t*, int, uint64_t*, uint64_t*)>(
      dlsym(api.sim_lib, "translate_virtual_address"));
  assert(fpix_write && fpix_read && initialize_memory && translate);
  if (argc == 3) {
    api.initialize_simulator(argv[2]);
    api.terminate_simulator();
    return 99; // Unsupported multi-hart options must have failed initialization.
  }
  auto read = [&](const char* name) {
    uint64_t value = 0, mask = 0;
    assert(api.read_simulator_register(0, name, &value, &mask) == 0);
    assert(mask == UINT64_MAX);
    return value;
  };
  auto write = [&](const char* name, uint64_t value, uint64_t mask = UINT64_MAX) {
    assert(api.write_simulator_register(0, name, value, mask) == 0);
  };
  api.initialize_simulator("-p1 --isa=rv64imach --pc=0x80000000");
  uint64_t pc = 0x80000000;
  assert(read("PC") == pc);
  assert(initialize_memory(0, &pc, 4, 0x00100513) == 0); // addi x10,x0,1
  for (unsigned i = 0; i < 1024; i++) {
    char* opcode = new char[128];
    char* disassembly = new char[128];
    memset(opcode, '0', 128);
    memset(disassembly, '0', 128);
    opcode[127] = disassembly[127] = 0;
    auto original_opcode = opcode, original_disassembly = disassembly;
    assert(api.get_disassembly_for_target(0, &pc, &opcode, &disassembly) == 0);
    assert(opcode == original_opcode && disassembly == original_disassembly);
    assert(std::string(opcode) == "0x100513" && strlen(disassembly) < 128);
    assert(api.get_disassembly(&pc, &opcode, &disassembly) == 0);
    uint64_t bad_pc = 0x600000000;
    assert(api.get_disassembly_for_target(0, &bad_pc, &opcode, &disassembly) == 1);
    assert(opcode == original_opcode && disassembly == original_disassembly);
    assert(strcmp(opcode, "00000000") == 0 && strcmp(disassembly, "?") == 0);
    delete[] opcode;
    delete[] disassembly;
  }
  // Eight-byte illegal encodings exercise the no-shift-by-64 disassembly path.
  assert(initialize_memory(0, &pc, 8, 0x3f) == 0);
  char op[128], dis[128];
  char* opp = op; char* disp = dis;
  assert(api.get_disassembly(&pc, &opp, &disp) == 0 && opp == op && disp == dis);
  assert(api.get_disassembly(&pc, nullptr, &disp) != 0);

  constexpr uint64_t old = 0xaabbccddeeff0011, mask = 0x00ff00000000ff00;
  for (const char* name : {"x1", "x10", "x31", "PC", "mscratch", "vsscratch"}) {
    write(name, old);
    write(name, 0x123456789abcdef0, mask);
    uint64_t expected = (old & ~mask) | (0x123456789abcdef0 & mask);
    assert(read(name) == expected);
    assert(fpix_write(0, name, ~uint64_t(0), 0xff) == 0);
    expected |= 0xff;
    uint64_t value = 0, read_mask = 0;
    assert(fpix_read(0, name, &value, &read_mask) == 0 && value == expected);
    write(name, 0, 0);
    assert(read(name) == expected);
  }
  assert(read("X31") == read("x31"));
  assert(api.write_simulator_register(0, "x32", 1, UINT64_MAX) != 0);
  assert(api.write_simulator_register(0, "x1junk", 1, UINT64_MAX) != 0);
  write("x0", UINT64_MAX); assert(read("x0") == 0);
  write("hvip", 0x444); write("hvip", 0, 4); assert(read("hvip") == 0x440);
  write("mstatus", 1ull << 17, 1ull << 17);
  write("mstatus", 1ull << 3, 1ull << 3);
  assert((read("mstatus") & (1ull << 17)) != 0);
  write("mstatus", 0, (1ull << 17) | (1ull << 3));

  uint64_t addr = 0x80000200;
  assert(initialize_memory(0, &addr, 1, 0xab) == 0);
  uint8_t bytes[8]; memset(bytes, 0xff, sizeof(bytes));
  assert(api.read_simulator_memory(0, &addr, 8, bytes) == 0);
  assert(bytes[0] == 0xab);
  for (size_t i = 1; i < 8; i++) assert(bytes[i] == 0);
  uint64_t unknown = 0x600000000;
  memset(bytes, 0xa5, sizeof(bytes));
  assert(api.read_simulator_memory(0, &unknown, 8, bytes) != 0);
  for (auto b : bytes) assert(b == 0xa5);
  for (int len : {-1, 0}) {
    assert(api.read_simulator_memory(0, &addr, len, bytes) != 0);
    assert(api.write_simulator_memory(0, &addr, len, bytes) != 0);
    assert(initialize_memory(0, &addr, len, 0) != 0);
  }
  uint64_t overflow = UINT64_MAX;
  assert(api.write_simulator_memory(0, &overflow, 8, bytes) != 0);
  assert(api.read_simulator_memory(0, &overflow, 8, bytes) != 0);
  assert(api.read_simulator_memory(1, &addr, 1, bytes) != 0);
  // PLIC rejects subword accesses; external initialization must not shadow it.
  uint64_t mmio = 0xc000000;
  uint8_t mmio_before[8], mmio_after[8];
  assert(api.read_simulator_memory(0, &mmio, 8, mmio_before) == 0);
  assert(api.write_simulator_memory(0, &mmio, 1, bytes) != 0);
  assert(api.read_simulator_memory(0, &mmio, 8, mmio_after) == 0);
  assert(memcmp(mmio_before, mmio_after, 8) == 0);
  uint64_t pa = 0x1234, attrs = 0x5678;
  assert(translate(0, &addr, 0, &pa, &attrs) == 9 && pa == 0x1234 && attrs == 0x5678);
  // The public API translates one byte even at the end of a locked PMP NA4 region.
  uint64_t pmp_end = 0x80000fff;
  write("pmpaddr0", (pmp_end & ~3ull) >> 2);
  write("pmpcfg0", 0x91); // locked, NA4, read-only
  assert(translate(0, &pmp_end, 0, &pa, nullptr) == 0 && pa == pmp_end);
  api.terminate_simulator();

  api.initialize_simulator("--isa=rv64imafdch");
  uint64_t mstatus_before = read("mstatus");
  assert(api.write_simulator_register(0, "fflags", 1, 1) != 0);
  assert(read("mstatus") == mstatus_before);
  write("fflags", 0x1f); // Existing full-mask initialization compatibility.
  write("fflags", 0, 1);
  assert(read("fflags") == 0x1e);
  api.terminate_simulator();

  // Explicit ISA strings must retain their own misalignment semantics.
  for (bool enabled : {false, true}) {
    api.initialize_simulator(enabled ? "--isa=rv64imach_zicclsm" : "--isa=rv64imach");
    pc = 0x80000000;
    uint64_t data_addr = 0x80000301;
    assert(initialize_memory(0, &pc, 4, (1u << 20) | (11u << 15) | (3u << 12) | (10u << 7) | 3) == 0);
    assert(initialize_memory(0, &data_addr, 8, 0xabcdef) == 0);
    write("x11", data_addr - 1); write("PC", pc); write("mtvec", pc + 0x1000);
    assert(api.step_simulator(0, 1, 0) == 0);
    if (enabled) assert(read("x10") == 0xabcdef && read("PC") == pc + 4);
    else assert(read("mcause") == 4 && read("PC") == pc + 0x1000);
    api.terminate_simulator();
  }
  // Repeated identical traps must be observed even when the CSRs do not change.
  api.initialize_simulator("--isa=rv64imach");
  pc = 0x80000000;
  traps.clear();
  assert(initialize_memory(0, &pc, 4, 0) == 0);
  write("mtvec", pc + 0x1000);
  for (unsigned i = 0; i < 2; ++i) {
    write("PC", pc);
    assert(api.step_simulator(0, 1, 0) == 0);
    assert(traps.size() == i + 1);
    const auto& trap = traps.back();
    assert(trap.cause == 2 && trap.epc == pc && trap.target == pc + 0x1000);
    assert(trap.from_priv == 3 && trap.to_priv == 3);
    assert(trap.name == "trap_illegal_instruction");
  }
  // A CSR write plus a normal step is not a trap, even with stale trap CSRs.
  write("mcause", 23);
  assert(initialize_memory(0, &pc, 4, 0x00100513) == 0);
  write("PC", pc);
  assert(api.step_simulator(0, 1, 0) == 0 && traps.size() == 2);
  // Instruction access faults have no decoded instruction, but do have an event.
  write("PC", 0x600000000);
  assert(api.step_simulator(0, 1, 0) == 0 && traps.size() == 3);
  assert(traps.back().cause == 1 && traps.back().epc == 0x600000000);
  // Verify that delegated S-mode traps are observed as well as M-mode traps.
  write("pmpaddr0", UINT64_MAX >> 2); write("pmpcfg0", 0xf);
  write("medeleg", 1ull << 9); write("stvec", pc + 0x2000);
  write("mstatus", 1ull << 11); write("mepc", pc + 4);
  assert(initialize_memory(0, &pc, 8, (uint64_t(0x00000073) << 32) | 0x30200073) == 0);
  write("PC", pc);
  assert(api.step_simulator(0, 1, 0) == 0 && traps.size() == 3); // mret
  assert(api.step_simulator(0, 1, 0) == 0 && traps.size() == 4); // ecall
  assert(traps.back().cause == 9 && traps.back().epc == pc + 4);
  assert(traps.back().from_priv == 1 && traps.back().to_priv == 1);
  assert(traps.back().target == pc + 0x2000);
  api.terminate_simulator();
  dlclose(api.sim_lib);
  std::cout << "PASS: real loader ABI, 1024 caller-owned disassembly buffer cycles, "
               "GPR/CSR/fpix masks, physical reads, MMIO rejection, PMP byte API, explicit ISA, "
               "actual/repeated/delegated trap trace events\n";
}
