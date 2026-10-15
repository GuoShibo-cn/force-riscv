//
// Copyright (C) [2020] Futurewei Technologies, Inc.
//
// FORCE-RISCV is licensed under the Apache License, Version 2.0 (the "License");
//  you may not use this file except in compliance with the License.
//  You may obtain a copy of the License at
//
//  http://www.apache.org/licenses/LICENSE-2.0
//
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR
// FIT FOR A PARTICULAR PURPOSE.
// See the License for the specific language governing permissions and
// limitations under the License.
//
#include "GenExceptionAgentRISCV.h"

#include <memory>
#include <sstream>

#include "AddressTable.h"
#include "AddressTableManager.h"
#include "Choices.h"
#include "ChoicesModerator.h"
#include "Config.h"
#include "DataBlock.h"
#include "DataStation.h"
#include "Enums.h"
#include "ExceptionManager.h"
#include "GenRequest.h"
#include "GenPC.h"
#include "Generator.h"
#include "Log.h"
#include "PageRequestRegulator.h"
#include "PeStateUpdate.h"
#include "Random.h"
#include "Register.h"
#include "RegisterReload.h"
#include "StringUtils.h"
#include "SwitchPrivilegeSolverRISCV.h"
#include "UtilityFunctionsRISCV.h"
#include "VmInfo.h"
#include "VmManager.h"
#include "VmMapper.h"
#include ARCH_ENUM_HEADER

using namespace std;

/*!
  \file GenExceptionAgentRISCV.cc
  \brief Code handling exception related requests.
*/

namespace Force {

  GenExceptionAgentRISCV::GenExceptionAgentRISCV()
    : GenExceptionAgent(), mArgRegIndices(), mFastMode(false), mAddrTableEC(),
      mCachedHedeleg(0), mCachedHideleg(0), mHedelegCached(false), mHidelegCached(false)
  { }

  GenExceptionAgentRISCV::GenExceptionAgentRISCV(const GenExceptionAgentRISCV& rOther)
    : GenExceptionAgent(rOther), mArgRegIndices(), mFastMode(false), mAddrTableEC(),
      mCachedHedeleg(0), mCachedHideleg(0), mHedelegCached(false), mHidelegCached(false)
  { }

  Object* GenExceptionAgentRISCV::Clone() const
  {
    return new GenExceptionAgentRISCV(*this);
  }

  bool GenExceptionAgentRISCV::IsExceptionReturn(const GenExceptionRequest* pExceptReq) const
  {
    auto except_req = mpExceptionRequest->CastInstance<GenHandleException>();
    if (except_req->Id() == 0x4e)
    {
      return true;
    }
    return false;
  }

  bool GenExceptionAgentRISCV::IsLowPower(const GenExceptionRequest* pExceptReq) const
  {
    /*auto except_req = mpExceptionRequest->CastInstance<GenHandleException>();
    if (except_req->Id() == 0x4d) {
      return true;
    }*/
    return false;
  }

  bool GenExceptionAgentRISCV::IsSimExit(const GenExceptionRequest* pExceptReq) const
  {
    /*auto except_req = mpExceptionRequest->CastInstance<GenHandleException>();
    if (except_req->Id() == 0x4c) {
      return true;
    }*/
    return false;
  }

  bool GenExceptionAgentRISCV::IsFastMode() const
  {
    return mFastMode;
  }

  void GenExceptionAgentRISCV::SystemCall()
  {
    auto system_call_req = mpExceptionRequest->CastInstance<GenSystemCall>();

    map<string, string> call_params = system_call_req->SystemCallParams();
    auto iter = call_params.find("Function");
    if (iter == call_params.end())
    {
      // shouldn't happen since front-end has to provide a function name first
      LOG(fail) << "{GenExceptionAgentRISCV::SystemCall} system call function not provided " << endl;
      FAIL("empty-systemcall-request-type");
    }

    string function = iter->second;
    call_params.erase(iter); // remove the "Function" key, not needed pass this point

    if (function == "SwitchPrivilegeLevel")
    {
      map<string, uint64> results;
      SwitchPrivilege(call_params, results);
      system_call_req->SetResults(results);
    }
    else
    {
      LOG(fail) << "{GenExceptionAgentRISCV::SystemCall} unsupported function: " << function << endl;
      FAIL("unsupported-systemcall-request-type");
    }

  }

