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
#include "SimApiHANDCAR.h"

#include <array>
#include <cctype>
#include <cstring>
#include <iomanip>
#include <iostream>

#include "GenException.h"

PICKY_IGNORE_BLOCK_START
#include "SimLoader.h"
PICKY_IGNORE_BLOCK_END

/*!
  \file SimApiHANDCAR.cc
  \brief Code supporting SimApiHANDCAR class that connects HANDCAR APIs with the FORCE C++ code.
*/

using namespace std;

namespace Force {

  static SimApiHANDCAR *spSimApiHandle = nullptr; //!< pointer to singletion SimApiHANDCAR object

}

namespace {

  using namespace Force;

  uint32 sXlen = 64;  // Integer register width
  uint32 sFlen = 32;  // Floating-point register width

  // Diagnostic events must not schedule FORCE's automatic exception handlers.
  // Capture actual take_trap calls, including repeated identical traps.
  struct TrapTrace {
    uint32 cpu;
    uint64 cause, epc, tval, tval2, tinst, target;
    uint32 from_priv, from_virt, to_priv, to_virt;
    string name;
  };
  vector<TrapTrace> sTrapTrace;
  bool sCollectTrapTrace = false;

  void validate_mask(cuint64 val, cuint32 maskSize)
  {
    // Signal error if the bits to be removed by the mask don't represent a sign-extension
    if (maskSize < 64) {
      uint64 sign_bits = static_cast<uint64>(static_cast<int64>(val) >> maskSize);

      if ((sign_bits != 0) and (sign_bits != MAX_UINT64)) {
        stringstream err_stream;
        err_stream << "Bits above Bit " << dec << (maskSize - 1) << " contain unexpected data in value 0x" << hex << val << "\n";
        throw SimulationError(err_stream.str());
      }
    }
  }

  uint64 mask_address_to_size(cuint64 addr)
  {
    uint64 mask_size = 64;
    if (sXlen == 32) {
      mask_size = 32;
    }

    //validate_mask(addr, mask_size);

    uint64 mask = MAX_UINT64 >> (64 - mask_size);

    return (addr & mask);
  }

  uint64 mask_register_to_size(const string& rRegName, cuint64 regVal)
  {
    uint32 mask_size = 64;
    if (rRegName[0] == 'f' and isdigit(rRegName[1])) {
      mask_size = sFlen;
    }
    else if (rRegName[0] == 'v' and isdigit(rRegName[1])) {
      // Vector register values can always use full 64-bit mask
    }
    else {
      mask_size = sXlen;
    }

    // Handcar sets the xstatus SXL and UXL fields in 32-bit mode even though those fields don't
    // exist, so we skip validating xstatus because the validation will always fail in 32-bit mode.
    // Handcar sometimes loads xtval with addresses larger than 32-bits for some vector
    // instructions, so we skip validating xtval as well.
    string reg_name_tail = rRegName.substr(1);
    if ((reg_name_tail != "status") and (reg_name_tail != "tval")) {
      validate_mask(regVal, mask_size);
    }

    uint64 mask = MAX_UINT64 >> (64 - mask_size);

    return (regVal & mask);
  }

  string simulator_register_name(const string& rRegName)
  {
    static const char* const kXprAbiNames[] = {
      "zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2",
      "s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5",
      "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
      "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6"
    };

    if ((rRegName.size() >= 2) && ((rRegName[0] == 'x') || (rRegName[0] == 'X'))) {
      try {
        size_t parsed_length = 0;
        uint32 reg_index = stoul(rRegName.substr(1), &parsed_length);
        if ((parsed_length == rRegName.size() - 1) && (reg_index < 32)) {
          return kXprAbiNames[reg_index];
        }
      }
      catch (...) {
      }
    }

    return rRegName;
  }

}

