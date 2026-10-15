// Public PTG v1 ABI consumer. PTG remains the only page-table implementation.
#include "PtgVmMapper.h"

#include <algorithm>
#include <cstddef>
#include <dlfcn.h>
#include <stdexcept>
#include "Constraint.h"
#include "Generator.h"
#include "GenRequest.h"
#include "Log.h"
#include "PaGenerator.h"
#include "SimAPI.h"
#include "VmUtils.h"

namespace Force {
namespace {
struct Query {
  uint32 size, version;
  int32 stage, direction, domain;
  uint32 flags;
  uint64 address;
  uint32 reserved0, reserved1;
};
struct Leaf { uint64 va, pa, size; int32 level; uint32 reserved; };
struct Record {
  uint32 size, version, valid;
  int32 stage, input, output, state, observed;
  uint64 tree, observedVa;
  Leaf logical, current;
  uint64 matchedVa, matchedPa, pteAddress, pteValue;
  uint32 perm, pbmt, napot, reserved;
};
static_assert(sizeof(Query) == 40 && sizeof(Record) == 160, "PTG query LP64 ABI");
static_assert(offsetof(Record, current) == 80 && offsetof(Record, perm) == 144, "PTG offsets");
void Check(int32 status, const char* operation) {
  if (status) throw std::runtime_error(std::string("PTG mapper ") + operation +
                                      " status " + std::to_string(status));
}
bool LeafValid(const Record& r, int stage) {
  if (r.size != sizeof(Record) || r.version != 1 || r.stage != stage)
    throw std::runtime_error("PTG mapper query ABI mismatch");
  return (r.valid & 6) == 6 && r.state == 0 && r.current.size && !r.pbmt && !r.napot
    && r.current.va <= UINT64_MAX - r.current.size && r.current.pa <= UINT64_MAX - r.current.size;
}
}

struct PtgVmMapper::Api {
  void* library;
  int32 (*init)(Query*, uint32);
  int32 (*query)(void*, uint32, const Query*, Record*, uint32, uint32, uint32*);
  int32 (*read)(void*, uint64, void*, uint32, uint32, uint8*, uint64, uint32*, uint64*);
  Api(const std::string& path) : library(dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL)),
      init(nullptr), query(nullptr), read(nullptr) {
    if (!library) throw std::runtime_error("PTG mapper cannot load selected library");
    init = reinterpret_cast<decltype(init)>(dlsym(library, "ptg_mapping_query_v1_init"));
    query = reinterpret_cast<decltype(query)>(dlsym(library, "ptg_mapping_query_v1"));
    read = reinterpret_cast<decltype(read)>(dlsym(library, "ptg_export_layout_read_v1"));
    if (!init || !query || !read) {
      dlclose(library);
      throw std::runtime_error("PTG mapper requires Query/Strict Export v1");
    }
  }
  ~Api() { dlclose(library); }
};

PtgVmMapper::PtgVmMapper(Generator* gen, const std::string& library, uint64 handle, uint32 context,
    Span gva, Span gpa, const std::vector<Span>& payload, uint64 vsatp, uint64 hgatp,
    const std::vector<uint64>& layouts)
  : VmMapper(nullptr), mpApi(new Api(library)), mHandle(handle), mContext(context), mGva(gva),
    mGpa(gpa), mPayload(payload), mVsatp(vsatp), mHgatp(hgatp), mLayouts(layouts), mSnapshots() {
  Setup(gen);
  if (!gen || gen->ThreadId() != 0 || !handle || layouts.size() != 2
      || gva.first >= gva.second || gva.second > (1ull << 38)
      || gpa.first >= gpa.second || gpa.second > (1ull << 41) || payload.empty()
      || vsatp >> 60 != 8 || hgatp >> 60 != 8)
    throw std::runtime_error("invalid PTG mapper binding");
  for (const auto& span : payload)
    if (span.first >= span.second || span.second > (1ull << 56))
      throw std::runtime_error("invalid PTG payload ownership span");
  for (auto id : mLayouts) mSnapshots.push_back(Snapshot(id));
  CheckBinding();
  VmMapper::Activate();
}
PtgVmMapper::~PtgVmMapper() = default;

