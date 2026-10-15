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
#ifndef Force_PyVirtualMemory_H
#define Force_PyVirtualMemory_H

#include "pybind11/pybind11.h"
#include "pybind11/stl.h"
#include <cstring>
#include <limits>
#include <memory>

#include "GenException.h"
#include "Generator.h"
#include "MemoryManager.h"
#include "Record.h"
#include "VmUtils.h"
#include "VmManager.h"
#include "PtgVmMapper.h"
#include "PagingInfo.h"
#include "Scheduler.h"
#include "SimAPI.h"
#include "ThreadContext.h"

namespace py = pybind11;

namespace Force {

  PYBIND11_MODULE(VirtualMemory, mod) {
    mod
      .def("beginPtgSwitch", []() {
          ThreadContext tc;
          Scheduler::Instance()->LookUpGenerator(tc.GetThreadId())->GetVmManager()->BeginPtgSwitch();
        })
      .def("bindPtgDataMapper", [](const std::string& library, uint64 handle, uint32 context,
          PtgVmMapper::Span gva, PtgVmMapper::Span gpa, const std::vector<PtgVmMapper::Span>& payload,
          uint64 vsatp, uint64 hgatp, const std::vector<uint64>& layouts) {
          ThreadContext tc;
          auto gen = Scheduler::Instance()->LookUpGenerator(tc.GetThreadId());
          std::unique_ptr<PtgVmMapper> mapper(new PtgVmMapper(
              gen, library, handle, context, gva, gpa, payload, vsatp, hgatp, layouts));
          gen->GetVmManager()->BindPtgDataMapper(std::move(mapper));
        })
      .def("dropPtgBinding", [](uint64 handle) {
          ThreadContext tc;
          Scheduler::Instance()->LookUpGenerator(tc.GetThreadId())->GetVmManager()->DropPtgBinding(handle);
        })
      .def("endPtgAddressScope", []() {
          ThreadContext tc;
          auto gen = Scheduler::Instance()->LookUpGenerator(tc.GetThreadId());
          uint64 vs = 0, gs = 0, mask = 0;
          gen->GetSimAPI()->ReadRegister(0, "vsatp", &vs, &mask);
          gen->GetSimAPI()->ReadRegister(0, "hgatp", &gs, &mask);
          if (vs || gs) throw std::runtime_error("clear guest roots before leaving PTG address scope");
          gen->GetVmManager()->EndPtgAddressScope();
        })
      .def("ptgTranslationRange", [](uint64 va) -> py::object {
          ThreadContext tc;
          auto gen = Scheduler::Instance()->LookUpGenerator(tc.GetThreadId());
          auto mapper = gen->GetVmManager()->PtgDataMapper();
          if (!mapper) throw std::runtime_error("no PTG data mapper is bound");
          TranslationRange range;
          if (!mapper->GetTranslationRange(va, range)) return py::none();
          return py::make_tuple(range.Lower(), range.Upper(), range.PhysicalLower(), range.PhysicalUpper());
        })
      .def("getPagingMode",
        []() {
          ThreadContext thread_context;

          Scheduler* scheduler = Scheduler::Instance();
          Generator* generator = scheduler->LookUpGenerator(thread_context.GetThreadId());
          const PagingInfo* paging_info = generator->GetPagingInfo();
          return paging_info->GetPagingMode();
        })
      .def("writePhysicalMemory",
        [](uint32_t mem_bank, uint64_t address, py::bytes data) {
          ThreadContext thread_context;

          Scheduler* scheduler = Scheduler::Instance();
          Generator* generator = scheduler->LookUpGenerator(thread_context.GetThreadId());
          SimAPI* sim_api = generator->GetSimAPI();

          std::string data_str = data;
          if (data_str.empty()) return;
          if (data_str.size() > std::numeric_limits<uint32_t>::max() ||
              address > std::numeric_limits<uint64_t>::max() - (data_str.size() - 1))
            throw py::value_error("physical memory write range overflows");
          auto memory = MemoryManager::Instance();
          if (mem_bank >= memory->NumberBanks())
            throw py::value_error("invalid physical memory bank");
          const uint32_t size = data_str.size();
          std::unique_ptr<uint8[]> bytes(new uint8[size]);
          std::unique_ptr<uint8[]> attrs(new uint8[size]);
          std::memcpy(bytes.get(), data_str.data(), size);
          memory->GetMemoryAttributes(PaTuple(address, mem_bank), size, attrs.get());
          // Preserve initial bytes for ELF output and current bytes for the generator.
          // This is an immediate host write, not a deferred initialization record.
          MemoryInitRecord record(thread_context.GetThreadId(), size, 1, EMemDataType::Data);
          record.SetDataWithAttributes(address, mem_bank, bytes.release(), attrs.release(), size);
          try {
            sim_api->WritePhysicalMemory(mem_bank, address, data_str.size(),
              reinterpret_cast<const unsigned char*>(data_str.data()));
            generator->InitializeMemory(&record);
            memory->GetMemoryBank(mem_bank)->WriteMemory(address, record.InitData(), size);
          } catch (const SimulationError& e) {
            PyErr_SetString(PyExc_RuntimeError, e.what());
            throw py::error_already_set();
          }
        })
      ;
  }

}

#endif  // Force_PyVirtualMemory_H