  /*int GenExceptionAgentRISCV::IllegalReturn(const map<string, string>& parmas_dict, map<string, uint64>& results)
  {
  }*/

  void GenExceptionAgentRISCV::ParseHandlerArgumentRegisters(const map<string, string>& rParams)
  {
    mArgRegIndices.clear();

    auto itr = rParams.find("DataBlockAddrRegIndex");
    if (itr != rParams.end()) {
      uint32 reg_index = parse_uint32(itr->second);
      mArgRegIndices.push_back(reg_index);

      LOG(notice) << "{GenExceptionAgentRISCV::ParseHandlerArgumentRegisters} adding handler argument register x" << reg_index << endl;
    }
    else {
      LOG(fail) << "The front-end exception system didn't allocate a register for passing the datablock address" << endl;
      FAIL("no-argument-register");
    }

    itr = rParams.find("ActionCodeRegIndex");
    if (itr != rParams.end()) {
      uint32 reg_index = parse_uint32(itr->second);
      mArgRegIndices.push_back(reg_index);

      LOG(notice) << "{GenExceptionAgentRISCV::ParseHandlerArgumentRegisters} adding handler argument register x" << reg_index << endl;
    }
    else {
      LOG(fail) << "The front-end exception system didn't allocate a register for passing the action code" << endl;
      FAIL("no-argument-register");
    }
  }

  void GenExceptionAgentRISCV::SwitchPrivilege(const map<string, string>& params_dict, map<string, uint64>& results)
  {
    SwitchPrivilegeSolver switch_priv_solver(mpGenerator);
    const SwitchPrivilegeResultInfo& switch_priv_info = switch_priv_solver.Solve(params_dict);

    results["RetCode"] = switch_priv_info.mSuccess ? 0 : 1;
    if (not switch_priv_info.mSuccess) {
      return;
    }

    results["DataBlockAddr"] = BuildDataBlock(switch_priv_info, switch_priv_solver.GetVmReloadRegisters());

    results["InstrSeqCode"] = switch_priv_info.mInstrSeqCode;
    results["PrivilegeLevel"] = switch_priv_info.mTargetPrivLevel;
    results["TargetAddr"] = switch_priv_info.mTargetAddr;
    results["IntermediateRetAddr"] = switch_priv_info.mIntermediateRetAddr;
    results["RecordId"] = BuildRequests(switch_priv_info.mTargetPrivLevel, switch_priv_info.mTargetAddr);

    results["DataBlockAddrRegIndex"] = mArgRegIndices[0];
    results["ActionCodeRegIndex"] = mArgRegIndices[1];
  }

  uint64 GenExceptionAgentRISCV::BuildRequests(uint32 targetPrivLevel, uint64 targetAddr)
  {
    auto peState = new PeStateUpdate();
    if (mpGenerator->HasISS() == false) {
      peState->UpdateState("PrivilegeLevel", "Set", targetPrivLevel);
      string status_name;
      string pp_field_name;
      if (targetPrivLevel == 3) {
        status_name = "mstatus"; pp_field_name = "MPP";
      } else if (targetPrivLevel == 2) {
        status_name = "mstatus"; pp_field_name = "MPP";  // mstatus.MPP records HS-mode
      } else {
        status_name = "sstatus"; pp_field_name = "SPP";
      }
      peState->UpdateRegisterField(status_name, pp_field_name, targetPrivLevel);

      if(not mpGenerator->InSpeculative()){
        peState->UpdateState("PC", "Set", targetAddr);
      }
    }

    return DataStation::Instance()->Add(peState);
  }