std::vector<uint8> PtgVmMapper::Snapshot(uint64 layout) const {
  uint32 count = 0; uint64 size = 0;
  void* h = reinterpret_cast<void*>(mHandle);
  Check(mpApi->read(h, layout, nullptr, 0, 56, nullptr, 0, &count, &size), "layout preflight");
  std::vector<uint8> records(uint64(count) * 56), data(size);
  uint32 expectedCount = count; uint64 expectedSize = size;
  Check(mpApi->read(h, layout, records.data(), count, 56, data.data(), size, &count, &size), "layout read");
  if (count != expectedCount || size != expectedSize)
    throw std::runtime_error("PTG export changed during serialized read");
  records.insert(records.end(), data.begin(), data.end());
  return records;
}

void PtgVmMapper::CheckBinding() const {
  if (mpGenerator->PrivilegeLevel() != 3)
    throw std::runtime_error("PTG data mapper supports M-mode HLV/HSV only");
  uint64 value = 0, mask = 0;
  auto sim = mpGenerator->GetSimAPI();
  sim->ReadRegister(0, "vsatp", &value, &mask);
  if (value != mVsatp) throw std::runtime_error("PTG vsatp binding changed");
  sim->ReadRegister(0, "hgatp", &value, &mask);
  if (value != mHgatp) throw std::runtime_error("PTG hgatp binding changed");
  sim->ReadRegister(0, "hstatus", &value, &mask);
  if (!(value & 0x100)) throw std::runtime_error("PTG data mapper requires HSTATUS.SPVP=1");
  for (size_t i = 0; i < mLayouts.size(); ++i)
    if (Snapshot(mLayouts[i]) != mSnapshots[i])
      throw std::runtime_error("published PTG mapping changed");
}

std::vector<PtgVmMapper::Range> PtgVmMapper::Ranges() const {
  CheckBinding();
  auto query = [&](int stage) {
    Query q{}; Check(mpApi->init(&q, sizeof(q)), "query init");
    q.stage = stage; q.direction = 2; // CURRENT enumeration, read-only.
    uint32 count = 0;
    void* h = reinterpret_cast<void*>(mHandle);
    Check(mpApi->query(h, mContext, &q, nullptr, 0, sizeof(Record), &count), "query preflight");
    std::vector<Record> records(count);
    const uint32 expected = count;
    if (count) Check(mpApi->query(h, mContext, &q, records.data(), count, sizeof(Record), &count), "query");
    if (count != expected) throw std::runtime_error("PTG query changed during serialized read");
    return records;
  };
  auto vs = query(1), gs = query(2);
  std::vector<Range> ranges;
  for (const auto& v : vs) {
    // Conservative subset: VS supervisor RW, G user RW, A/D set, no PBMT/NAPOT.
    // Query raw_perm is R/W/X/U/G/A/D (U=0x08), unlike add_mapping's U=0x10.
    if (!LeafValid(v, 1) || (v.perm & 0x6b) != 0x63) continue;
    for (const auto& g : gs) {
      if (!LeafValid(g, 2) || (g.perm & 0x6b) != 0x6b) continue;
      uint64 lo = std::max(std::max(v.current.pa, g.current.va), mGpa.first);
      uint64 hi = std::min(std::min(v.current.pa + v.current.size, g.current.va + g.current.size), mGpa.second);
      if (lo >= hi) continue;
      uint64 va = v.current.va + lo - v.current.pa, pa = g.current.pa + lo - g.current.va;
      if (va < mGva.first || va >= mGva.second) continue;
      hi = lo + std::min(hi - lo, mGva.second - va);
      for (const auto& owned : mPayload) {
        uint64 begin = std::max(pa, owned.first), end = std::min(pa + hi - lo, owned.second);
        if (begin < end) ranges.push_back({va + begin - pa, lo + begin - pa, begin, end - begin});
      }
    }
  }
  return ranges;
}

