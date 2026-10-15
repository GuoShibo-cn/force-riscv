#include <algorithm>
#include <limits>
#include <memory>
#include <stdexcept>
#include <vector>

#include "lest/lest.hpp"
#include "Architectures.h"
#include "ArchInfoRISCV.h"
#include "Config.h"
#include "Constraint.h"
#include "GenRequest.h"
#include "GeneratorRISCV.h"
#include "InstructionResults.h"
#include "Log.h"
#include "MemoryManager.h"
#include "Page.h"
#include "Random.h"
#include "TwoStageTranslationUnit.h"
#include "VmAddressSpaceRISCV.h"
#include "VmGpaAddressSpace.h"
#include "VmUtils.h"

using namespace Force;
using text = std::string;

namespace {

// Substitute only allocation. Page lookup and the composed, cached translation are production code.
template<typename Stage> class TestAddressSpace : public Stage {
public:
  TestAddressSpace(Generator* gen, bool gstage, std::vector<unsigned>& order)
    : Stage(), mGstage(gstage), mOrder(order), mCalls(0), mFailAt(0), mWrongPa(false),
      mInstruction(false), mMaxPhysical(0xffffffffffull), mErrorAddress(~0ull), mTables()
  {
    this->mpGenerator = gen;
    this->mpLookUpPage = new Page();
  }

  void AddPage(uint64 va, uint64 pa, uint64 size = 0x1000, bool addressError = false)
  {
    Page* page = addressError ? new AddressErrorPage() : new Page();
    page->SetBoundary(va, va + size - 1);
    page->SetPhysicalBoundary(pa, pa + size - 1);
    page->SetMemoryBank(EMemBankType::Default);
    this->mPages.push_back(page);
    this->mNoTablePages.push_back(page);
    std::sort(this->mPages.begin(), this->mPages.end(), compare_pages);
  }

  bool MapAddressRange(uint64 va, uint64 size, bool isInstr, const GenPageRequest* req) override
  {
    ++mCalls;
    mOrder.push_back(mGstage);
    if (this->IsTwoStageEnabled()) throw std::runtime_error("unexpected automatic chaining");
    if (mCalls == mFailAt) throw std::runtime_error("injected allocation failure");
    uint64 pa = 0;
    if (!req->GetAttributeValue(EPageRequestAttributeType::PA, pa) ||
        size == 0 || size > 0x1000 - (va & 0xfff) ||
        isInstr != mInstruction || req->InstructionRequest() != isInstr ||
        req->GenBoolAttributeDefaultFalse(EPageGenBoolAttrType::FlatMap) ||
        !req->GenAttributeConstraint(EPageGenAttributeType::Invalid)->ContainsValue(0) ||
        !req->PteAttributeConstraint(EPteAttributeType::G)->ContainsValue(0) ||
        !req->PteAttributeConstraint(EPteAttributeType::U)->ContainsValue(mGstage ? 1 : 0) ||
        !req->PteAttributeConstraint(EPteAttributeType::V)->ContainsValue(1) ||
        !req->PteAttributeConstraint(EPteAttributeType::WR)->ContainsValue(isInstr ? 1 : 3) ||
        !req->PteAttributeConstraint(EPteAttributeType::X)->ContainsValue(isInstr ? 1 : 0) ||
        !req->PteAttributeConstraint(EPteAttributeType::DA)->ContainsValue(3)) {
      throw std::runtime_error("invalid stage request");
    }
    if (this->GetPage(va)) return false; // False means reuse, not mapping failure.
    AddPage(va & ~0xfffull, (pa & ~0xfffull) + (mWrongPa ? 0x1000 : 0));
    return true;
  }

  uint64 MaxPhysicalAddress() const override { return mMaxPhysical; }
  uint64 MaxVirtualAddress() const override { return 0xffffffffffull; }
  bool VaInAddressErrorRange(uint64 va) const override { return va == mErrorAddress; }
  EMemBankType DefaultMemoryBank() const override { return EMemBankType::Default; }
  const ConstraintSet* GetVmConstraint(EVmConstraintType) const override { return &mTables; }

  bool mGstage;
  std::vector<unsigned>& mOrder;
  unsigned mCalls;
  unsigned mFailAt;
  bool mWrongPa;
  bool mInstruction;
  uint64 mMaxPhysical;
  uint64 mErrorAddress;
  ConstraintSet mTables;
};

struct Fixture {
  GeneratorRISCV generator;
  std::vector<unsigned> order;
  TestAddressSpace<VmAddressSpaceRISCV> vs;
  TestAddressSpace<VmGpaAddressSpace> gs;
  TwoStageTranslationUnit unit;
  Fixture() : generator(), order(), vs(&generator, false, order), gs(&generator, true, order),
    unit(&vs, &gs) {}
};

}

