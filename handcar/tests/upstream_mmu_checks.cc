// Focused integration checks against the candidate library, not replacement MMU code.
#include <sys/syscall.h>
#include "mmu.h"
#include <iostream>
#include <vector>

struct memory_event {
  uint64_t va, pa;
  std::vector<uint8_t> bytes;
  std::string access;
};
static std::vector<memory_event> events;
extern "C" void update_generator_memory(uint32_t, uint64_t va, uint32_t,
    uint64_t pa, uint32_t size, const char* bytes, const char* access) {
  events.push_back({va, pa, std::vector<uint8_t>(bytes, bytes + size), access});
}
extern "C" void update_generator_register(uint32_t, const char*, uint64_t, uint64_t, const char*) {}

class test_sim : public simif_t {
public:
  cfg_t cfg;
  std::map<size_t, processor_t*> harts;
  std::vector<char> ram = std::vector<char>(2 * PGSIZE, 0);
  std::vector<uint8_t> device = std::vector<uint8_t>(PGSIZE, 0x5a);
  static constexpr reg_t device_base = 0x40000000;
  size_t rejected_stores = 0;
  static constexpr reg_t base = 0x80000000;
  char* addr_to_mem(reg_t pa) override {
    return pa >= base && pa - base < ram.size() ? ram.data() + (pa - base) : nullptr;
  }
  bool mmio_load(reg_t addr, size_t len, uint8_t* bytes) override {
    if (addr < device_base || addr - device_base + len > device.size()) return false;
    memcpy(bytes, device.data() + addr - device_base, len);
    return true;
  }
  bool mmio_store(reg_t, size_t, const uint8_t*) override { rejected_stores++; return false; }
  void proc_reset(unsigned) override {}
  const cfg_t& get_cfg() const override { return cfg; }
  const std::map<size_t, processor_t*>& get_harts() const override { return harts; }
  const char* get_symbol(uint64_t) override { return nullptr; }
};