  uint64 GenExceptionAgentRISCV::BuildDataBlock(const SwitchPrivilegeResultInfo& result, const map<string, uint64>& sysRegReloads)
  {
    LOG(debug) << "{GenExceptionAgentRISCV::BuildDataBlock} entered..." << std::endl;
    
    uint64 satp_val = 0;
    auto satp_itr = sysRegReloads.find("satp");
    if (satp_itr != sysRegReloads.end()) {
      satp_val = satp_itr->second;

      LOG(notice) << "{GenExceptionAgentRISCV::BuildDataBlock} satp: 0x" << hex << satp_val << endl;
    }
    else {
      LOG(fail) << "{GenExceptionAgentRISCV::BuildDataBlock} No reload value provided for satp" << endl;
      FAIL("no-reload-value");
    }

    uint64 action_code_reg_val = 0;
    string action_code_reg_name = "x" + to_string(mArgRegIndices[1]);

    LOG(debug) << "{GenExceptionAgentRISCV::BuildDataBlock} action code reg: " << action_code_reg_name << std::endl;
    
    mpGenerator->RandomInitializeRegister(action_code_reg_name, "");
    mpGenerator->ReadRegister(action_code_reg_name, "", action_code_reg_val);

    LOG(debug) << "{GenExceptionAgentRISCV::BuildDataBlock} action code reg: " << action_code_reg_name
	       << " value: 0x" << std::hex << action_code_reg_val << std::dec << std::endl;
    
    uint64 data_block_addr_reg_val = 0;
    string data_block_addr_reg_name = "x" + to_string(mArgRegIndices[0]);
    mpGenerator->RandomInitializeRegister(data_block_addr_reg_name, "");
    mpGenerator->ReadRegister(data_block_addr_reg_name, "", data_block_addr_reg_val);

    LOG(debug) << "{GenExceptionAgentRISCV::BuildDataBlock} data block addr reg: " << data_block_addr_reg_name
	       << " value: 0x" << std::hex << data_block_addr_reg_val << std::dec << std::endl;
   
    int dsize = 8;

    if (Config::Instance()->GetGlobalStateValue(EGlobalStateType::AppRegisterWidth) == 32) {
      dsize = 4;
      LOG(debug) << "{GenExceptionAgentRISCV::BuildDataBlock} force-risc configured to 32-bits, dsize = " << std::dec << dsize << std::endl;
    }
    
    DataBlock dataBlock(8);
    int dblock_offset = 0;
    
    uint64 big_endian = mpGenerator->IsDataBigEndian();
    if (result.mInstrSeqCode == 3) {
      dataBlock.AddUnit(result.mIntermediateRetAddr, dsize, big_endian);
      LOG(debug) << "{GenExceptionAgentRISCV::BuildDataBlock} intermediate return address/dblock offset: 0x"
		 << std::hex << result.mIntermediateRetAddr << "/0x" << dblock_offset << std::dec << std::endl;
      dblock_offset+= dsize;
    }

    dataBlock.AddUnit(result.mStatusVal, dsize, big_endian);
    LOG(debug) << "{GenExceptionAgentRISCV::BuildDataBlock} status value/dblock offset: 0x"
	       << std::hex << result.mStatusVal << "/0x" << dblock_offset << std::dec << std::endl;
    dblock_offset+= dsize;
    dataBlock.AddUnit(result.mTargetAddr, dsize, big_endian);
    LOG(debug) << "{GenExceptionAgentRISCV::BuildDataBlock} target address/dblock offset: 0x"
	       << std::hex << result.mTargetAddr << "/0x" << dblock_offset << std::dec << std::endl;
    dblock_offset+= dsize;
    dataBlock.AddUnit(satp_val, dsize, big_endian);
    LOG(debug) << "{GenExceptionAgentRISCV::BuildDataBlock} satp/dblock offset: 0x"
	       << std::hex << satp_val << "/0x" << dblock_offset << std::dec << std::endl;

    VmManager* vm_manager = mpGenerator->GetVmManager();
    unique_ptr<VmInfo> vm_info(vm_manager->VmInfoInstance());
    vm_info->SetPrivilegeLevel(result.mDataBlockPrivLevel);
    vm_info->GetOtherStates(*mpGenerator);

    LOG(debug) << "{GenExceptionAgentRISCV::BuildDataBlock} target VM info: " << vm_info->ToString() << endl;

    VmMapper* target_mapper = vm_manager->GetVmMapper(*vm_info);
    target_mapper->Initialize();

    unique_ptr<GenPageRequest> page_req(mpGenerator->GenPageRequestInstance(false, EMemAccessType::Read));
    page_req->SetPrivilegeLevel(EPrivilegeLevelType(result.mDataBlockPrivLevel));
    page_req->SetGenBoolAttribute(EPageGenBoolAttrType::NoDataPageFault, true);

    if (result.mInstrSeqCode != 2) {
      // Transitioning to data block privilege level via ECALL exception
      page_req->SetGenBoolAttribute(EPageGenBoolAttrType::ViaException, true);
    }

    const PageRequestRegulator* page_req_regulator = mpGenerator->GetPageRequestRegulator();
    page_req_regulator->RegulateLoadStorePageRequest(target_mapper, nullptr, page_req.get());

    LOG(debug) << "{GenExceptionAgentRISCV::BuildDataBlock} current privilege level = " << dec << mpGenerator->PrivilegeLevel()
	       << ", data block privilege level = " << result.mDataBlockPrivLevel << endl;

    uint64 data_block_address = dataBlock.Allocate(mpGenerator, target_mapper, page_req.get());

    LOG(debug) << "{GenExceptionAgentRISCV::BuildDataBlock} data block address: 0x" << std::hex << data_block_address << std::dec << std::endl;

    return data_block_address;
  }