const lest::test specification[] = {
  CASE("Nonidentity unaligned mapping spans three granules, G-stage first") {
    Fixture f;
    f.unit.SetupFullTranslation(0x4ff8, 0x12ff8, 0x28ff8, 0x1010, false);
    EXPECT(f.unit.IsEnabled());
    EXPECT(f.order == std::vector<unsigned>({1, 1, 1, 0, 0, 0}));
    for (uint64 offset : {0ull, 7ull, 8ull, 0x1007ull, 0x1008ull, 0x100full}) {
      uint64 pa = 0;
      EXPECT(f.unit.ValidateTranslationChain(0x4ff8 + offset, pa));
      EXPECT(pa == 0x28ff8 + offset);
    }
    EXPECT(f.gs.GetPage(0x4000) == nullptr);
    uint64 pa = 0;
    EXPECT(!f.unit.ValidateTranslationChain(0x7000, pa));
  },
  CASE("Instruction requests and repeated setup reuse identical pages") {
    Fixture f;
    f.vs.mInstruction = f.gs.mInstruction = true;
    f.unit.SetupFullTranslation(0x4000, 0x12000, 0x28000, 8, true);
    uint64 pa = 0;
    EXPECT(f.unit.ValidateTranslationChain(0x4000, pa)); // Populate cache before re-entry.
    f.unit.SetupFullTranslation(0x4000, 0x12000, 0x28000, 8, true);
    EXPECT(f.unit.IsEnabled());
    EXPECT(f.unit.ValidateTranslationChain(0x4000, pa));
    EXPECT(pa == 0x28000u);
  },
  CASE("Reuse existing mixed-size superpages without requiring GVA equal GPA") {
    Fixture f;
    f.vs.AddPage(0x400000, 0x800000, 0x200000);
    f.gs.AddPage(0x800000, 0x1800000);
    f.unit.SetupFullTranslation(0x400ff8, 0x800ff8, 0x1800ff8, 16, false);
    uint64 pa = 0;
    EXPECT(f.unit.ValidateTranslationChain(0x401000, pa));
    EXPECT(pa == 0x1801000u);
  },
  CASE("Conflicts late in either stage fail before any allocation") {
    for (bool gstage : {false, true}) {
      Fixture f;
      if (gstage) f.gs.AddPage(0x13000, 0x99000);
      else f.vs.AddPage(0x5000, 0x99000);
      EXPECT_FAIL(f.unit.SetupFullTranslation(0x4000, 0x12000, 0x28000, 0x2000, false),
                  "two-stage-mapping-conflict");
      EXPECT(f.order.empty());
      EXPECT(!f.unit.IsEnabled());
    }
  },
  CASE("A rejected conflicting extension preserves an already enabled chain") {
    Fixture f;
    f.unit.SetupFullTranslation(0x4000, 0x12000, 0x28000, 8, false);
    EXPECT_FAIL(f.unit.SetupFullTranslation(0x4000, 0x12000, 0x38000, 8, false),
                "two-stage-mapping-conflict");
    uint64 pa = 0;
    EXPECT(f.unit.IsEnabled());
    EXPECT(f.unit.ValidateTranslationChain(0x4000, pa));
    EXPECT(pa == 0x28000u);
  },
  CASE("Null, aliased, unattached and recursively composed stages are rejected") {
    Fixture f;
    TwoStageTranslationUnit missing(nullptr, &f.gs);
    EXPECT_FAIL(missing.SetupFullTranslation(0, 0, 0, 8, false), "two-stage-address-spaces-null");
    f.gs.SetTwoStageEnabled(true);
    EXPECT_FAIL(f.unit.SetupFullTranslation(0, 0, 0, 8, false), "two-stage-invalid-configuration");
    f.gs.SetTwoStageEnabled(false);
    f.gs.VmMapper::Setup(nullptr);
    EXPECT_FAIL(f.unit.SetupFullTranslation(0, 0, 0, 8, false), "two-stage-invalid-configuration");
    TwoStageTranslationUnit aliased(&f.gs, &f.gs);
    EXPECT_FAIL(aliased.SetupFullTranslation(0, 0, 0, 8, false), "two-stage-invalid-configuration");
    EXPECT(f.order.empty());
  },
  CASE("Empty, overflowing and mismatched-offset ranges fail before allocation") {
    Fixture f;
    EXPECT_FAIL(f.unit.SetupFullTranslation(0, 0, 0, 0, false), "two-stage-invalid-range");
    const uint64 max = std::numeric_limits<uint64>::max();
    EXPECT_FAIL(f.unit.SetupFullTranslation(max, 0, 0, 2, false), "two-stage-invalid-range");
    EXPECT_FAIL(f.unit.SetupFullTranslation(0, max, 0, 2, false), "two-stage-invalid-range");
    EXPECT_FAIL(f.unit.SetupFullTranslation(0, 0, max, 2, false), "two-stage-invalid-range");
    EXPECT_FAIL(f.unit.SetupFullTranslation(1, 0, 0, 8, false), "two-stage-offset-mismatch");
    EXPECT_FAIL(f.unit.SetupFullTranslation(0, 0, 1, 8, false), "two-stage-offset-mismatch");
    EXPECT(f.order.empty());
  },
  CASE("Physical limits and address error ranges reject the entire request") {
    Fixture f;
    f.gs.mMaxPhysical = 0x28fff;
    EXPECT_FAIL(f.unit.SetupFullTranslation(0x4000, 0x12000, 0x28000, 0x1001, false),
                "two-stage-address-out-of-range");
    f.vs.mErrorAddress = 0x4fff;
    EXPECT_FAIL(f.unit.SetupFullTranslation(0x4000, 0x12000, 0x28000, 0x1000, false),
                "two-stage-address-out-of-range");
    EXPECT(f.order.empty());
  },
  CASE("An address-error Page is not a successfully mapped leaf") {
    Fixture f;
    f.vs.AddPage(0x4000, 0x12000, 0x1000, true);
    EXPECT_FAIL(f.unit.SetupFullTranslation(0x4000, 0x12000, 0x28000, 8, false),
                "two-stage-mapping-conflict");
    EXPECT(f.order.empty());
  },
  CASE("Allocation failures leave partial pages visible but composition disabled") {
    for (bool gstage : {false, true}) {
      Fixture f;
      if (gstage) f.gs.mFailAt = 2;
      else f.vs.mFailAt = 2;
      EXPECT_FAIL(f.unit.SetupFullTranslation(0x4000, 0x12000, 0x28000, 0x2000, false),
                  "injected allocation failure");
      EXPECT(!f.unit.IsEnabled());
      EXPECT(!f.vs.IsTwoStageEnabled());
      EXPECT(f.gs.GetPage(0x12000) != nullptr);
      uint64 pa = 0;
      EXPECT(!f.unit.ValidateTranslationChain(0x4000, pa));
    }
  },
  CASE("Wrong allocator output cannot enable a falsely successful chain") {
    Fixture f;
    f.gs.mWrongPa = true;
    EXPECT_FAIL(f.unit.SetupFullTranslation(0x4000, 0x12000, 0x28000, 8, false),
                "two-stage-mapping-failed");
    EXPECT(!f.unit.IsEnabled());
    EXPECT(f.vs.mCalls == 0u);
  },
  CASE("Incompatible superpage offsets are rejected before allocator side effects") {
    Fixture f;
    std::unique_ptr<GenPageRequest> req(f.vs.GenPageRequestInstance(false));
    req->SetAttributeValue(EPageRequestAttributeType::PA, 0x801000);
    PageSizeInfo info;
    PageSizeInfo::StringToPageSizeInfo("2M", info);
    std::string error;
    EXPECT(f.vs.CreatePage(0x400000, 8, req.get(), info, error) == nullptr);
    EXPECT(error == "target PA has an incompatible page offset");
    EXPECT(f.vs.GetPage(0x400000) == nullptr);
  },
};

int main(int argc, char* argv[])
{
  Logger::Initialize();
  SET_LOG_LEVEL("error");
  Random::Initialize();
  Config::Initialize();
  Architectures::Initialize();
  std::vector<ArchInfo*> architectures{new ArchInfoRISCV("RISCV")};
  Architectures::Instance()->AssignArchInfoObjects(architectures);
  MemoryManager::Initialize();
  InstructionResults::Initialize();
  int result = lest::run(specification, argc, argv);
  InstructionResults::Destroy();
  MemoryManager::Destroy();
  Architectures::Destroy();
  Config::Destroy();
  Random::Destroy();
  Logger::Destroy();
  return result;
}
