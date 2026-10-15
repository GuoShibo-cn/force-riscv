"""Exercise FORCE allocation/reservation exclusion around a PTG-owned table pool."""

import struct

from base.Sequence import Sequence
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from riscv.Utils import LoadGPR64
from riscv.paging.PtgBackend import PtgBackend


class MainSequence(Sequence):
    def generate(self, **kargs):
        size = 0x100000
        with self.threadLockingContext():
            span = self.genPA(Size=2 * size, Align=0x4000, Type="D", ForceNewAddr=1,
                              Range="0x88000000-0x88ffffff")
            self.reserveMemoryRange("ExistingPoolNeighbor", span, size, 0)
        sentinel = 0x123456789ABCDEF0
        self.genThread.writePhysicalMemory(span, struct.pack("<Q", sentinel), 0)
        ptg = PtgBackend.with_reserved_table_pool(
            self.genThread, "PTGPoolContract", size, span, span + 2 * size
        )
        try:
            if ptg.table_pool.base != span + size:
                self.error("PTG pool overlaps an existing FORCE reservation")
            ctx = ptg.create_two_stage_context(
                asid=1, vmid=1, gpa_base=0x90000000, gpa_limit=0x91000000
            )
            ptg.handle.add_mapping(ctx, "VS", 0x40000000, 0x60000000, 0x1000, perm=0x63)
            ptg.handle.add_mapping(ctx, "G", 0x60000000, 0x110000000, 0x1000, perm=0x73)
            with ptg.capture_export_layout(ctx, "VS") as vs:
                with ptg.capture_export_layout(ctx, "G") as gs:
                    ptg.load_export_layouts((vs, gs), self.genThread)
            # A reservation controls allocation, not explicit architectural reads.
            LoadGPR64(self.genThread).load(1, span)
            self.genInstruction("LD##RISCV", {"rd": 2, "rs1": 1, "simm12": 0,
                                               "NoRestriction": 1})
            value, valid = self.readRegister("x2")
            if not valid or value != sentinel:
                self.error(
                    f"Neighbor readback 0x{value:X}, expected 0x{sentinel:X}, valid={valid}"
                )
            pool = ptg.table_pool
        finally:
            ptg.destroy()

        # PTG handle destruction must not return still-live table backing to the generator.
        try:
            self.genPA(Size=0x1000, Align=0x1000, Type="D", ForceNewAddr=1,
                       Range="0x%x-0x%x" % (pool.base, pool.limit - 1))
        except Exception as error:
            if "ConstraintSet is empty" not in str(error):
                raise
        else:
            self.error("destroying PTG made its reserved backing available to FORCE")
        self.notice("PTG OWNED POOL: existing reservation and neighbor preserved; reuse rejected")


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