  void GenExceptionAgentRISCV::UpdateArchHandlerInfo()
  {
    auto update_req = mpExceptionRequest->CastInstance<GenUpdateHandlerInfo>();

    const map<string, string> handler_params = update_req->UpdaterHandlerParams();
    auto iter = handler_params.find("Function");
    if (iter == handler_params.end()) {
      // shouldn't happen since front-end has to provide a function name first
      LOG(fail) << "{GenExceptionAgentRISCV::UpdateHandlerInfo} function not provided " << endl;
      FAIL("empty-updatehandlerinfo-request-type");
    }

    string function = iter->second;

    if (function == "ExceptionRegisters") {
      LOG(notice) << "{GenExceptionAgentRISCV::UpdateHandlerInfo} given exception registers" << endl;

      ParseHandlerArgumentRegisters(handler_params);
    }
    else if (function == "FastMode") {
      string fast_mode = handler_params.find("is_fast_mode")->second;
      (fast_mode != "0") ? mFastMode = true : mFastMode = false;
      LOG(notice) << "{GenExceptionAgentRISCV::UpdateHandlerInfo} is_fast_mode=" << fast_mode << " mFastMode=" << mFastMode << endl;
      //setup default recovery exceptions for fast/comprehensive modes
      /*if (mFastMode) {
      }
      else {
      */
        mAddrTableEC.insert(uint64(EExceptionClassType::InstrAccessFault));
        mAddrTableEC.insert(uint64(EExceptionClassType::LoadAccessFault));
        mAddrTableEC.insert(uint64(EExceptionClassType::StoreAmoAccessFault));
        mAddrTableEC.insert(uint64(EExceptionClassType::InstrPageFault));
        mAddrTableEC.insert(uint64(EExceptionClassType::LoadPageFault));
        mAddrTableEC.insert(uint64(EExceptionClassType::StoreAmoPageFault));
        mAddrTableEC.insert(uint64(EExceptionClassType::InstrGuestPageFault));
        mAddrTableEC.insert(uint64(EExceptionClassType::LoadGuestPageFault));
        mAddrTableEC.insert(uint64(EExceptionClassType::StoreAmoGuestPageFault));
      //}
    }
    else if (function == "AddrTableEC") {
      mAddrTableEC.insert(parse_uint64(handler_params.find("EC")->second));
      LOG(notice) << "{GenExceptionAgent::UpdateHandlerInfo} adding EC for addr table EC=0x" << hex << parse_uint64(handler_params.find("EC")->second) << endl;
      LOG(warn) << "{GenExceptionAgentRISCV::UpdateHandlerInfo} no addr table EC's supported yet" << endl;
    }
    else {
      LOG(fail) << "{GenExceptionAgentRISCV::UpdateHandlerInfo} unsupported function: " << function << endl;
      FAIL("unsupported-updatehandlerinfo-request-type");
    }
  }

  bool GenExceptionAgentRISCV::AllowExceptionInException(const GenHandleException* except_req, string& rErrInfo) const
  {
    EExceptionClassType ec_type = EExceptionClassType(except_req->Id());
    /* Allow only certain types of exceptions to be taken while in another exception */
    switch (ec_type) {
    case EExceptionClassType::InstrGuestPageFault:
    case EExceptionClassType::LoadGuestPageFault:
    case EExceptionClassType::StoreAmoGuestPageFault:
    case EExceptionClassType::VirtualInstruction:
      return true;
    default:
      DiagnoseExceptionDefault(ec_type, rErrInfo);
      return false;
    }

    return false;
  }

