// See LICENSE for license details.

// Handcar Library Wrapper for Spike (Adapted for Latest Spike API)
// Transforms Spike from CLI executable to shared library for FORCE-RISCV co-simulation.

#include <sys/syscall.h>

#include "sim.h"
#include "mmu.h"
#include "processor.h"
#include "cachesim.h"
#include "cfg.h"
#include "platform.h"
#include "memif.h"
#include "disasm.h"
#include <fesvr/option_parser.h>
#include <fesvr/elfloader.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <vector>
#include <string>
#include <memory>
#include <cstring>
#include <iomanip>
#include <map>
#include <sstream>
#include <functional>
#include <sys/syscall.h>

#include "handcar_cosim_wrapper.h"

// FORCE callbacks - implemented in FORCE's SimApiHANDCAR.cc, resolved at runtime
extern "C" {
    void update_generator_register(uint32_t cpuid, const char* pRegisterName, uint64_t value, uint64_t mask, const char* pAccessType);
}

// Sparse Memory Implementation
// Replaces dense mem_t with byte-granular map for partial initialization
class sparse_mem_t : public abstract_mem_t {
public:
    sparse_mem_t() : size_val(0) {}
    sparse_mem_t(reg_t sz) : size_val(sz) {}
    
    bool load(reg_t addr, size_t len, uint8_t* bytes) override {
        for (size_t i = 0; i < len; i++) {
            auto it = mem.find(addr + i);
            bytes[i] = (it != mem.end()) ? it->second : 0;
        }
        return true;
    }
    bool store(reg_t addr, size_t len, const uint8_t* bytes) override {
        for (size_t i = 0; i < len; i++) {
            mem[addr + i] = bytes[i];
        }
        return true;
    }
    reg_t size() override { return size_val; }
    char* contents(reg_t addr) override { return nullptr; }
    void dump(std::ostream& o) override {}
    
private:
    std::map<reg_t, uint8_t> mem;
    reg_t size_val;
};

// Simulator lifecycle objects
static sim_t* _pSimulator = nullptr;
static cfg_t* _pCfg = nullptr;
static std::unique_ptr<icache_sim_t> ic;
static std::unique_ptr<dcache_sim_t> dc;
static std::unique_ptr<cache_sim_t> l2;
static std::vector<std::pair<reg_t, abstract_mem_t*>> _mems; // Keep track of memory for direct access