//!< simulator calls these C functions:
extern "C" {

  void handcar_trace_trap(uint32_t cpu, uint64_t cause, uint64_t epc,
    uint64_t tval, uint64_t tval2, uint64_t tinst, uint64_t target,
    uint32_t from_priv, uint32_t from_virt, uint32_t to_priv, uint32_t to_virt,
    const char* name)
  {
    if (sCollectTrapTrace)
      sTrapTrace.push_back({cpu, cause, epc, tval, tval2, tinst, target,
        from_priv, from_virt, to_priv, to_virt, name ? name : "unknown"});
  }

  Force::SimAPI * instantiate_api()
  {
    return new Force::SimApiHANDCAR();
  }

  void update_generator_register(uint32_t cpuid, const char *pRegName, uint64_t rval_in, uint64_t mask, const char *pAccessType)
  {
    std::string reg_name_copy(pRegName);
    uint64_t rval = mask_register_to_size(reg_name_copy, rval_in);

    //Force demands that fp register names contain implementation specific physical register suffixes. So, just tack on '_0' to fp register names
    //if we can assume that the current design is limited to a max precision of double precision floating point instructions.
    if(pRegName[0] == 'f' && pRegName[1] < (char)(58))
    {
      reg_name_copy += std::string("_0");
    }

    //std::cout << "[update_generator_register] reg_name_copy: " << reg_name_copy << ": 0x" << std::hex << rval << std::dec << std::endl;

    Force::spSimApiHandle->RecordRegisterUpdate(cpuid, reg_name_copy.c_str(), rval, mask, pAccessType);
  }

  void update_generator_memory(uint32_t cpuid, uint64_t virtualAddress, uint32_t memBank, uint64_t physicalAddress, uint32_t size, const char *pBytes, const char *pAccessType)
  {
    Force::spSimApiHandle->RecordMemoryUpdate(cpuid, mask_address_to_size(virtualAddress), memBank, mask_address_to_size(physicalAddress), size, pBytes, pAccessType);
  }

  void update_mmu_event(Force::MmuEvent *event)
  {
    event->va = mask_address_to_size(event->va);
    event->pa = mask_address_to_size(event->pa);
    Force::spSimApiHandle->RecordMmuEvent(event);
  }

  struct SimException {
    SimException() : mExceptionID(0), mExceptionAttributes(0), mpComments(""), mEPC(0) {}
    SimException(uint32_t exceptionID, uint32_t exceptionAttributes, const char* comments, uint64_t epc) :
      mExceptionID(exceptionID), mExceptionAttributes(exceptionAttributes), mpComments(comments), mEPC(epc) {}
    uint32_t mExceptionID; //!< 0x4E: eret. Others are scause or mcause values.  
    uint32_t  mExceptionAttributes;  //!< copied from tval.
    const char* mpComments; //!<  exception comments, indicate exit / enter and m versus s mode.
    uint64_t mEPC; //!< exception program counter
  };

  void update_exception_event(const SimException *exception)
  {
    Force::spSimApiHandle->RecordExceptionUpdate(exception);
  }

  // inputs:
  //  uint32_t cpuid : the id of the core from which the register update is being received.
  //  const char *pRegName : the name of the logical register in which the element belongs.
  //  uint32_t vecRegIndex : the index of the vector register, somewhat redundant with name.
  //  uint32_t eltByteWidth : the byte width of the element, important because this can change during runtime.
  //  const uint8_t* pValue : whenever access type is read, this points to the entire data content of the whole vector register not just an element.
  //  uint32_t byteLength : the number of bytes that pValue points to.
  //  const char* pAccessType : should be either "read" or "write".
  void update_vector_element(uint32_t cpuid, const char *pRegName, uint32_t vecRegIndex, uint32_t eltIndex, uint32_t eltByteWidth, const uint8_t* pValue, uint32_t  byteLength, const char* pAccessType)
  {
    Force::spSimApiHandle->RecordVectorRegisterUpdate(cpuid, pRegName, vecRegIndex, eltIndex, eltByteWidth, pValue, byteLength, pAccessType);
  }
  
};

using namespace std;

namespace Force {

  SimApiHANDCAR::SimApiHANDCAR()
    : SimAPI(), mpSimDllAPI(nullptr), mLastStepWasSelfLoop(false)
  {
    mpSimDllAPI = new SimDllApi();
  }

  SimApiHANDCAR::~SimApiHANDCAR()
  {
    delete mpSimDllAPI;
  }

    //!< Initialize simulator shared object using standard Force/HANDCAR parameters...

