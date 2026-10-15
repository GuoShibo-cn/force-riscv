#
# Copyright (C) [2020] Futurewei Technologies, Inc.
#
# FORCE-RISCV is licensed under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance
#  with the License.  You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES
# OF ANY KIND, EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import StateTransition
from Enums import EStateElementType

import riscv.PcConfig as PcConfig
from base.GenThread import (
    GenThread,
    GenThreadSetupSequence,
)
from riscv.StateTransitionHandlerRISCV import *
from riscv.exception_handlers.ExceptionHandlerManagerRISCV import (
    ExceptionHandlerManagerRISCV,
)
from riscv.exception_handlers.ExceptionsFactoryRISCV import (
    ExceptionsFactoryRISCV,
)


class GenThreadSetupSeqRISCV(GenThreadSetupSequence):
    """Inherit from GenThreadSetupSequence, return RISCV specific per-thread
    initial information."""

    def __init__(self, gen_thread, name):
        super().__init__(gen_thread, name)

    def setupBootRegion(self):
        """Setup memory region for boot instructions"""
        self.virtualMemoryRequest(
            "PhysicalRegion",
            {
                "RegionType": "BootRegion",
                "Size": PcConfig.get_boot_region_size(),
                "Type": "I",
                "Bank": 0,
            },
        )

    def setupEssentials(self):
        """Setup essentials like key register fields, etc"""
        self.genSequence("InitialSetup")
        self.updateVm()
        self.genThread.installAddressTable()

        no_handler, valid = self.getOption("NoHandler")
        if (not valid) or (not no_handler):
            self.genThread.installHandlers()

        handler_set, valid = self.getOption("handlers_set")
        if valid:
            self.genThread.specifyExceptionHandlerSet(handler_set)

    def getInitialPC(self):
        """Return initial main test PC for the generator thread"""
        return PcConfig.get_initial_pc(self.genThread.genThreadID)

    # Return boot code address for the generator thread
    def getBootPC(self):
        return PcConfig.get_boot_pc(self.genThread.genThreadID)

    def setDefaultStateTransitionHandlers(self):
        """Set the default StateTransitionHandlers to process StateElements of
        each type."""
        StateTransition.setDefaultStateTransitionHandler(
            MemoryStateTransitionHandlerRISCV(self.genThread),
            EStateElementType.Memory,
        )
        StateTransition.setDefaultStateTransitionHandler(
            VectorRegisterStateTransitionHandlerRISCV(self.genThread),
            EStateElementType.VectorRegister,
        )
        StateTransition.setDefaultStateTransitionHandler(
            SystemRegisterStateTransitionHandlerRISCV(self.genThread),
            EStateElementType.SystemRegister,
        )
        StateTransition.setDefaultStateTransitionHandler(
            GprStateTransitionHandlerRISCV(self.genThread),
            EStateElementType.GPR,
        )
        StateTransition.setDefaultStateTransitionHandler(
            VmContextStateTransitionHandlerRISCV(self.genThread),
            EStateElementType.VmContext,
        )
        StateTransition.setDefaultStateTransitionHandler(
            PrivilegeLevelStateTransitionHandlerRISCV(self.genThread),
            EStateElementType.PrivilegeLevel,
        )
        StateTransition.setDefaultStateTransitionHandler(
            PcStateTransitionHandlerRISCV(self.genThread), EStateElementType.PC
        )
        StateTransition.setDefaultStateTransitionHandler(
            FloatingPointRegisterStateTransitionHandlerRISCV(self.genThread),
            EStateElementType.FloatingPointRegister,
        )