// Helper: CSR name to Number mapping
// In latest Spike, CSRs are accessed by number. We map common names here.
static std::map<std::string, int> _csr_name_map;
static void init_csr_map() {
    if (!_csr_name_map.empty()) return;
    // Machine
    _csr_name_map["mstatus"] = 0x300;
    _csr_name_map["misa"] = 0x301;
    _csr_name_map["medeleg"] = 0x302;
    _csr_name_map["mideleg"] = 0x303;
    _csr_name_map["mie"] = 0x304;
    _csr_name_map["mtvec"] = 0x305;
    _csr_name_map["mcounteren"] = 0x306;
    _csr_name_map["mstatush"] = 0x310;
    _csr_name_map["menvcfg"] = 0x30A;
    _csr_name_map["menvcfgh"] = 0x31A;
    _csr_name_map["mcountinhibit"] = 0x320;
    _csr_name_map["mscratch"] = 0x340;
    _csr_name_map["mepc"] = 0x341;
    _csr_name_map["mcause"] = 0x342;
    _csr_name_map["mtval"] = 0x343;
    _csr_name_map["mip"] = 0x344;
    _csr_name_map["mtinst"] = 0x34A;
    _csr_name_map["mtval2"] = 0x34B;
    // PMP CSRs
    for (int i = 0; i < 16; i++) {
        char name[20];
        snprintf(name, sizeof(name), "pmpcfg%d", i);
        _csr_name_map[name] = 0x3A0 + i;
    }
    for (int i = 0; i < 64; i++) {
        char name[20];
        snprintf(name, sizeof(name), "pmpaddr%d", i);
        _csr_name_map[name] = 0x3B0 + i;
    }
    // Supervisor
    _csr_name_map["sstatus"] = 0x100;
    _csr_name_map["sie"] = 0x104;
    _csr_name_map["stvec"] = 0x105;
    _csr_name_map["scounteren"] = 0x106;
    _csr_name_map["senvcfg"] = 0x10A;
    _csr_name_map["sscratch"] = 0x140;
    _csr_name_map["sepc"] = 0x141;
    _csr_name_map["scause"] = 0x142;
    _csr_name_map["stval"] = 0x143;
    _csr_name_map["sip"] = 0x144;
    _csr_name_map["satp"] = 0x180;
    // FPU CSRs
    _csr_name_map["fflags"] = 0x1;
    _csr_name_map["frm"] = 0x2;
    _csr_name_map["fcsr"] = 0x3;
    // Hypervisor
    _csr_name_map["hstatus"] = 0x600;
    _csr_name_map["hedeleg"] = 0x602;
    _csr_name_map["hideleg"] = 0x603;
    _csr_name_map["hie"] = 0x604;
    _csr_name_map["hcounteren"] = 0x606;
    _csr_name_map["hgeie"] = 0x607;
    _csr_name_map["htval"] = 0x643;
    _csr_name_map["hip"] = 0x644;
    _csr_name_map["hvip"] = 0x645;
    _csr_name_map["htinst"] = 0x64A;
    _csr_name_map["hgatp"] = 0x680;
    _csr_name_map["hgeip"] = 0xE12;
    _csr_name_map["vsstatus"] = 0x200;
    _csr_name_map["vsie"] = 0x204;
    _csr_name_map["vstvec"] = 0x205;
    _csr_name_map["vsscratch"] = 0x240;
    _csr_name_map["vsepc"] = 0x241;
    _csr_name_map["vscause"] = 0x242;
    _csr_name_map["vstval"] = 0x243;
    _csr_name_map["vsip"] = 0x244;
    _csr_name_map["vsatp"] = 0x280;
    // M-mode identification
    _csr_name_map["mvendorid"] = 0xF11;
    _csr_name_map["marchid"] = 0xF12;
    _csr_name_map["mimpid"] = 0xF13;
    _csr_name_map["mhartid"] = 0xF14;
    _csr_name_map["mconfigptr"] = 0xF15;
    // Vector CSRs
    _csr_name_map["vstart"] = 0x008;
    _csr_name_map["vxsat"] = 0x009;
    _csr_name_map["vxrm"] = 0x00A;
    _csr_name_map["vcsr"] = 0x00F;
    _csr_name_map["vl"] = 0xC20;
    _csr_name_map["vtype"] = 0xC21;
    _csr_name_map["vlenb"] = 0xC22;
    // Counters
    _csr_name_map["cycle"] = 0xC00;
    _csr_name_map["time"] = 0xC01;
    _csr_name_map["instret"] = 0xC02;
    for (int i = 3; i <= 31; i++) {
        char name[20];
        snprintf(name, sizeof(name), "hpmcounter%d", i);
        _csr_name_map[name] = 0xC00 + i;
    }
    _csr_name_map["cycleh"] = 0xC80;
    _csr_name_map["timeh"] = 0xC81;
    _csr_name_map["instreth"] = 0xC82;
    for (int i = 3; i <= 31; i++) {
        char name[20];
        snprintf(name, sizeof(name), "hpmcounter%dh", i);
        _csr_name_map[name] = 0xC80 + i;
    }
}

static int get_csr_no(const std::string& name) {
    init_csr_map();
    auto it = _csr_name_map.find(name);
    if (it != _csr_name_map.end()) return it->second;
    return -1;
}