  void SimApiHANDCAR::InitializeIss(const ApiSimConfig& rConfig, const string &rSimSoFile, const string& rApiTraceFile)
  {
    spSimApiHandle = this;
 
    OpenApiTrace(rApiTraceFile);

    if (mOfsApiTrace.is_open()) {
      mOfsApiTrace << "#include <stdio.h>\n"
		   << "#include <stdlib.h>\n\n"
		   << "#include <dlfcn.h>\n\n"
		   << "#include \"handcar_cosim_wrapper.h\"\n\n"
		   << "#include \"SimLoader.h\"\n\n"
		   << "int main(int argc,char **argv) {\n\n"
		   << "  SimDllApi sim_api;\n\n"
		   << "  if (open_sim_dll(\"" << rSimSoFile << "\", &sim_api)) {\n"
		   << "    printf(\"Program aborted due to sim errors.\n\");\n"
		   << "    return -1;\n"
		   << "  }\n\n"
		   << std::endl;
    }

    if(rConfig.mUseTraceFile) {
      OpenOfs(rConfig.mpTraceFile, mOfsSimTrace);
      mOfsSimTrace << "# HANDCAR trace v2: PC(VA)=instruction address; NextPC(VA)=after step; Trap=take_trap event\n";
    }

    if (open_sim_dll(rSimSoFile.c_str(), mpSimDllAPI)) {
      stringstream err_stream;
      err_stream << "Simulator shared library failed to load\n";
      throw SimulationError(err_stream.str());
    }

    if (mOfsApiTrace.is_open()) {
      mOfsApiTrace << "sim_api.initialize_simulator(\"-l\");\n"
		   << std::endl;
    }

    SetVectorRegisterWidth(rConfig.mVectorRegLen);

    string config_str = BuildHandcarConfigurationString(rConfig);
    mpSimDllAPI->initialize_simulator(config_str.c_str());
  }

  //!< write out simulation trace file (if any), send 'terminate' directive to simulator, close sim dll...

  void SimApiHANDCAR::Terminate()
  {
    PrintSummary();

    if (mOfsApiTrace.is_open()) {
      mOfsApiTrace << "  sim_api.terminate_simulator();\n"
		   << "  close_sim_dll(&sim_api);\n"
		   << "  return(0);\n}\n" << std::endl;
    }
    CloseApiTrace();

    mpSimDllAPI->terminate_simulator();
    close_sim_dll(mpSimDllAPI);
    spSimApiHandle = nullptr;
  }

  //!< obtain the opcode and dissassembly that corresponds to a given PC address
  
  void SimApiHANDCAR::GetDisassembly(uint32 CpuID, const uint64_t* pPc, std::string& rOpcode, std::string& rDisassembly)
  {
    char* op = new char[128];
    char* dis = new char[128];
    memset(op, '0', 128);
    memset(dis,'0', 128);
    op[127]='\0';
    dis[127]='\0';
    char** opp = &op;
    char** disp = &dis;

    int rcode = mpSimDllAPI->get_disassembly_for_target(CpuID, pPc, opp, disp);

    if (rcode == 1) {
      // A page fault on a branch could result in an exception. The disassembly call in the simulator
      // will fail since there is no mapping for the fault address. The expected return code in
      // this case is 1...
      strcpy(op,"00000000");
      strcpy(dis,"?");
    } else if (rcode != 0) {
      // any other non-zero return code is NOT expected...
      stringstream err_stream;
      err_stream << "Problems getting disassembly" << "\n";
      throw SimulationError(err_stream.str());
    }

    rOpcode = op;
    rDisassembly = dis;

    delete[] op;
    delete[] dis;
  }

  //!< write simulator physical memory. Return 0 if no errors...

  void SimApiHANDCAR::WritePhysicalMemory(uint32 memBank, uint64 address, uint32 size, const unsigned char *pBytes) {
    if (mOfsApiTrace.is_open()) {
      char tbuf[1024];
      for (unsigned int i = 0; i < size; i++) {
         sprintf(tbuf," 0x%02x",pBytes[i]);
         if ( (size > 1) && (i < (size - 1)) )
           strcat(tbuf,",");
      }
      mOfsApiTrace << "{\n"
		   << "  char tbuf = { " 
		   << tbuf 
		   << "  };\n";
      sprintf(tbuf,"sim_api.write_simulator_memory(%d,0x%llx,%d,tbuf);",memBank,(unsigned long long) address,size);
      mOfsApiTrace << tbuf
		   << "}" << std::endl;
    }

    int error_code = mpSimDllAPI->write_simulator_memory(memBank, (const uint64_t*)&address, size, (const uint8_t *) pBytes);
    //if (mpSimDllAPI->write_simulator_memory(memBank, (const uint64_t*)&address, size, (const uint8_t *) pBytes)) {
    if(error_code != 0){
      stringstream err_stream;
      err_stream << dec << "error code: " << error_code << " Problems writing to simulator memory. PA: 0x" << hex << address
                 << dec << ", # of bytes: " << size << "\n";
      throw SimulationError(err_stream.str());
    }

  }

