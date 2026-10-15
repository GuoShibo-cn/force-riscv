"""Managed PTG ranges and A/B/A context switching with persistent architectural stores."""

import struct

from base.Sequence import Sequence
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from riscv.Utils import LoadGPR64


GVA = 0x40000000
GPA = 0x60000000
ALIAS = GVA + 0x10000
SWITCH_COUNT = 64
INITIAL = (0x1111222233334444, 0xAAAABBBBCCCCDDDD)


class MainSequence(Sequence):
    def generate(self, **kargs):
        contexts = []
        try:
            addresses = []
            for index in range(2):
                context = self.genThread.createPtgVmContext(
                    "ManagedVM" + str(index), asid=0x11 + index, vmid=1 + index,
                    table_ram=(0x88000000, 0x89000000),
                    data_ram=(0x84000000 + index * 0x2000000, 0x86000000 + index * 0x2000000),
                    gva_range=(GVA, GVA + 0x1000000), gpa_range=(GPA, GPA + 0x1000000),
                    table_gpa_range=(0x90000000, 0x91000000),
                )
                contexts.append(context)
                try:
                    self.genThread.releaseVMID(context.vmid)
                except ValueError:
                    pass
                else:
                    self.error("A managed VMID was released while its tables remain live")
                spa = context.map(GVA, GPA)
                addresses.append(spa)
                context.map_alias(ALIAS, GPA)
                context.initialize_data(spa, struct.pack("<Q", INITIAL[index]))
                if context.translate(GVA + 8) != spa + 8 or context.reverse(spa + 8) != (
                        GVA + 8, ALIAS + 8):
                    self.error("Managed context forward/reverse mapping mismatch")
                # Two non-identical leaf-size compositions, with independent known sentinels.
                for slot, levels in enumerate(((1, 0), (0, 1)), 1):
                    va, ga = GVA + slot * 0x200000, GPA + slot * 0x200000
                    pa = context.map(va, ga, 0x200000, vs_level=levels[0], g_level=levels[1])
                    value = 0x1020304050607080 + index * 0x100 + slot
                    context.initialize_data(pa + 0x1238, struct.pack("<Q", value))
                    info = context.lookup(va + 0x1238)
                    if (info.gva_base, info.gpa_base, info.spa_base, info.size,
                            info.vs_level, info.g_level) != (
                            va + 0x1000, ga + 0x1000, pa + 0x1000, 0x1000, *levels):
                        self.error("Mixed-page translation range was not intersected")
                if context.lookup(GVA + 0xF00000) is not None:
                    self.error("Unmapped GVA was treated as mapped")
                context.publish()

            # All table/data initialization precedes switching. FPIX replays from the ELF
            # without table reloads; generation itself still initializes instruction bytes.
            expected = list(INITIAL)
            for switch in range(SWITCH_COUNT):
                index = switch % 2
                self.genThread.activatePtgVmContext(contexts[index])
                self._read(GVA, expected[index])
                value = 0x5566000000000000 | (index << 32) | switch
                LoadGPR64(self.genThread).load(1, GVA)
                LoadGPR64(self.genThread).load(3, value)
                self.genInstruction("HSV.D##RISCV", {
                    "rs1": 1, "rs2": 3, "NoRestriction": 1,
                })
                expected[index] = value
                self._read(ALIAS, value)
                if switch < 2:
                    for slot in (1, 2):
                        self._read(GVA + slot * 0x200000 + 0x1238,
                                   0x1020304050607080 + index * 0x100 + slot)

            if addresses[0] == addresses[1]:
                self.error("Distinct VM payload reservations alias unexpectedly")
            try:
                self.genThread.allocateVMID(min_vmid=1, max_vmid=2)
            except ValueError:
                pass
            else:
                self.error("The VMID allocator reused a managed context ID")
            self.notice("PTG MANAGED CONTEXT: 64 switches, aliases, mixed ranges and stores PASS")
        finally:
            if contexts:
                self.genThread.deactivatePtgVmContext()
            for context in contexts:
                context.close()

    def _read(self, address, expected):
        LoadGPR64(self.genThread).load(1, address)
        self.genInstruction("HLV.D##RISCV", {"rs1": 1, "rd": 2, "NoRestriction": 1})
        actual, valid = self.readRegister("x2")
        if not valid or actual != expected:
            self.error(f"Managed HLV {address:#x}: {actual:#x}, expected {expected:#x}")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