  void GenExceptionAgentRISCV::HandleException()
  {
    auto except_req = mpExceptionRequest->CastInstance<GenHandleException>();
    EExceptionClassType ec_type = EExceptionClassType(except_req->Id());

    LOG(notice) << "{GenExceptionAgentRISCV::HandleException} exception ID 0x" << hex << except_req->Id()
                << " (" << EExceptionClassType_to_string(ec_type) << ")" << dec << endl;

    // Check if this is a guest page fault
    if (ec_type == EExceptionClassType::InstrGuestPageFault ||
        ec_type == EExceptionClassType::LoadGuestPageFault ||
        ec_type == EExceptionClassType::StoreAmoGuestPageFault) {

      LOG(notice) << "{GenExceptionAgentRISCV::HandleException} detected guest page fault, calling handler" << endl;

      EPagingExceptionType pf_type = EExceptionClassTypeToPagingExceptionType(ec_type);
      GenerateGuestPageFaultHandler(pf_type);
      return;  // Guest page fault handled, don't fall through to base class
    }

    // Invalidate hedeleg/hideleg cache before delegation check (registers may have changed)
    InvalidateRegisterCache();

    // Check hypervisor trap delegation (hedeleg)
    if (IsExceptionDelegatedToVS(ec_type)) {
      LOG(notice) << "{GenExceptionAgentRISCV::HandleException} exception delegated to VS-mode via hedeleg" << endl;
      // Exception is delegated to VS-mode, handle accordingly
      // The base class HandleException will handle the privilege switch
    }

    // Call base class HandleException
    GenExceptionAgent::HandleException();
  }

  // Map EExceptionClassType (FORCE internal) to RISC-V mcause exception code.
  // hedeleg bit positions follow the RISC-V spec mcause layout, not FORCE's
  // internal EExceptionClassType numbering (which inserts EnvCallFromVU/HS at 10-11).
  static uint32 ECTypeToMcause(EExceptionClassType ec_type)
  {
    switch (ec_type) {
    case EExceptionClassType::InstrAddrMisaligned:        return 0;
    case EExceptionClassType::InstrAccessFault:           return 1;
    case EExceptionClassType::IllegalInstr:               return 2;
    case EExceptionClassType::Breakpoint:                 return 3;
    case EExceptionClassType::LoadAddrMisaligned:         return 4;
    case EExceptionClassType::LoadAccessFault:            return 5;
    case EExceptionClassType::StoreAmoAddrMisaligned:     return 6;
    case EExceptionClassType::StoreAmoAccessFault:        return 7;
    case EExceptionClassType::EnvCallFromUMode:           return 8;
    case EExceptionClassType::EnvCallFromSMode:           return 9;
    case EExceptionClassType::EnvCallFromVU:              return 10;
    case EExceptionClassType::EnvCallFromHS:              return 11;
    case EExceptionClassType::EnvCallFromMMode:           return 11;
    case EExceptionClassType::InstrPageFault:             return 12;
    case EExceptionClassType::LoadPageFault:              return 13;
    case EExceptionClassType::StoreAmoPageFault:          return 15;
    case EExceptionClassType::InstrGuestPageFault:        return 20;
    case EExceptionClassType::LoadGuestPageFault:         return 21;
    case EExceptionClassType::StoreAmoGuestPageFault:     return 23;
    case EExceptionClassType::VirtualInstruction:         return 22;
    default:                                              return static_cast<uint32>(ec_type);
    }
  }