  //!< read register value...

  void SimApiHANDCAR::ReadRegister(uint32 CpuID, const char *regname, uint64 *rval, uint64 *pRegMask)
  {
    if (mOfsApiTrace.is_open()) {
      char tbuf[1024];
      sprintf(tbuf,"  sim_api.read_simulator_register(0x%x,\"%s\",&rval,&rmask);\n",CpuID,regname);
      mOfsApiTrace << "{\n"
		   << " uint64_t rval,rmask;\n" 
		   << tbuf;
      sprintf(tbuf,"  printf(\"  %s",regname);
      mOfsApiTrace << tbuf
		   << " value/mask: 0x\%llx/0x\%llx\n\",(unsigned long long) rval,(unsigned long long) rmask);\n"
		   << "};" << std::endl;
    }

    //Remove any suffix the generator has attached to the register name, the simulator doesn't use the suffix.
    int errorcode = 0;
    char* p_edited_regname = nullptr;
    const char* p_fp_reg_f = strstr(regname, "f");
    const char* p_phys_reg_suffix = strstr(regname, "_"); 

    if(p_fp_reg_f != nullptr && p_phys_reg_suffix != nullptr)
    {

      ptrdiff_t arch_regname_length = p_phys_reg_suffix - p_fp_reg_f;
      p_edited_regname = new char[arch_regname_length+1];
      p_edited_regname[arch_regname_length] = '\0';

      memcpy(p_edited_regname, regname, arch_regname_length);

      errorcode = mpSimDllAPI->read_simulator_register(CpuID, p_edited_regname, (uint64_t *)rval, (uint64_t *)pRegMask);
      delete[] p_edited_regname;
    }
    else
    {
      const string sim_reg_name = simulator_register_name(regname);
      errorcode = mpSimDllAPI->read_simulator_register(CpuID, sim_reg_name.c_str(), (uint64_t *)rval, (uint64_t *)pRegMask);
    }

    //std::cout << "SimApiHANDCAR::ReadRegister(...) : " << regname << " val: " << std::hex << rval << std::endl;

    if (0 != errorcode) {
      stringstream err_stream;
      err_stream << "Problems reading simulator register. CPU ID: " << hex << CpuID << dec
                 << ", register: '" << regname << "', mask: 0x" << hex << pRegMask << dec << "\n";
      throw SimulationError(err_stream.str());
    }
  }

  //!< read the bytes corresponding to a physical register from a large logical register without forcing the simulator to use Force's naming convention.
  
  void SimApiHANDCAR::PartialReadLargeRegister(uint32 CpuID, const char* pRegname, uint8_t* pBytes, uint32 length, uint32 offset)
  {
    if (mOfsApiTrace.is_open()) {
      char tbuf[1024];
      sprintf(tbuf,"  sim_api.partial_read_large_register(0x%x,\"%s\",&bytes,length,offset);\n",CpuID,pRegname);
      mOfsApiTrace << "{\n"
           << " uint8_t* pBytes;\n"
           << tbuf;
      sprintf(tbuf,"  printf(\"  %s",pRegname);
    }
 
    if (0 != mpSimDllAPI->partial_read_large_register(CpuID, pRegname, pBytes, (uint32_t)length, (uint32_t)offset)) {
      stringstream err_stream;
      err_stream << "Problems reading simulator register. CPU ID: " << hex << CpuID  << dec
                 << ", register: '" << pRegname << "\n";
      throw SimulationError(err_stream.str());
    }
  }

  //!< write simulator register. mask indicates which bits to write...