uint64 PtgVmMapper::GenerateAddress(const GenVirtualMemoryRequest& r, bool forPA) const {
  if (r.DataType() != EMemDataType::Data || r.VmSpecified() || r.BankType() != EMemBankType(0)
      || r.ForceNewAddr() || r.ForceAlias() || r.FlatMap() || r.SharedMemory() || r.ForceMemAttrs()
      || !r.CanAlias() || r.PhysPageId() || (r.Tag() <= 255 && r.Tag() != 0)
      || !r.ImplementationMemoryAttributes().empty() || !r.ArchitectureMemoryAttributes().empty()
      || !r.AliasImplementationMemoryAttributes().empty())
    throw std::runtime_error("unsupported request for published PTG data mapper");
  if (!r.Size() || !r.Align() || (r.Align() & (r.Align() - 1)))
    throw std::runtime_error("PTG address size/alignment is invalid");
  // Store admissible START addresses per composed span before union; do not stitch disjoint PAs.
  ConstraintSet starts;
  for (const auto& span : Ranges()) {
    if (span.size < r.Size()) continue;
    ConstraintSet eligible(span.va, span.va + span.size - 1);
    if (r.MemoryRangesConstraint()) eligible.ApplyConstraintSet(*r.MemoryRangesConstraint());
    eligible.AlignWithSize(~(r.Align() - 1), r.Size());
    if (forPA) {
      if (r.PhysAddr() < span.pa || r.PhysAddr() - span.pa > span.size - r.Size()) continue;
      uint64 va = span.va + r.PhysAddr() - span.pa;
      ConstraintSet exact(va, va); eligible.ApplyConstraintSet(exact);
    }
    starts.MergeConstraintSet(eligible);
  }
  PaGenerator selector(&starts);
  uint64 address = selector.GenerateAddress(r.Align(), 1, false, nullptr);
  LOG(notice) << "PTG_DATA_ADDRESS " << (forPA ? "genVAforPA" : "genVA")
              << " vmid=0x" << std::hex << ((mHgatp >> 44) & 0x3fff)
              << " va=0x" << address << std::endl;
  return address;
}

bool PtgVmMapper::GetTranslationRange(uint64 va, TranslationRange& result) const {
  for (const auto& r : Ranges()) if (va >= r.va && va - r.va < r.size) {
    result.SetBoundary(r.va, r.va + r.size - 1);
    result.SetPhysicalBoundary(r.pa, r.pa + r.size - 1);
    result.SetMemoryBank(EMemBankType(0)); result.SetTranslationResult(ETranslationResultType::Mapped);
    return true;
  }
  return false;
}
ETranslationResultType PtgVmMapper::TranslateVaToPa(uint64 va, uint64& pa, uint32& bank) const {
  TranslationRange range;
  if (!GetTranslationRange(va, range)) return ETranslationResultType::NotMapped;
  pa = range.PhysicalLower() + va - range.Lower(); bank = 0;
  return ETranslationResultType::Mapped;
}
ETranslationResultType PtgVmMapper::TranslatePaToVa(uint64 pa, EMemBankType bank, uint64& va) const {
  if (bank != EMemBankType(0)) return ETranslationResultType::NotMapped;
  for (const auto& r : Ranges()) if (pa >= r.pa && pa - r.pa < r.size) {
    va = r.va + pa - r.pa; return ETranslationResultType::Mapped;
  }
  return ETranslationResultType::NotMapped;
}
bool PtgVmMapper::MapAddressRange(uint64 va, uint64 size, bool instruction, const GenPageRequest* request) {
  if (instruction || request) Unsupported();
  TranslationRange r;
  return size && GetTranslationRange(va, r) && size - 1 <= r.Upper() - va;
}
bool PtgVmMapper::VaInAddressErrorRange(uint64 va) const { return va < mGva.first || va >= mGva.second; }
bool PtgVmMapper::ValidateContext(std::string& error) const {
  try { CheckBinding(); return true; }
  catch (const std::exception& e) { error = e.what(); return false; }
}
void PtgVmMapper::Unsupported() { throw std::runtime_error("unsupported PTG VmMapper operation"); }
}