// Helper: XPR index
static int get_xpr_idx(const std::string& name) {
    if (name.size() < 2) return -1;
    char c = name[0];
    char n = name[1];
    if (c == 'x' || c == 'X') {
        if (n >= '0' && n <= '9') return n - '0';
        if (n == '1' && name.size() > 2) {
            if (name[2] == '0') return 10;
            if (name[2] == '1') return 11;
            if (name[2] == '2') return 12;
            if (name[2] == '3') return 13;
            if (name[2] == '4') return 14;
            if (name[2] == '5') return 15;
            if (name[2] == '6') return 16;
            if (name[2] == '7') return 17;
            if (name[2] == '8') return 18;
            if (name[2] == '9') return 19;
        }
    }
    // ABI names
    if (name == "zero" || name == "x0") return 0;
    if (name == "ra" || name == "x1") return 1;
    if (name == "sp" || name == "x2") return 2;
    if (name == "gp" || name == "x3") return 3;
    if (name == "tp" || name == "x4") return 4;
    if (name == "t0" || name == "x5") return 5;
    if (name == "t1" || name == "x6") return 6;
    if (name == "t2" || name == "x7") return 7;
    if (name == "s0" || name == "fp" || name == "x8") return 8;
    if (name == "s1" || name == "x9") return 9;
    if (name == "a0" || name == "x10") return 10;
    if (name == "a1" || name == "x11") return 11;
    if (name == "a2" || name == "x12") return 12;
    if (name == "a3" || name == "x13") return 13;
    if (name == "a4" || name == "x14") return 14;
    if (name == "a5" || name == "x15") return 15;
    if (name == "a6" || name == "x16") return 16;
    if (name == "a7" || name == "x17") return 17;
    if (name == "s2" || name == "x18") return 18;
    if (name == "s3" || name == "x19") return 19;
    if (name == "s4" || name == "x20") return 20;
    if (name == "s5" || name == "x21") return 21;
    if (name == "s6" || name == "x22") return 22;
    if (name == "s7" || name == "x23") return 23;
    if (name == "s8" || name == "x24") return 24;
    if (name == "s9" || name == "x25") return 25;
    if (name == "s10" || name == "x26") return 26;
    if (name == "s11" || name == "x27") return 27;
    if (name == "t3" || name == "x28") return 28;
    if (name == "t4" || name == "x29") return 29;
    if (name == "t5" || name == "x30") return 30;
    if (name == "t6" || name == "x31") return 31;
    return -1;
}

// Stored parsed options for sim_t construction
static bool _halted = false;
static bool _log = false;
static std::string _log_path;
static std::string _isa_str = DEFAULT_ISA;
static std::string _varch_str;
static std::vector<size_t> _hartids = {0};
static reg_t _start_pc = reg_t(-1);
static bool _auto_init_mem = false;
static bool _dtb_enabled = true;
static std::vector<device_factory_sargs_t> _plugin_devices;

// Parse options string into argv/argc for option_parser_t compatibility
static int _parse_options(const char* options, std::vector<std::string>& out_storage) {
    // Prepend "handcar_cosim" as argv[0]
    out_storage.push_back("handcar_cosim");
    
    if (options && strlen(options) > 0) {
        std::istringstream iss(options);
        std::string token;
        while (iss >> token) {
            out_storage.push_back(token);
        }
    }
    
    return (int)out_storage.size();
}