  void SimApiHANDCAR::WriteRegister(uint32 CpuID, const char *regname, uint64 rval, uint64 rmask)
  {
    std::cout << "[SimApiHANDCAR::WriteRegister] " << regname << std::hex << " 0x" << rval << "/0x" << rmask << std::dec << std::endl;

    if (mOfsApiTrace.is_open()) {
      char tbuf[1024];
      sprintf(tbuf,"  sim_api.write_simulator_register(0x%x,\"%s\", 0x%llx, 0x%llx);\n",
              CpuID,regname,(unsigned long long) rval,(unsigned long long) rmask);
      mOfsApiTrace << tbuf << std::endl;
    }

    //Remove any suffix the generator has attached to the register name, the simulator doesn't use the suffix.
    int errorcode = 0;
    string reg_name = regname;
    uint64 underscore_pos = reg_name.find("_");
    string reg_name_no_suffix = reg_name.substr(0, underscore_pos);
    if (underscore_pos == string::npos) {
      const string sim_reg_name = simulator_register_name(reg_name_no_suffix);
      errorcode = mpSimDllAPI->write_simulator_register(CpuID, sim_reg_name.c_str(), rval, rmask);
    }
    else if (reg_name[0] == 'f') {
      errorcode = mpSimDllAPI->write_simulator_register(CpuID, reg_name_no_suffix.c_str(), rval, rmask);
    }
    else if (reg_name[0] == 'v') {
      uint32 phys_reg_sub_index = stoul(reg_name.substr(underscore_pos + 1));
      errorcode = mpSimDllAPI->partial_write_large_register(CpuID, reg_name_no_suffix.c_str(), reinterpret_cast<const uint8_t*>(&rval), sizeof(rval), phys_reg_sub_index * sizeof(rval));
    }
    else {
      errorcode = -1;
    }

    //std::cout << "SimApiHANDCAR::WriteRegister(...) : " << regname << " val: " << std::hex << rval << std::endl;

    if (0 != errorcode) {
      stringstream err_stream;
      err_stream << "Error code: " << errorcode << ", Problems writing simulator register. CPU ID: " << hex << CpuID
                 << ", register: '" << regname << "', value: 0x" << rval
                 << ", mask: 0x" << rmask << dec << "\n";
      throw SimulationError(err_stream.str());
    }
  }

  //!< standard step method...