int main() {
  test_sim sim;
  processor_t proc("rv64imach_zicclsm_svadu", "MSU", &sim.cfg, &sim, 0, false, nullptr, std::cerr);
  sim.harts[0] = &proc;
  auto mmu = proc.get_mmu();
  constexpr reg_t base = test_sim::base;
  uint64_t host_value = 0x1122334455667788;
  memcpy(sim.addr_to_mem(base + 24), &host_value, 8);
  events.clear();
  assert(mmu->load<uint64_t>(base + 24) == host_value);
  assert(mmu->load<uint64_t>(base + 24) == host_value);
  assert(events.size() == 2 && events[1].pa == base + 24);
  mmu->sparse_initialize_pa(base + 25, 0xaa, 1);
  assert(mmu->load<uint64_t>(base + 24) == 0x112233445566aa88);
  mmu->sparse_initialize_pa(base + 24, 0xdeadbeef, 8);
  assert(mmu->load<uint64_t>(base + 24) == 0xdeadbeef);
  assert(mmu->load<uint64_t>(base + 24) == 0xdeadbeef);
  events.clear();
  mmu->store<uint64_t>(base + 24, 0x10203040);
  mmu->store<uint64_t>(base + 24, 0x50607080);
  assert(events.size() == 2 && events[1].access == "write");
  assert(mmu->sparse_read(base + 24, 8) == 0x50607080);
  memcpy(&host_value, sim.addr_to_mem(base + 24), 8);
  assert(host_value == 0x50607080);

  // Sparse instruction parcels must override host RAM on cold and warm ITLBs.
  mmu->sparse_initialize_pa(base, 0x00100093, 4);
  assert(mmu->load_insn(base).insn.bits() == 0x00100093);
  mmu->flush_icache();
  assert(mmu->load_insn(base).insn.bits() == 0x00100093);
  mmu->sparse_initialize_pa(base, 0x00200093, 4);
  assert(mmu->load_insn(base).insn.bits() == 0x00200093);

  constexpr reg_t outside = 0x140000000;
  mmu->declare_sparse_memory(outside, 2 * PGSIZE);
  mmu->sparse_initialize_pa(outside + PGSIZE - 4, 0x8877665544332211, 8);
  events.clear();
  assert(mmu->load<uint64_t>(outside + PGSIZE - 4) == 0x8877665544332211);
  assert(events.size() == 2 && events[0].bytes.size() == 4 && events[1].bytes.size() == 4);
  bool trapped = false;
  try { mmu->amo<uint64_t>(outside + 1, [](uint64_t x) { return x; }); }
  catch (trap_store_access_fault&) { trapped = true; }
  assert(trapped);
  mmu->cbo_zero(outside + 3);
  assert(mmu->sparse_is_pa_initialized(outside, sim.cfg.cache_blocksz));
  for (size_t i = 0; i < sim.cfg.cache_blocksz; i++)
    assert(mmu->sparse_read(outside + i, 1) == 0);

  // Hardware A/D updates to sparse PTEs must survive cache flushes.
  constexpr reg_t root = 0x100000000, l1 = root + PGSIZE, l0 = l1 + PGSIZE;
  mmu->declare_sparse_memory(root, 3 * PGSIZE);
  constexpr reg_t va = 0x40000000;
  const reg_t leaf = ((outside >> PGSHIFT) << PTE_PPN_SHIFT) | PTE_V | PTE_R | PTE_W;
  mmu->sparse_initialize_pa(root + 8, ((l1 >> PGSHIFT) << PTE_PPN_SHIFT) | PTE_V, 8);
  mmu->sparse_initialize_pa(l1, ((l0 >> PGSHIFT) << PTE_PPN_SHIFT) | PTE_V, 8);
  mmu->sparse_initialize_pa(l0, leaf, 8);
  mmu->sparse_initialize_pa(outside, 0xabcdef, 8);
  proc.set_max_vaddr_bits(39);
  proc.put_csr(CSR_MENVCFG, MENVCFG_ADUE);
  proc.put_csr(CSR_SATP, (reg_t(SATP_MODE_SV39) << 60) | (root >> PGSHIFT));
  proc.set_privilege(PRV_S, false);
  events.clear();
  assert(mmu->load<uint64_t>(va) == 0xabcdef);
  assert(mmu->sparse_read(l0, 8) == (leaf | PTE_A));
  mmu->store<uint64_t>(va, 0x76543210);
  assert(mmu->sparse_read(l0, 8) == (leaf | PTE_A | PTE_D));
  size_t pte_writes = 0;
  for (auto& event : events)
    if (event.pa == l0 && event.access == "write") pte_writes++;
  assert(pte_writes == 2);
  mmu->flush_tlb();
  assert(mmu->load<uint64_t>(va) == 0x76543210);
  proc.put_csr(CSR_MENVCFG, 0);
  mmu->sparse_initialize_pa(l0, leaf, 8);
  trapped = false;
  try { mmu->load<uint64_t>(va); }
  catch (trap_load_page_fault&) { trapped = true; }
  assert(trapped);
  // Bit 1 means HLVX and must also force virtualization (G-stage is bare here).
  proc.put_csr(CSR_VSATP, (reg_t(SATP_MODE_SV39) << 60) | (root >> PGSHIFT));
  proc.put_csr(CSR_HSTATUS, HSTATUS_SPVP);
  mmu->sparse_initialize_pa(l0, (leaf & ~(PTE_R | PTE_W)) | PTE_X | PTE_A, 8);
  reg_t pa = 0;
  assert(mmu->translate_api(va, &pa, nullptr, 1, LOAD, 1) != 0);
  assert(mmu->translate_api(va, &pa, nullptr, 1, LOAD, 2) == 0 && pa == outside);
  uint64_t attrs = 0x1234;
  pa = 0x5678;
  assert(mmu->translate_api(va, &pa, &attrs, 1, LOAD, 2) == 9);
  assert(pa == 0x5678 && attrs == 0x1234);
  trapped = false;
  try { mmu->pmp_ok_api(outside, &pa, nullptr, 1, LOAD, PRV_S); }
  catch (std::invalid_argument&) { trapped = true; }
  assert(trapped && pa == 0x5678);
  assert(mmu->walk_api(va, &pa, LOAD, PRV_M, false, false) == 0 && pa == va);

  // A/D stores rejected by a read-only MMIO PTE must not become sparse writes.
  reg_t device_pte = leaf;
  memcpy(sim.device.data() + 8, &device_pte, 8);
  proc.put_csr(CSR_SATP, (reg_t(SATP_MODE_SV39) << 60) | (test_sim::device_base >> PGSHIFT));
  proc.put_csr(CSR_MENVCFG, MENVCFG_ADUE);
  events.clear();
  for (unsigned i = 0; i < 2; i++) {
    trapped = false;
    try { mmu->load<uint64_t>(va); }
    catch (trap_load_access_fault&) { trapped = true; }
    assert(trapped && events.empty());
  }
  assert(!mmu->sparse_is_pa_initialized(test_sim::device_base + 8, 8));
  assert(memcmp(sim.device.data() + 8, &device_pte, 8) == 0);
  proc.put_csr(CSR_SATP, 0);
  proc.put_csr(CSR_PMPCFG0, 0);
  assert(!mmu->pmp_ok_api(outside, nullptr, nullptr, 8, LOAD, PRV_S));
  assert(mmu->translate_api(outside, &pa, nullptr, 8, LOAD, 0) != 0);
  proc.set_privilege(PRV_M, false);
  events.clear();
  for (reg_t addr : {test_sim::device_base, reg_t(0x180000000)}) {
    for (unsigned i = 0; i < 2; i++) {
      trapped = false;
      try { mmu->store<uint64_t>(addr, 0xbad); }
      catch (trap_store_access_fault&) { trapped = true; }
      assert(trapped && events.empty() && !mmu->sparse_is_pa_initialized(addr, 8));
    }
    trapped = false;
    try { mmu->cbo_zero(addr); }
    catch (trap_store_access_fault&) { trapped = true; }
    assert(trapped && events.empty());
  }
  assert(mmu->load<uint8_t>(test_sim::device_base) == 0x5a);
  sim.device[0] = 0xab;
  assert(mmu->load<uint8_t>(test_sim::device_base) == 0xab);
  trapped = false;
  try { mmu->sparse_initialize_pa(test_sim::device_base + 1, 0, 1); }
  catch (std::runtime_error&) { trapped = true; }
  assert(trapped && mmu->load<uint16_t>(test_sim::device_base) == 0x5aab);

  test_sim aligned_sim;
  processor_t aligned("rv64imac", "MSU", &aligned_sim.cfg, &aligned_sim, 0, false, nullptr, std::cerr);
  trapped = false;
  try { aligned.get_mmu()->load<uint64_t>(base + 1); }
  catch (trap_load_address_misaligned&) { trapped = true; }
  assert(trapped);
  std::cout << "PASS: host/sparse cold+warm load/store/fetch callbacks, cross-page load, "
               "declared CBO.ZERO, sparse PTE A/D persistence, A/D fault, PMP API, alignment faults, "
               "partial host writes, MMIO rejection without sparse/callback pollution, HLVX flags\n";
}