extern "C" {

void initialize_simulator(const char* options) {
    // Cleanup existing simulator if present
    if (_pSimulator) { delete _pSimulator; _pSimulator = nullptr; }
    if (_pCfg) { delete _pCfg; _pCfg = nullptr; }
    _halted = false; _log = false; _log_path.clear();
    _isa_str = DEFAULT_ISA; _varch_str.clear();
    _hartids = {0}; _start_pc = reg_t(-1); _auto_init_mem = false;
    _dtb_enabled = true; _plugin_devices.clear();
    
    // Parse options
    std::vector<std::string> storage;
    int argc = _parse_options(options, storage);
    
    // Build argv (must be after storage is fully populated to avoid invalidating c_str pointers)
    std::vector<const char*> argv_vec;
    argv_vec.reserve(argc + 1);
    for (auto& s : storage) {
        argv_vec.push_back(s.c_str());
    }
    argv_vec.push_back(nullptr);  // NULL terminator required by option_parser_t::parse
    const char** argv = argv_vec.data();
    
    // Parse with option_parser_t (same as Spike main)
    bool debug = false;
    bool histogram = false;
    const char* varch = "vlen:128,slen:128,elen:64";  // default varch
    const char* isa = DEFAULT_ISA;
    const char* priv = DEFAULT_PRIV;
    size_t nprocs = 1;
    bool dump_dts = false;
    bool socket = false;
    unsigned dmi_rti = 0;
    reg_t start_pc = reg_t(-1);
    bool log_cache = false;
    const char* dtb_file = nullptr;
    bool use_rbb = false;
    int rbb_port = 0;
    FILE* cmd_file = NULL;
    
    // Device factory args
    std::vector<device_factory_sargs_t> plugin_device_factories;
    
    option_parser_t parser;
    parser.option('d', 0, 0, [&](const char* s){ debug = true; });
    parser.option('g', 0, 0, [&](const char* s){ histogram = true; });
    parser.option('l', 0, 0, [&](const char* s){ _log = true; });
    parser.option('p', 0, 1, [&](const char* s){ nprocs = atoi(s); });
    parser.option('H', 0, 0, [&](const char* s){ _halted = true; });
    parser.option(0, "pc", 1, [&](const char* s){ start_pc = strtoull(s, 0, 0); });
    parser.option(0, "hartids", 1, [&](const char* s){
        std::istringstream iss(s);
        std::string token;
        _hartids.clear();
        while (std::getline(iss, token, ',')) {
            _hartids.push_back(std::stoul(token));
        }
    });
    parser.option(0, "ic", 1, [&](const char* s){ ic.reset(new icache_sim_t(s)); });
    parser.option(0, "dc", 1, [&](const char* s){ dc.reset(new dcache_sim_t(s)); });
    parser.option(0, "l2", 1, [&](const char* s){ l2.reset(cache_sim_t::construct(s, "L2$")); });
    parser.option(0, "log-cache-miss", 0, [&](const char* s){ log_cache = true; });
    parser.option(0, "auto-init-mem", 0, [&](const char* s){ _auto_init_mem = true; });
    parser.option(0, "isa", 1, [&](const char* s){ isa = s; });
    parser.option(0, "priv", 1, [&](const char* s){ priv = s; });
    parser.option(0, "varch", 1, [&](const char* s){ varch = s; });
    parser.option(0, "pmpregions", 1, [&](const char* s){});
    parser.option(0, "pmpgranularity", 1, [&](const char* s){});
    parser.option(0, "dump-dts", 0, [&](const char* s){ dump_dts = true; });
    parser.option(0, "disable-dtb", 0, [&](const char* s){ _dtb_enabled = false; });
    parser.option(0, "dtb", 1, [&](const char* s){ dtb_file = s; });
    parser.option(0, "extlib", 1, [&](const char* s){
        void* lib = dlopen(s, RTLD_NOW | RTLD_GLOBAL);
        if (!lib) { fprintf(stderr, "Unable to load extlib '%s': %s\n", s, dlerror()); exit(-1); }
    });
    parser.option(0, "device", 1, [&](const char* s){
        // Skip device parsing for now - FORCE doesn't use plugin devices
        (void)s;
    });
    parser.option(0, "log", 1, [&](const char* s){ _log_path = s; });
    parser.option(0, "debug-cmd", 1, [&](const char* s){
        cmd_file = fopen(s, "r");
        if (!cmd_file) { fprintf(stderr, "Unable to open command file '%s'\n", s); exit(-1); }
    });
    parser.option(0, "instructions", 1, [&](const char* s){});
    parser.option(0, "rbb-port", 1, [&](const char* s){ rbb_port = atoi(s); use_rbb = true; });
    parser.option(0, "dm-progsize", 1, [&](const char* s){});
    parser.option(0, "dm-sba", 1, [&](const char* s){});
    parser.option(0, "dm-auth", 0, [&](const char* s){});
    parser.option(0, "dmi-rti", 1, [&](const char* s){ dmi_rti = atoi(s); });
    parser.option(0, "dm-abstract-rti", 1, [&](const char* s){});
    parser.option(0, "dm-no-hasel", 0, [&](const char* s){});
    parser.option(0, "dm-no-abstract-csr", 0, [&](const char* s){});
    parser.option(0, "dm-no-halt-groups", 0, [&](const char* s){});

    auto argv1 = parser.parse(argv);

    // Apply parsed options to cfg
    _isa_str = isa;
    _varch_str = varch;
    _start_pc = start_pc;
    _plugin_devices = plugin_device_factories;
    
    // If hartids not explicitly set, create default based on nprocs
    if (_hartids.empty()) {
        _hartids.resize(nprocs);
        for (size_t i = 0; i < nprocs; i++) _hartids[i] = i;
    }
    
    // Create cfg_t
    _pCfg = new cfg_t();
    _pCfg->isa = isa;  // String lifetime managed by storage vector
    _pCfg->priv = priv;
    _pCfg->misaligned = true;  // FORCE needs misaligned access support
    _pCfg->endianness = endianness_little;
    _pCfg->pmpregions = 16;
    _pCfg->pmpgranularity = 4;  // Must be power of 2 and >= 4
    _pCfg->hartids = _hartids;
    _pCfg->explicit_hartids = false;
    _pCfg->real_time_clint = false;
    _pCfg->trigger_count = 4;
    _pCfg->cache_blocksz = 0;
    _pCfg->start_pc = (start_pc != reg_t(-1)) ? std::make_optional(start_pc) : std::nullopt;
    
    // Default memory already set by cfg_t constructor (2GB at DRAM_BASE)
    // No need to add again - cfg_t::cfg() already initializes mem_layout
    
    // Create debug module config
    debug_module_config_t dm_config = {
        .progbufsize = 2,
        .max_sba_data_width = 0,
        .require_authentication = false,
        .abstract_rti = 0,
        .support_hasel = true,
        .support_abstract_csr_access = true,
        .support_abstract_fpr_access = true,
        .support_haltgroups = true,
        .support_impebreak = true
    };
    
    // Create memory objects (Sparse for partial initialization support)
    _mems.clear();
    std::vector<std::pair<reg_t, abstract_mem_t*>> mems;
    for (auto& m : _pCfg->mem_layout) {
        auto mem = new sparse_mem_t(m.get_size());
        mems.push_back(std::make_pair(m.get_base(), mem));
        _mems.push_back(std::make_pair(m.get_base(), mem));
    }
    
    // Build args for htif - use "none" to skip automatic ELF loading
    // (FORCE loads ELF separately via simulator_load_elf)
    std::vector<std::string> htif_args;
    htif_args.push_back("none");  // targs[0] = "none" skips load_program() in htif_t::start()
    
    // Create sim_t
    _pSimulator = new sim_t(_pCfg, _halted, mems, _plugin_devices, htif_args,
                           dm_config, _log_path.empty() ? nullptr : _log_path.c_str(),
                           _dtb_enabled, dtb_file,
                           socket, cmd_file, std::nullopt);
    
    // Register cache memtracers
    if (ic && l2) ic->set_miss_handler(&*l2);
    if (dc && l2) dc->set_miss_handler(&*l2);
    if (ic) ic->set_log(log_cache);
    if (dc) dc->set_log(log_cache);
    for (size_t i = 0; i < _pCfg->nprocs(); i++) {
        if (ic) _pSimulator->get_core(i)->get_mmu()->register_memtracer(&*ic);
        if (dc) _pSimulator->get_core(i)->get_mmu()->register_memtracer(&*dc);
    }
    
    _pSimulator->set_debug(debug);
    _pSimulator->set_histogram(histogram);
    
    // Initialize CSR map
    init_csr_map();
}

void terminate_simulator() {
    if (_pSimulator) {
        delete _pSimulator;
        _pSimulator = nullptr;
    }
    if (_pCfg) {
        delete _pCfg;
        _pCfg = nullptr;
    }
}

int step_simulator(int target_id, int num_steps, int stx_failed) {
    if (!_pSimulator) return 1;
    processor_t* proc = _pSimulator->get_core(target_id);
    if (!proc) return 1;
    
    for (int i = 0; i < num_steps; i++) {
        uint64_t pc_before = proc->get_state()->pc;
        mmu_t* mmu = proc->get_mmu();
        uint64_t sparse_word = 0;
        bool sparse_ok = false;
        try {
            sparse_ok = mmu->sparse_is_pa_initialized(pc_before, 4);
            if (sparse_ok) sparse_word = mmu->sparse_read(pc_before, 4);
        } catch (...) {}

        auto read_csr_dbg = [&](uint64_t csr_no) -> uint64_t {
            auto it = proc->get_state()->csrmap.find(csr_no);
            return (it != proc->get_state()->csrmap.end()) ? it->second->read() : 0xdeadbeefdeadbeefULL;
        };
        uint64_t mtvec_before = read_csr_dbg(0x305);
        uint64_t mstatus_before = read_csr_dbg(0x300);
        fprintf(stderr, "[STEPDBG] before pc=0x%lx sparse_ok=%d sparse_word=0x%08lx mtvec=0x%lx mstatus=0x%lx prv=%u virt=%d\n",
                (unsigned long)pc_before, sparse_ok ? 1 : 0, (unsigned long)sparse_word,
                (unsigned long)mtvec_before, (unsigned long)mstatus_before,
                (unsigned)proc->get_state()->prv, proc->get_state()->v ? 1 : 0);

        try {
            proc->step(1);
        } catch (const std::exception& e) {
            fprintf(stderr, "[STEP] Exception during step: %s (pc_before=0x%lx)\n", e.what(), (unsigned long)pc_before);
            proc->get_state()->pc = pc_before + 4;
        } catch (...) {
            fprintf(stderr, "[STEP] Unknown exception during step (pc_before=0x%lx)\n", (unsigned long)pc_before);
            proc->get_state()->pc = pc_before + 4;
        }
        uint64_t pc_after = proc->get_state()->pc;
        uint64_t mcause_after = read_csr_dbg(0x342);
        uint64_t mepc_after = read_csr_dbg(0x341);
        uint64_t mtval_after = read_csr_dbg(0x343);
        fprintf(stderr, "[STEPDBG] after pc=0x%lx mcause=0x%lx mepc=0x%lx mtval=0x%lx\n",
                (unsigned long)pc_after, (unsigned long)mcause_after, (unsigned long)mepc_after, (unsigned long)mtval_after);
        
        fprintf(stderr, "[STEP] target_id=%d pc 0x%lx -> 0x%lx\n", target_id, (unsigned long)pc_before, (unsigned long)pc_after);
        update_generator_register(target_id, "PC", pc_after, 0xFFFFFFFFFFFFFFFFULL, "write");
    }
    return 0;
}

int read_simulator_register(uint32_t target_id, const char* pRegName, uint64_t* pValue, uint64_t* mask) {
    if (!_pSimulator || !pRegName || !pValue) return 1;
    processor_t* p = _pSimulator->get_core(target_id);
    if (!p) return 1;
    
    std::string name(pRegName);
    
    // Handle PC specially
    if (name == "PC" || name == "pc") {
        *pValue = p->get_state()->pc;
        *mask = 0xFFFFFFFFFFFFFFFF;
        return 0;
    }

    if (name == "vlenb") {
        *pValue = p->VU.vlenb;
        *mask = 0xFFFFFFFFFFFFFFFF;
        return 0;
    }
    
    int csr_no = get_csr_no(name);
    if (csr_no >= 0) {
        try {
            *pValue = p->get_csr(csr_no);
            *mask = 0xFFFFFFFFFFFFFFFF;
            return 0;
        } catch (...) {}
    }
    
    int xpr_idx = get_xpr_idx(name);
    if (xpr_idx >= 0 && xpr_idx < 32) {
        try {
            *pValue = p->get_state()->XPR[xpr_idx];
            *mask = 0xFFFFFFFFFFFFFFFF;
            return 0;
        } catch (...) {}
    }

    return 1;
}

int write_simulator_register(uint32_t target_id, const char* pRegName, uint64_t value, uint64_t mask) {
    if (!_pSimulator || !pRegName) return 1;
    processor_t* p = _pSimulator->get_core(target_id);
    if (!p) return 1;

    reg_t val = value;
    std::string name(pRegName);
    int csr_no = get_csr_no(name);
    
    fprintf(stderr, "[WRITE_REG] name=%s csr_no=0x%x value=0x%lx mask=0x%lx\n", name.c_str(), csr_no, (unsigned long)val, (unsigned long)mask);
    
    // Handle PC specially
    if (name == "PC" || name == "pc") {
        p->get_state()->pc = val;
        return 0;
    }
    
    // Handle privilege (internal FORCE register, not a real CSR)
    // Just accept the value, no action needed in Spike
    if (name == "privilege" || name == "PRIVILEGE") {
        return 0;
    }
    
    if (csr_no >= 0) {
        auto it = p->get_state()->csrmap.find(csr_no);
        if (it != p->get_state()->csrmap.end()) {
            // Mask value for small CSRs to avoid assertion failures in newer Spike
            if (csr_no < 0x1000 && (csr_no == 0x3 || csr_no == 0x1 || csr_no == 0x2)) {
                val &= 0xFFFFFFFF;
            }
            
            // Workaround: Newer Spike aborts if writing to FPU CSRs when sstatus.FS is Off.
            if (csr_no == 0x3 || csr_no == 0x1 || csr_no == 0x2) {
                auto sstatus_it = p->get_state()->csrmap.find(0x100);
                if (sstatus_it != p->get_state()->csrmap.end()) {
                    reg_t sstatus_val = sstatus_it->second->read();
                    reg_t fs_mask = 0x6000;
                    if ((sstatus_val & fs_mask) == 0) {
                        sstatus_it->second->write((sstatus_val & ~fs_mask) | 0x2000);
                    }
                }
                auto vsstatus_it = p->get_state()->csrmap.find(0x200);
                if (vsstatus_it != p->get_state()->csrmap.end()) {
                    reg_t vsstatus_val = vsstatus_it->second->read();
                    reg_t fs_mask = 0x6000;
                    if ((vsstatus_val & fs_mask) == 0) {
                        vsstatus_it->second->write((vsstatus_val & ~fs_mask) | 0x2000);
                    }
                }
            }
            
            // MSTATUS: mask out bits that would affect fetch behavior during init:
            // MPRV(17), MXR(19), TVM(20), TW(21), TSR(22)
            // These should not affect how the ISS fetches the first instruction.
            if (csr_no == 0x300) {  // mstatus
                val &= ~(reg_t(0x7U << 19));  // clear MXR(19)+TVM(20)+TW(21)
                val &= ~(reg_t(0x1U << 22));  // clear TSR(22)
                val &= ~(reg_t(0x1U << 17));  // clear MPRV(17) - critical!
            }
            
            try {
                it->second->write(val);
                fprintf(stderr, "[WRITE_CSR] csr_no=0x%x written=0x%lx readback=0x%lx\n", csr_no, (unsigned long)val, (unsigned long)it->second->read());
            } catch (...) {
                fprintf(stderr, "[WRITE_CSR] csr_no=0x%x write exception\n", csr_no);
                return 1;
            }
            
            return 0;
        }
    }
    
    int xpr_idx = get_xpr_idx(name);
    if (xpr_idx >= 0 && xpr_idx < 32) {
        p->get_state()->XPR.write(xpr_idx, val);
        fprintf(stderr, "[DEBUG] WriteReg %s (x%d) = 0x%lx, readback=0x%lx\n", name.c_str(), xpr_idx, val, (reg_t)p->get_state()->XPR[xpr_idx]);
        return 0;
    }

    return 1;
}

int read_simulator_memory(int target_id, const uint64_t* addr, int length, uint8_t* data) {
    if (!_pSimulator || !addr || !data) return 1;
    processor_t* p = _pSimulator->get_core(target_id);
    if (!p) return 1;
    
    try {
        mmu_t* mmu = p->get_mmu();
        // Use sparse read or standard load
        // Standard load might trap if not initialized.
        // We should use sparse read if available.
        if (mmu->sparse_is_pa_initialized(*addr, length)) {
            mmu->sparse_read_partially_initialized(*addr, length, data);
        } else {
            // Fallback to normal load (may trap)
            // mmu->load_slow_path(*addr, length, data, 0); // access_info needed
        }
        return 0;
    } catch (...) { return 1; }
}

int write_simulator_memory(int target_id, const uint64_t* addr, int length, const uint8_t* data) {
    if (!_pSimulator || !addr || !data) return 1;
    processor_t* p = _pSimulator->get_core(target_id);
    if (!p) return 1;

    fprintf(stderr, "[WRITE_SIM_MEM] addr=0x%lx len=%d bytes=", (unsigned long)*addr, length);
    for (int i = 0; i < length && i < 16; i++) fprintf(stderr, "%02x", data[i]);
    if (length > 16) fprintf(stderr, "...");
    fprintf(stderr, "\n");

    try {
        mmu_t* mmu = p->get_mmu();
        mmu->sparse_write(*addr, data, length);
        mmu->flush_tlb();
        mmu->flush_icache();
        return 0;
    } catch (...) { return 1; }
}

int translate_virtual_address(int target_id, const uint64_t* vaddr, int intent, uint64_t* paddr, uint64_t* memattrs) {
    if (!_pSimulator || !vaddr || !paddr) return 1;
    processor_t* p = _pSimulator->get_core(target_id);
    if (!p) return 1;

    try {
        mmu_t* mmu = p->get_mmu();
        reg_t pa = 0;
        int res = mmu->translate_api(*vaddr, &pa, nullptr, 8, (access_type)intent, 0);
        if (res == 0) {
            *paddr = pa;
            if (memattrs) *memattrs = 0;
            return 0;
        }
        return 1; // Fault
    } catch (...) { return 1; }
}

int set_simulator_parameter(const char* name, const uint64_t* pValue, const char* path) {
    // Placeholder for parameter setting
    return 0;
}

int get_simulator_version(char* version) {
    const char version_string[] = "2.0\0";
    if(version == nullptr) return 1;
    strcpy(version, version_string);
    return 0;
}

int get_disassembly_for_target(int target_id, const uint64_t* pc, char** opcode, char** disassembly) {
    if (!_pSimulator || !pc || !opcode || !disassembly) return 1;
    
    processor_t* proc = _pSimulator->get_core(target_id);
    if (!proc) return 1;
    
    try {
        const disassembler_t* disassembler = proc->get_disassembler();
        insn_fetch_t fetched = proc->get_mmu()->load_insn(*pc);
        
        uint64_t opcode_num = fetched.insn.bits() & ((1ull << (8 * insn_length(fetched.insn.bits()))) - 1);
        std::string disassembly_str = disassembler->disassemble(fetched.insn);
        
        std::stringstream stream;
        stream << "0x" << std::hex << opcode_num;
        std::string opcode_str = stream.str();
        
        *opcode = strdup(opcode_str.c_str());
        *disassembly = strdup(disassembly_str.c_str());
        
        return 0;
    } catch(...) {
        *opcode = strdup("00000000");
        *disassembly = strdup("?");
        return 1;
    }
}

int get_disassembly(const uint64_t* pc, char** opcode, char** disassembly) {
    return get_disassembly_for_target(0, pc, opcode, disassembly);
}

int partial_read_large_register(int target_id, const char* pRegName, uint8_t* pValue, uint32_t length, uint32_t offset) {
    if (!pRegName || !pValue || !_pSimulator) return 1;
    // Stub: zero out the buffer
    memset(pValue, 0, length);
    return 0;
}

int partial_write_large_register(int target_id, const char* pRegName, const uint8_t* pValue, uint32_t length, uint32_t offset) {
    if (!pRegName || !pValue || !_pSimulator) return 1;
    return 0; // Stub
}

int inject_simulator_events(uint32_t target_id, uint32_t event_mask) {
    return 0; // Stub: no events to inject
}

int read_simulator_register_fpix(uint32_t target_id, const char* registerName, uint64_t* pValue, uint64_t* mask) {
    return read_simulator_register(target_id, registerName, pValue, mask);
}

int write_simulator_register_fpix(uint32_t target_id, const char* registerName, uint64_t value, uint64_t mask) {
    return write_simulator_register(target_id, registerName, value & mask, 0xFFFFFFFFFFFFFFFF);
}

int initialize_simulator_memory(int target_id, const uint64_t* addr, int length, uint64_t data) {
    if (!_pSimulator || !addr) return 1;
    if (length < 0 || length > 8) return 2;
    
    // Write directly to mmu's sparse memory map
    processor_t* proc = _pSimulator->get_core(target_id);
    if (!proc) return 1;
    
    mmu_t* mmu = proc->get_mmu();
    mmu->sparse_initialize_pa(static_cast<reg_t>(*addr), data, static_cast<size_t>(length));
    
    // Debug: log instruction writes (4-byte writes are typically instructions)
    if (length == 4) {
        fprintf(stderr, "[INIT_MEM] target_id=%d addr=0x%lx data=0x%lx\n", target_id, (unsigned long)*addr, (unsigned long)data);
    }
    return 0;
}

} // extern "C"