  void SimApiHANDCAR::Step(uint32 cpuid, vector<RegUpdate> &rRegUpdates, vector<MemUpdate> &rMemUpdates, vector<MmuEvent> &rMmuEvents, vector<ExceptionUpdate> &rExceptUpdates)
  {
    // clear updates from previous step...
    mRegisterUpdates.erase(mRegisterUpdates.begin(),mRegisterUpdates.end());
    mMemoryUpdates.erase(mMemoryUpdates.begin(),mMemoryUpdates.end());
    mMmuEvents.erase(mMmuEvents.begin(),mMmuEvents.end());
    mExceptionUpdates.erase(mExceptionUpdates.begin(), mExceptionUpdates.end());
    mVectorElementUpdates.erase(mVectorElementUpdates.begin(), mVectorElementUpdates.end());

    sTrapTrace.clear();
    mLastStepWasSelfLoop = false;
    // Decode in the pre-step translation/privilege context, including xRET/traps.
    uint64 rval = 0ull;
    uint64 rmask = 0ull;
    ReadRegister(cpuid, "PC", &rval, &rmask);
    uint64_t pc_before_step = rval;
    std::string opcode;
    std::string disassembly;
    GetDisassembly(cpuid, &pc_before_step, opcode, disassembly);

    // The standalone Handcar library does not emit GPR callbacks. Snapshot the
    // architectural GPRs so FORCE still receives changes produced by the step.
    std::array<uint64, 32> gpr_values_before;
    std::array<uint64, 32> gpr_masks;
    for (uint32 reg_index = 0; reg_index < gpr_values_before.size(); ++reg_index) {
      const string reg_name = "x" + to_string(reg_index);
      ReadRegister(cpuid, reg_name.c_str(), &gpr_values_before[reg_index], &gpr_masks[reg_index]);
    }

    // step the simulator; simulator returns after all updates recorded...
    sCollectTrapTrace = true;
    int step_status = mpSimDllAPI->step_simulator((int) cpuid, 1, 0);
    sCollectTrapTrace = false;
    if (0 != step_status) {
      stringstream err_stream;
      err_stream << "Simulator 'step_simulator' failed.\n";
      throw SimulationError(err_stream.str());
    }

    for (uint32 reg_index = 1; reg_index < gpr_values_before.size(); ++reg_index) {
      const string reg_name = "x" + to_string(reg_index);
      uint64 value_after = 0;
      uint64 mask_after = 0;
      ReadRegister(cpuid, reg_name.c_str(), &value_after, &mask_after);
      if (value_after != gpr_values_before[reg_index]) {
        RecordRegisterUpdate(cpuid, reg_name.c_str(), value_after, mask_after, "write");
      }
    }

    // Keep the next PC distinct from the address of the decoded instruction.
    ReadRegister(cpuid, "PC", &rval, &rmask);
    rval = mask_register_to_size("PC", rval);
    const uint64 encoding = std::stoull(opcode, nullptr, 16);
    mLastStepWasSelfLoop = (rval == mask_address_to_size(pc_before_step)) &&
      (encoding == 0x6f || encoding == 0xa001) && sTrapTrace.empty() && mExceptionUpdates.empty();

    //Bundle the vector register updates in with the regular register updates
    GetVectorRegisterUpdates(mRegisterUpdates);

    // print the step and updates information
    uint32 icount = UpdateCurrentInstructionCount(cpuid);
    PrintInstructionStep(mask_address_to_size(pc_before_step), cpuid, icount, opcode, disassembly);
    if (mOfsSimTrace.is_open()) {
      mOfsSimTrace << "Cpu " << dec << cpuid << " NextPC(VA) 0x"
        << hex << setfill('0') << setw(16) << rval << "\n";
      for (const auto& trap : sTrapTrace) {
        mOfsSimTrace << "Cpu " << dec << trap.cpu << " Trap " << trap.name
          << " cause=0x" << hex << trap.cause << " epc=0x" << trap.epc
          << " tval=0x" << trap.tval << " tval2=0x" << trap.tval2
          << " tinst=0x" << trap.tinst << " target=0x" << trap.target
          << " from_priv=" << dec << trap.from_priv << " from_v=" << trap.from_virt
          << " to_priv=" << trap.to_priv << " to_v=" << trap.to_virt << "\n";
      }
    }
    PrintRegisterUpdates();
    PrintMemoryUpdates();
    PrintMmuEvents();
    PrintExceptionUpdates();

    // retreive simulator step updates...
    GetRegisterUpdates(rRegUpdates);
    GetMemoryUpdates(rMemUpdates);
    GetMmuEvents(rMmuEvents);
    GetExceptionUpdates(rExceptUpdates);
  }
  
  void SimApiHANDCAR::RecordExceptionUpdate(const SimException *pException)
  {
    mExceptionUpdates.push_back(ExceptionUpdate(pException->mExceptionID, pException->mExceptionAttributes, pException->mpComments));
  }
  
  void SimApiHANDCAR::WakeUp(uint32 cpuId)
  {
  }

  void SimApiHANDCAR::TurnOn(uint32 cpuId)
  {
  }

  void SimApiHANDCAR::EnterSpeculativeMode(uint32 cpuId)
  {
    mInSpeculativeMode[cpuId] = uint32(1);
  }

  void SimApiHANDCAR::LeaveSpeculativeMode(uint32 cpuId)
  {
    mInSpeculativeMode[cpuId] = uint32(0);
  }

  string SimApiHANDCAR::BuildHandcarConfigurationString(const ApiSimConfig& rConfig)
  {
    stringstream config_stream;

    config_stream << "-p" << (rConfig.mChipNum * rConfig.mCoreNum * rConfig.mThreadNum) << " ";

    config_stream << "--varch=vlen:" << rConfig.mVectorRegLen << ",slen:" << rConfig.mVectorRegLen << ",elen:" << rConfig.mMaxVectorElemWidth;

    if (rConfig.mSimConfigString.size() > 0) {
      config_stream << " " << rConfig.mSimConfigString << " ";

      if (rConfig.mSimConfigString.find("RV32") != string::npos) {
        sXlen = 32;
      }

      if (rConfig.mSimConfigString.find("D") != string::npos) {
        sFlen = 64;
      }
    }

    if (rConfig.mAutoInitMem) {
      config_stream << "--auto-init-mem";
    }

    string config_str = config_stream.str();

    return config_str;
  }

}
