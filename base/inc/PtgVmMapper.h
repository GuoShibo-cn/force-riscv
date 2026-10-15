// PTG-backed, published-data-only VmMapper. No native page-table construction.
#ifndef Force_PtgVmMapper_H
#define Force_PtgVmMapper_H

#include <memory>
#include <utility>
#include "VmMapper.h"

namespace Force {
class GenVirtualMemoryRequest;

class PtgVmMapper final : public VmMapper {
public:
  using Span = std::pair<uint64, uint64>; // Half-open.
  PtgVmMapper(Generator* gen, const std::string& library, uint64 handle, uint32 context,
              Span gva, Span gpa, const std::vector<Span>& payload,
              uint64 vsatp, uint64 hgatp, const std::vector<uint64>& layouts);
  ~PtgVmMapper() override;
  uint64 GenerateAddress(const GenVirtualMemoryRequest& request, bool forPA) const;
  void CheckBinding() const;
  uint64 Handle() const { return mHandle; }

  bool GetTranslationRange(uint64 va, TranslationRange& range) const override;
  ETranslationResultType TranslateVaToPa(uint64 va, uint64& pa, uint32& bank) const override;
  ETranslationResultType TranslatePaToVa(uint64 pa, EMemBankType bank, uint64& va) const override;
  bool MapAddressRange(uint64 va, uint64 size, bool instruction,
                       const GenPageRequest* request=nullptr) override;
  uint32 GenContextId() const override { return mContext; }
  uint64 MaxVirtualAddress() const override { return mGva.second - 1; }
  uint64 MaxPhysicalAddress() const override { return (1ull << 56) - 1; }
  EMemBankType DefaultMemoryBank() const override { return EMemBankType(0); }
  bool ValidateContext(std::string& error) const override;
  bool VaInAddressErrorRange(uint64 va) const override;

  // Unsupported generic VmMapper features fail explicitly, never delegate to native paging.
  void AddPhysicalRegion(PhysicalRegion*, bool) override { Unsupported(); }
  void ApplyVirtualUsableConstraint(EMemDataType, EMemAccessType, const AddressReuseMode&,
                                    ConstraintSet*) const override { Unsupported(); }
  void DumpPage(EDumpFormat, std::ofstream&) const override { Unsupported(); }
  void GetVmContextDelta(std::map<std::string, uint64>&) const override { Unsupported(); }
  bool GetPageInfo(uint64, const std::string&, uint32, PageInformation&) const override { Unsupported(); }
  uint64 MapAddressRangeForPA(uint64, EMemBankType, uint64, bool,
                              const GenPageRequest*) override { Unsupported(); }
  ConstraintSet* VirtualUsableConstraintSetClone(bool) override { Unsupported(); }
  RegisterReload* GetRegisterReload() const override { Unsupported(); }
  const AddressTagging* GetAddressTagging() const override { Unsupported(); }
  const ConstraintSet* VirtualUsableConstraintSet(bool) const override { Unsupported(); }
  const ConstraintSet* VirtualSharedConstraintSet() const override { Unsupported(); }
  const ConstraintSet* GetVmConstraint(EVmConstraintType) const override { Unsupported(); }
  const Page* GetPage(uint64) const override { Unsupported(); }
  EExceptionConstraintType GetExceptionConstraintType(const std::string&) const override { Unsupported(); }
  bool VerifyStreamingPageCrossing(uint64, uint64) const override { Unsupported(); }
  void ApplyVmConstraints(const GenPageRequest*, ConstraintSet&) const override { Unsupported(); }
private:
  struct Api;
  struct Range { uint64 va, gpa, pa, size; };
  std::vector<Range> Ranges() const;
  std::vector<uint8> Snapshot(uint64 layout) const;
  [[noreturn]] static void Unsupported();
  std::unique_ptr<Api> mpApi;
  uint64 mHandle;
  uint32 mContext;
  Span mGva, mGpa;
  std::vector<Span> mPayload;
  uint64 mVsatp, mHgatp;
  std::vector<uint64> mLayouts;
  std::vector<std::vector<uint8>> mSnapshots;
};
}
#endif