  bool GenExceptionAgentRISCV::IsExceptionDelegatedToVS(EExceptionClassType ec_type) const
  {
    // Check if the exception is delegated to VS-mode via hedeleg register
    // Use cached value if available
    if (!mHedelegCached) {
      const RegisterFile* reg_file = mpGenerator->GetRegisterFile();
      Register* hedeleg_reg = reg_file->RegisterLookup("hedeleg");

      if (hedeleg_reg == nullptr || !hedeleg_reg->IsInitialized()) {
        return false;
      }

      mCachedHedeleg = hedeleg_reg->Value();
      mHedelegCached = true;
    }

    // Use mcause-based bit position for hedeleg check (not EExceptionClassType value)
    uint32 exc_bit = ECTypeToMcause(ec_type);

    // Check if the corresponding bit is set in hedeleg
    if (exc_bit < 64) {
      bool delegated = (mCachedHedeleg >> exc_bit) & 0x1;
      if (delegated) {
        LOG(notice) << "{GenExceptionAgentRISCV::IsExceptionDelegatedToVS} exception 0x" << hex << exc_bit
                    << " delegated to VS-mode (hedeleg=0x" << mCachedHedeleg << ")" << dec << endl;
      }
      return delegated;
    }

    return false;
  }

  void GenExceptionAgentRISCV::InvalidateRegisterCache()
  {
    mHedelegCached = false;
    mHidelegCached = false;
    LOG(trace) << "{GenExceptionAgentRISCV::InvalidateRegisterCache} register cache invalidated" << endl;
  }

  bool GenExceptionAgentRISCV::NeedRecoveryAddress() const
  {
    bool recovery_exception = false;
    bool need_check_ec = false;
    uint64 ec_val = -1ull;
    cuint32 priv_level = mpGenerator->PrivilegeLevel();
    const RegisterFile* reg_file = mpGenerator->GetRegisterFile();

    if (priv_level == cuint32(EPrivilegeLevelType::S) || priv_level == cuint32(EPrivilegeLevelType::H))
    {
      // Determine if we are in VS-mode (V=1) or regular S/HS mode
      bool is_vs_mode = false;
      if (priv_level == cuint32(EPrivilegeLevelType::S)) {
        uint64 v_val = 0;
        mpGenerator->ReadRegister("virtual", "MODE", v_val);
        is_vs_mode = (v_val & 0x1) != 0;
      }
      const char* cause_reg_name = is_vs_mode ? "vscause" : "scause";

      //We are in supervisor/hypervisor mode, look to the cause register for the EC value.
      Register* cause_reg = reg_file->RegisterLookup(cause_reg_name);
      if (not cause_reg->IsInitialized()) {
        LOG(warn) << "{GenExceptionAgentRISCV::NeedRecoveryAddress} " << cause_reg_name << " was not initialized." << endl;
        LOG(notice) << "{GenExceptionAgentRISCV::NeedRecoveryAddress} " << cause_reg_name << " was not initialized." << endl;
        mpGenerator->RandomInitializeRegister(cause_reg_name,"");
      }

      //Is the interrupt bit enabled? If so we don't need a recovery address
      uint64 interrupt_bit = cause_reg->RegisterFieldLookup("INTERRUPT")->FieldValue();
      if (interrupt_bit == uint64(1u))
      {
        recovery_exception = false;
        need_check_ec = false;
      }
      else
      {
        //This is not an interrupt. Determine EC.
        ec_val = cause_reg->RegisterFieldLookup("EXCEPTION CODE_VAR")->FieldValue();
        LOG(notice) << "{GenExceptionAgentRISCV::NeedRecoveryAddress} found ec value for " << cause_reg_name << ": " << ec_val  << endl;
        need_check_ec = true;
      }
    }
    else if (priv_level == cuint32(EPrivilegeLevelType::M))
    {
      //We are in machine mode (0b11) so we look to the mcause register for the EC value.
      Register* mcause_reg = reg_file->RegisterLookup("mcause");
      if (not mcause_reg->IsInitialized()) {
        LOG(warn) << "{GenExceptionAgentRISCV::NeedRecoveryAddress} function is called but mcause was not initialized." << endl;
        LOG(notice) << "{GenExceptionAgentRISCV::NeedRecoveryAddress} function is called but mcause was not initialized." << endl;
	mpGenerator->RandomInitializeRegister("mcause","");
      }

      //Is the interrupt bit enabled? If so we don't need a recovery address
      uint64 interrupt_bit = mcause_reg->RegisterFieldLookup("INTERRUPT")->FieldValue();
      if (interrupt_bit == uint64(1u))
      {
        recovery_exception = false;
	need_check_ec = false;
      }
      else
      {
        //This is not an interrupt. Determine EC.
        ec_val = mcause_reg->RegisterFieldLookup("EXCEPTION CODE_VAR")->FieldValue();
	need_check_ec = true;
        LOG(notice) << "{GenExceptionAgentRISCV::NeedRecoveryAddress} found ec value for mcause: " << ec_val  << endl;
      }
    }
    else
    {
      //We could be in user mode, a reserved mode or hypervisor mode. Exceptions from these modes are not supported currently.
      LOG(warn) << "{GenExceptionAgentRISCV::NeedRecoveryAddress} Current Privilege Level is not Supervisor nor is it Machine. User, Reserved or Hypervisor exceptions not supported. Returning false." << endl;

      recovery_exception = false;
      need_check_ec = false;
    }

    if(need_check_ec)
    {
      //EExceptionClassType enum values should match the ISA ECs.
      auto find_iter = mAddrTableEC.find(ec_val);
      if (find_iter != mAddrTableEC.end())
      {
        recovery_exception = true;
      }
      else
      {
        recovery_exception = false;
      }
    }

    LOG(notice) << "{GenExceptionAgentRISCV::NeedRecoveryAddress} recovery_exception set to: " << recovery_exception << endl;
    return recovery_exception;
  }

