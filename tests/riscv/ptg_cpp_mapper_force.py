"""Exercise the C++ genVA/genVAforPA path against published PTG contexts."""

import struct
import VirtualMemory
from base.Sequence import Sequence
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from riscv.Utils import LoadGPR64


BASE = 0x40000000
GPA = 0x60000000


class MainSequence(Sequence):
    def generate(self, **kwargs):
        contexts, pages, values = [], [], {}
        try:
            for index in range(2):
                ctx = self.genThread.createPtgVmContext(
                    "CppMapper" + str(index), asid=0x31 + index, vmid=1 + index,
                    table_ram=(0x88000000, 0x89000000),
                    data_ram=(0x84000000, 0x88000000),
                    gva_range=(BASE, BASE + 0x1000000), gpa_range=(GPA, GPA + 0x1000000),
                    table_gpa_range=(0x90000000, 0x91000000),
                )
                contexts.append(ctx)
                owned = []
                for page in range(4):
                    pa = ctx.map(BASE + page * 0x1000, GPA + page * 0x1000)
                    owned.append(pa)
                    ctx.map_alias(BASE + 0x10000 + page * 0x1000, GPA + page * 0x1000)
                    data = b"".join(struct.pack("<Q", self.initial(index + 1, page, word))
                                    for word in range(512))
                    ctx.initialize_data(pa, data)
                # Structurally valid mappings outside the C++ RW-supervisor contract.
                ctx.map(BASE + 0x4000, GPA + 0x4000, vs_perm=0x64)
                ctx.map(BASE + 0x5000, GPA + 0x5000, g_perm=0x71)
                ctx.map(BASE + 0x6000, GPA + 0x6000, vs_perm=0x73)
                ctx.publish()
                pages.append(owned)

            for iteration in range(32):
                index = iteration % 2
                ctx = contexts[index]
                self.genThread.activatePtgVmContext(ctx)
                address = self.genVA(Size=8, Align=8, Type="D", Range="0x40000000-0x40003fff")
                page, word = (address - BASE) // 0x1000, (address & 0xFFF) // 8
                pa = pages[index][page]
                info = VirtualMemory.ptgTranslationRange(address)
                if info != (BASE + page * 0x1000, BASE + (page + 1) * 0x1000 - 1,
                            pa, pa + 0xFFF):
                    self.error("C++ VmMapper translation range mismatch")
                expected = values.get((index, page, word), self.initial(index + 1, page, word))
                self.read(address, expected)
                value = 0x2200000000000000 | ((index + 1) << 48) | (iteration << 16) | word
                LoadGPR64(self.genThread).load(3, value)
                self.genInstruction("HSV.D##RISCV", {"rs1": 1, "rs2": 3, "NoRestriction": 1})
                values[index, page, word] = value
                alias = self.genVAforPA(PA=pa + (address & 0xFFF), Size=8, Align=8, Type="D")
                if alias not in (address, address + 0x10000):
                    self.error("C++ reverse alias selection mismatch")
                self.read(alias, value)

                if iteration == 0:
                    for low in (BASE + 0x4000, BASE + 0x5000, BASE + 0x6000, BASE + 0x8000):
                        self.reject(lambda low=low: self.genVA(
                            Size=8, Align=8, Type="D", Range=f"{low:#x}-{low + 0xfff:#x}"))
                    self.reject(lambda: self.genVA(Size=8, Align=8, Type="I"))
                    self.reject(lambda: self.genVA(Size=8, Align=8, ForceNewAddr=1))
                    self.reject(lambda: self.genVA(Size=8, Align=3, Type="D"))
                    self.reject(lambda: self.genVA(Size=0, Align=8, Type="D"))
                    self.reject(lambda: self.genVAforPA(PA=0x1234, Size=8, Align=8))
                    # A two-page request must not stitch separately reserved payload pages.
                    self.reject(lambda: self.genVA(Size=0x2000, Align=0x1000, Type="D",
                                                   Range="0x40000000-0x40003fff"))
                    self.reject(lambda: self.updateVm())
                    self.reject(lambda: self.genVmContext(PrivilegeLevel=1))
                    # Detect a software-only PTG mutation before using mismatched hardware roots.
                    ctx._backend.handle.remap_va(ctx.context_id, "G", GPA, pages[0][0] + 0x1000)
                    self.reject(lambda: self.genVA(Size=8, Align=8, Type="D"))
                    ctx._backend.handle.remap_va(ctx.context_id, "G", GPA, pages[0][0])

            contexts[1].close()
            self.reject(lambda: self.genVA(Size=8, Align=8, Type="D"))
            self.reject(lambda: self.genThread.activatePtgVmContext(contexts[1]))
            self.reject(lambda: self.genVA(Size=8, Align=8, Type="D"))
            self.genThread.activatePtgVmContext(contexts[0])
            self.read(BASE, values.get((0, 0, 0), self.initial(1, 0, 0)))
            self.notice("PTG CPP MAPPER: automatic VA/PA aliases, isolation and fail-closed checks PASS")
        finally:
            if contexts:
                self.genThread.deactivatePtgVmContext()
            for ctx in contexts:
                ctx.close()

    @staticmethod
    def initial(vmid, page, word):
        return 0x1000000000000000 | (vmid << 48) | (page << 32) | word

    def read(self, address, value):
        LoadGPR64(self.genThread).load(1, address)
        self.genInstruction("HLV.D##RISCV", {"rs1": 1, "rd": 2, "NoRestriction": 1})
        actual, valid = self.readRegister("x2")
        if not valid or actual != value:
            self.error(f"C++-selected HLV {address:#x}: {actual:#x}, expected {value:#x}")

    def reject(self, operation):
        try:
            operation()
        except Exception as error:
            if not any(token in str(error) for token in ("PTG", "ConstraintSet is empty")):
                raise
        else:
            self.error("Unsupported PTG address operation was accepted")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