#  GenThreadRISCV class
#  RISCV class representing generator thread
class GenThreadRISCV(GenThread):
    def __init__(self, gen_id, interface):
        super().__init__(gen_id, interface)
        self._ptg_contexts = {}
        self._active_ptg_context = None
        self.exceptionHandlerManager = ExceptionHandlerManagerRISCV(self, ExceptionsFactoryRISCV())
        self.addressTableManager = None
        self.fastMode = False

    # Called to assign sequences to be run at setup stage
    def assignSetupSequences(self):
        self.addSetupSequence(GenThreadSetupSeqRISCV)

    # Called to install exception handlers.
    def installHandlers(self):
        # generate exception handlers...
        self.exceptionHandlerManager.run(address_table_manager=self.addressTableManager)

        # assign SystemCallSequence to handle system call
        from riscv.SystemCallSequence import SystemCallSequence

        self.systemCallSequence = SystemCallSequence

        # create SelfHostedDebugSequence instance...
        #   from riscv.SelfHostedDebugSequence import SelfHostedDebugSequence

    def installAddressTable(self):
        from riscv.AddressTable import AddressTableManagerRISCV

        if self.addressTableManager is None:
            self.addressTableManager = AddressTableManagerRISCV(self)
        self.addressTableManager.run()

    def setupVsStagePaging(self, mode="Sv39"):
        """Setup VS-stage page tables (GVA -> GPA)"""
        # Initialize vsatp register with the specified paging mode
        self.initializeRegister("vsatp", "MODE", self._mode_to_value(mode))
        print(f"  [VS-Stage] vsatp.MODE set to {mode} (value={self._mode_to_value(mode)})")

    def setupGStagePaging(self, mode="Sv39x4", vmid=None):
        """Setup G-stage page tables (GPA -> SPA)

        Args:
            mode: G-stage paging mode (Sv39x4/Sv48x4/Sv57x4/Bare)
            vmid: VMID for hgatp.VMID field. If None, defaults to 0 (shared VMID).
        """
        self.initializeRegister("hgatp", "PPN", 0)
        self.initializeRegister("hgatp", "VMID", vmid if vmid is not None else 0)
        self.initializeRegister("hgatp", "MODE", self._mode_to_value(mode))
        print(f"  [G-Stage] hgatp.MODE={mode} VMID={vmid if vmid is not None else 0}")

    def setupTwoStageVm(self):
        """Trigger VM update after two-stage paging configuration"""
        self.updateVm({})

    def allocateVMID(self, min_vmid=1, max_vmid=0x3FFF):
        """Allocate a unique VMID in the hgatp.VMID range (14-bit, 1-16383).

        VMID=0 is reserved for shared/no-ASID contexts. Returns the new VMID.
        The allocator is per-GenThread; each thread maintains its own allocated set.
        """
        if not hasattr(self, "_allocated_vmids"):
            self._allocated_vmids = set()
        import RandomUtils
        for _ in range(100):
            candidate = RandomUtils.random32(min_vmid, max_vmid)
            if candidate not in self._allocated_vmids:
                self._allocated_vmids.add(candidate)
                return candidate
        # Fallback: sequential allocation after range exhaustion
        next_vmid = max(self._allocated_vmids) + 1 if self._allocated_vmids else min_vmid
        if next_vmid > max_vmid:
            raise ValueError(f"VMID range exhausted ({min_vmid}-{max_vmid})")
        self._allocated_vmids.add(next_vmid)
        return next_vmid

    def releaseVMID(self, vmid):
        """Release a previously allocated VMID back to the pool."""
        if vmid in self._ptg_contexts:
            raise ValueError("managed VMID remains reserved for the generation session")
        if hasattr(self, "_allocated_vmids") and vmid in self._allocated_vmids:
            self._allocated_vmids.discard(vmid)

    def _mode_to_value(self, mode):
        mode_map = {
            "Bare": 0,
            "Sv32": 1,
            "Sv39": 8,
            "Sv48": 9,
            "Sv57": 10,
            "Sv39x4": 8,
            "Sv48x4": 9,
            "Sv57x4": 10,
        }
        return mode_map.get(mode, 0)

    def setupPtgCSRsForHart(self, ptg_handle, ctx_id, hart_id, vs_mode=None, g_mode=None, vmid=None):
        """Override CSR fields for a specific Hart to point to PTG page tables.

        Like setupPtgCSRs but takes hart_id for per-Hart isolation.
        Args:
            ptg_handle: PtgHandle instance
            ctx_id: PTG context ID
            hart_id: Hart index (0..num_harts-1)
            vs_mode: Paging mode for VS-stage (Sv39/Sv48/Sv57)
            g_mode: Paging mode for G-stage (Sv39x4/Sv48x4/Sv57x4)
            vmid: Optional VMID override; if None, derives from ctx_id
        """
        PPN_MASK_44 = (1 << 44) - 1

        if g_mode is not None:
            vsatp_val = ptg_handle.get_vsatp(ctx_id)
            hgatp_val = ptg_handle.get_hgatp(ctx_id)
            vs_mode_val = self._mode_to_value(vs_mode)
            hg_mode_val = self._mode_to_value(g_mode)
            vs_asid_val = (vsatp_val >> 44) & 0xFFFF
            vs_ppn_val = vsatp_val & PPN_MASK_44
            hg_vmid_val = vmid if vmid is not None else ((hgatp_val >> 44) & 0x3FFF)
            hg_ppn_val = hgatp_val & PPN_MASK_44
            vsatp_csr = (vs_mode_val << 60) | (vs_asid_val << 44) | vs_ppn_val
            hgatp_csr = (hg_mode_val << 60) | (hg_vmid_val << 44) | hg_ppn_val
            self.writeRegister("vsatp", "", vsatp_csr, False)
            print(f"  [setupPtgCSRsForHart] hart={hart_id} vsatp=0x{vsatp_csr:016X}")
            # hgatp: use LoadGPR64 + CSRRW (writeRegister fails due to boot=0)
            from riscv.Utils import LoadGPR64
            load_gpr = LoadGPR64(self)
            load_gpr.load(5, hgatp_csr)
            self.genInstruction("CSRRW#register#RISCV", {
                "rd": 0,
                "rs1": 5,
                "csr": 0x680,
                "NoRestriction": 1,
            })
            print(f"  [setupPtgCSRsForHart] hart={hart_id} hgatp=0x{hgatp_csr:016X}")
        else:
            satp_val = ptg_handle.get_satp(ctx_id)
            mode_val = self._mode_to_value(vs_mode or "Sv39")
            ppn_val = satp_val & PPN_MASK_44
            satp_csr = (mode_val << 60) | ppn_val
            self.setRegisterValueWithUpdate("satp", satp_csr, hart_id)
            print(f"  [setupPtgCSRsForHart] hart={hart_id} satp=0x{satp_csr:016X}")

    def createPtgVmContext(self, name, asid, vmid, **kwargs):
        """Create a managed PTG context with caller-approved address/RAM constraints."""
        from riscv.paging.PtgVmContext import PtgVmContext
        if vmid in self._ptg_contexts:
            raise ValueError("managed VMID remains reserved for the generation session")
        context = PtgVmContext(self, name, asid, vmid, **kwargs)
        self._ptg_contexts[vmid] = context
        if not hasattr(self, "_allocated_vmids"):
            self._allocated_vmids = set()
        self._allocated_vmids.add(vmid)
        return context

    def activatePtgVmContext(self, context, scratch=5):
        """Activate one of this GenThread's managed contexts using actual CSR/fence instructions."""
        if self._ptg_contexts.get(context.vmid) is not context:
            raise ValueError("PTG context belongs to another GenThread")
        import VirtualMemory
        required = ("beginPtgSwitch", "bindPtgDataMapper", "dropPtgBinding", "endPtgAddressScope")
        if any(not hasattr(VirtualMemory, name) for name in required):
            raise RuntimeError("FORCE binary lacks the C++ PTG mapper bridge; rebuild friscv")
        VirtualMemory.beginPtgSwitch()
        self._active_ptg_context = None
        context.activate(scratch)
        handle = context._backend.handle
        VirtualMemory.bindPtgDataMapper(
            handle._lib._name, handle._handle, context.context_id, context._gva, context._gpa,
            context._data, *context._roots, [layout._layout_id for layout in context._layouts]
        )
        self._active_ptg_context = context

    def _ptgContextClosing(self, context):
        if self._active_ptg_context is context:
            import VirtualMemory
            VirtualMemory.dropPtgBinding(context._backend.handle._handle)
            self._active_ptg_context = None

    def deactivatePtgVmContext(self):
        """Clear guest roots/fence before allowing native address generation again."""
        import VirtualMemory
        if self.getPEstate("PrivilegeLevel") != 3:
            raise ValueError("PTG deactivation requires M-mode")
        VirtualMemory.beginPtgSwitch()
        self._active_ptg_context = None
        for csr, fence in ((0x280, "HFENCE.VVMA##RISCV"), (0x680, "HFENCE.GVMA##RISCV")):
            self.genInstruction("CSRRW#register#RISCV", {
                "rd": 0, "rs1": 0, "csr": csr, "NoRestriction": 1,
            })
            self.genInstruction(fence, {"rs1": 0, "rs2": 0, "NoRestriction": 1})
        VirtualMemory.endPtgAddressScope()

    def setupPtgCSRs(self, ptg_handle, ctx_id, vs_mode=None, g_mode=None):
        """Override satp/vsatp/hgatp CSR fields to point to PTG-generated page tables.

        Must be called AFTER built-in updateVm() completes to ensure CSR overrides
        persist. Uses initializeRegister for uninitialized fields (PPN, VMID) and
        writeRegister for already-initialized fields (MODE).

        The caller should trigger a final updateVm() after this method if the new
        CSR values need to be propagated to the ISS simulator.

        Args:
            ptg_handle: PtgHandle instance (from PtgBackend.handle)
            ctx_id: PTG context ID
            vs_mode: Paging mode for S/VS-stage (e.g. \"Sv39\"). If g_mode is None,
                     sets satp (S-stage single-stage). If g_mode is also set,
                     sets vsatp (VS-stage two-stage).
            g_mode: G-stage paging mode (e.g. \"Sv39x4\"). When set along with
                    vs_mode, enables two-stage vsatp + hgatp override.
        """
        PPN_MASK_44 = (1 << 44) - 1

        if vs_mode is not None and g_mode is None:
            satp_val = ptg_handle.get_satp(ctx_id)
            mode_val = self._mode_to_value(vs_mode)
            ppn_val = satp_val & PPN_MASK_44
            self.initializeRegister("satp", "PPN", ppn_val)
            self.writeRegister("satp", "MODE", mode_val, False)
            print(f"  [setupPtgCSRs] satp.MODE={mode_val} PPN=0x{ppn_val:X}")

        elif vs_mode is not None and g_mode is not None:
            vsatp_val = ptg_handle.get_vsatp(ctx_id)
            hgatp_val = ptg_handle.get_hgatp(ctx_id)
            vs_mode_val = self._mode_to_value(vs_mode)
            vs_asid_val = (vsatp_val >> 44) & 0xFFFF
            vs_ppn_val = vsatp_val & PPN_MASK_44
            hg_mode_val = self._mode_to_value(g_mode)
            hg_vmid_val = (hgatp_val >> 44) & 0x3FFF
            hg_ppn_val = hgatp_val & PPN_MASK_44
            # Rebuild full CSR values with our MODE, PPN, VMID fields
            vsatp_csr = (vs_mode_val << 60) | (vs_asid_val << 44) | vs_ppn_val
            hgatp_csr = (hg_mode_val << 60) | (hg_vmid_val << 44) | hg_ppn_val
            # Use LoadGPR64 + CSRRW for both vsatp and hgatp to ensure
            # the ISS simulator gets the updated CSR values.
            from riscv.Utils import LoadGPR64
            # Write vsatp (CSR 0x280)
            load_gpr_vs = LoadGPR64(self)
            load_gpr_vs.load(6, vsatp_csr)
            self.genInstruction("CSRRW#register#RISCV", {
                "rd": 0,
                "rs1": 6,
                "csr": 0x280,
                "NoRestriction": 1,
            })
            print(f"  [setupPtgCSRs] vsatp CSR=0x{vsatp_csr:016X} (via CSRRW)")
            # Write hgatp (CSR 0x680) - writeRegister fails due to boot=0
            load_gpr_hg = LoadGPR64(self)
            load_gpr_hg.load(5, hgatp_csr)
            self.genInstruction("CSRRW#register#RISCV", {
                "rd": 0,
                "rs1": 5,
                "csr": 0x680,
                "NoRestriction": 1,
            })
            print(f"  [setupPtgCSRs] hgatp CSR=0x{hgatp_csr:016X} (via CSRRW)")