  void GenExceptionAgentRISCV::RecordExceptionSpecificAddressBounds(const map<string, string>& myMap)
  {
    ExceptionManager::ListOfAddressBoundaries boundaries_list;
    const string& handler_bounds = myMap.find("DEFAULT_bounds")->second;
    ProcessHandlerBounds(EMemBankTypeBaseType(EMemBankType::Default), handler_bounds, boundaries_list);

    ExceptionManager::Instance()->AddHandlerBounds(EMemBankTypeBaseType(EMemBankType::Default), boundaries_list);
  }

  void GenExceptionAgentRISCV::GenerateGuestPageFaultHandler(EPagingExceptionType guestPfType)
  {
    LOG(notice) << "{GenExceptionAgentRISCV::GenerateGuestPageFaultHandler} handling guest page fault type: "
                << EPagingExceptionType_to_string(guestPfType) << endl;

    // For Guest Page Faults, set up the hypervisor trap value registers:
    // htval: Contains the faulting Guest Virtual Address (GVA) bits[63:2]
    // htinst: Contains the trapped instruction or a pseudo-instruction encoding

    const RegisterFile* reg_file = mpGenerator->GetRegisterFile();

    // Get faulting GVA from stval or mtval register
    uint64 faulting_gva = 0;
    Register* stval_reg = reg_file->RegisterLookup("stval");
    if (stval_reg != nullptr && stval_reg->IsInitialized()) {
      faulting_gva = stval_reg->Value();
      LOG(notice) << "{GenExceptionAgentRISCV::GenerateGuestPageFaultHandler} faulting GVA from stval: 0x"
                  << hex << faulting_gva << dec << endl;
    } else {
      Register* mtval_reg = reg_file->RegisterLookup("mtval");
      if (mtval_reg != nullptr && mtval_reg->IsInitialized()) {
        faulting_gva = mtval_reg->Value();
        LOG(notice) << "{GenExceptionAgentRISCV::GenerateGuestPageFaultHandler} faulting GVA from mtval: 0x"
                    << hex << faulting_gva << dec << endl;
      } else {
        // Fallback: use PC as faulting address
        faulting_gva = mpGenerator->GetGenPC()->Value();
        LOG(warn) << "{GenExceptionAgentRISCV::GenerateGuestPageFaultHandler} using PC as faulting GVA: 0x"
                  << hex << faulting_gva << dec << endl;
      }
    }

    // htval holds bits [63:2] of the faulting guest virtual address
    Register* htval_reg = reg_file->RegisterLookup("htval");
    if (htval_reg != nullptr) {
      // Set htval with faulting GVA bits[63:2]
      uint64 htval_value = (faulting_gva >> 2) & 0xFFFFFFFFFFFFFFCULL;
      
      LOG(notice) << "{GenExceptionAgentRISCV::GenerateGuestPageFaultHandler} htval set to 0x" 
                  << hex << htval_value << " (GVA bits[63:2])" << dec << endl;
      
      // Generate instruction to set htval register
      mpGenerator->AddPostInstructionStepRequest(
        new GenSetRegister(htval_reg, htval_value)
      );
    }

    // htinst holds the trapped instruction or a pseudo-instruction encoding
    Register* htinst_reg = reg_file->RegisterLookup("htinst");
    if (htinst_reg != nullptr) {
      // For guest page faults, htinst contains:
      // - Bits [1:0] = 00: full instruction
      // - Bits [1:0] = 10: pseudo-instruction encoding
      // - Bits [15:2]: instruction bits or transformation value
      
      uint64 htinst_value = 0;
      
      // Set pseudo-instruction flag for guest page faults
      htinst_value |= 0x2; // bits[1:0] = 10 for pseudo-instruction
      
      // Set the transformation value based on fault type
      switch (guestPfType) {
        case EPagingExceptionType::InstrGuestPageFault:
          htinst_value |= (0x0 << 2); // Instruction fetch
          break;
        case EPagingExceptionType::LoadGuestPageFault:
          htinst_value |= (0x1 << 2); // Load
          break;
        case EPagingExceptionType::StoreAmoGuestPageFault:
          htinst_value |= (0x2 << 2); // Store/AMO
          break;
        default:
          break;
      }
      
      LOG(notice) << "{GenExceptionAgentRISCV::GenerateGuestPageFaultHandler} htinst set to 0x" 
                  << hex << htinst_value << dec << endl;
      
      mpGenerator->AddPostInstructionStepRequest(
        new GenSetRegister(htinst_reg, htinst_value)
      );
    }

    // Log the specific guest page fault type for debugging
    switch (guestPfType) {
    case EPagingExceptionType::InstrGuestPageFault:
      LOG(notice) << "{GenExceptionAgentRISCV::GenerateGuestPageFaultHandler} Instruction Guest Page Fault - G-stage translation fault on instruction fetch" << endl;
      break;
    case EPagingExceptionType::LoadGuestPageFault:
      LOG(notice) << "{GenExceptionAgentRISCV::GenerateGuestPageFaultHandler} Load Guest Page Fault - G-stage translation fault on load" << endl;
      break;
    case EPagingExceptionType::StoreAmoGuestPageFault:
      LOG(notice) << "{GenExceptionAgentRISCV::GenerateGuestPageFaultHandler} Store/AMO Guest Page Fault - G-stage translation fault on store/AMO" << endl;
      break;
    default:
      LOG(warn) << "{GenExceptionAgentRISCV::GenerateGuestPageFaultHandler} unknown guest page fault type" << endl;
      break;
    }
  }

  EExceptionVectorType GenExceptionAgentRISCV::GetExceptionVectorType(const string& vecStr) const
  {
    return string_to_EExceptionVectorType(vecStr);
  }

  void GenExceptionAgentRISCV::AddPostExceptionRequests()
  {
    ChoicesModerator* choices_mod = mpGenerator->GetChoicesModerator(EChoicesType::GeneralChoices);
    unique_ptr<ChoiceTree> choice_tree(choices_mod->CloneChoiceTree("Reset vstart"));
    const Choice* choice = choice_tree->Choose();
    if (choice->Value() == 1) {
      const RegisterFile* reg_file = mpGenerator->GetRegisterFile();
      Register* vstart_reg = reg_file->RegisterLookup("vstart");

      if (vstart_reg->Value() != 0) {
        mpGenerator->AddPostInstructionStepRequest(new GenLoadRegister("vstart", 0));
      }
    }
  }

  EPagingExceptionType GenExceptionAgentRISCV::EExceptionClassTypeToPagingExceptionType(EExceptionClassType ec_type) const
  {
    switch (ec_type) {
      case EExceptionClassType::InstrGuestPageFault:
        return EPagingExceptionType::InstrGuestPageFault;
      case EExceptionClassType::LoadGuestPageFault:
        return EPagingExceptionType::LoadGuestPageFault;
      case EExceptionClassType::StoreAmoGuestPageFault:
        return EPagingExceptionType::StoreAmoGuestPageFault;
      default:
        LOG(warn) << "{GenExceptionAgentRISCV::EExceptionClassTypeToPagingExceptionType} unexpected exception class type: "
                  << EExceptionClassType_to_string(ec_type) << endl;
        return EPagingExceptionType::InstructionPageFault; // Default fallback
    }
  }

}
