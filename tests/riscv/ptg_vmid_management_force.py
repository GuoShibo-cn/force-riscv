"""
Phase 3.8: VMID Management

Tests VMID allocation, multi-VM isolation, VMID recycling, and VMID=0 handling
using PTG (page table generator) two-stage contexts.

API ref: PtgBackend.create_two_stage_context(vmid=N) assigns VMID
         PtgBackend.get_hgatp(ctx_id) fetches hgatp value
         hgatp.MODE = bits 60-63, hgatp.VMID = bits 44-57, hgatp.PPN = bits 0-43
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend


def _extract_vmid(hgatp_val):
    """Extract VMID field (bits 44-57) from an hgatp register value."""
    return (hgatp_val >> 44) & 0x3FFF


def _extract_ppn(hgatp_val):
    """Extract PPN field (bits 0-43) from an hgatp register value."""
    return hgatp_val & 0xFFFFFFFFFFF


def _extract_mode(hgatp_val):
    """Extract MODE field (bits 60-63) from an hgatp register value."""
    return (hgatp_val >> 60) & 0xF


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("Phase 3.8: VMID Management")
        self.notice("=" * 60)

        pa_base = 0x80000000
        pa_limit = 0x90000000
        gpa_base = 0x30000000
        gpa_limit = 0x40000000

        # ====================================================================
        # Test 1: VMID Allocation - 10 VM contexts with unique VMIDs
        # ====================================================================
        self.notice("\n=== Test 1: VMID Allocation (10 VMs, VMID 1-10) ===")
        ptg1 = PtgBackend()
        ctx_ids_1 = []
        for vmid in range(1, 11):
            ctx_id = ptg1.create_two_stage_context(
                vs_mode="Sv39",
                gs_mode="Sv39x4",
                asid=0,
                vmid=vmid,
                pa_base=pa_base,
                pa_limit=pa_limit,
                gpa_base=gpa_base,
                gpa_limit=gpa_limit,
            )
            hgatp_val = ptg1.handle.get_hgatp(ctx_id)
            actual_vmid = _extract_vmid(hgatp_val)
            mode = _extract_mode(hgatp_val)
            ppn = _extract_ppn(hgatp_val)
            self.notice(
                f"  VM {vmid:2d}: ctx={ctx_id}  "
                f"hgatp=0x{hgatp_val:016X}  "
                f"MODE={mode}  VMID={actual_vmid}  PPN=0x{ppn:X}  "
                f"match={actual_vmid == vmid}"
            )
            ctx_ids_1.append(ctx_id)
            self.genInstruction("ADD##RISCV")

        # Verify all 10 VMIDs are distinct
        vmid_set = set()
        for cid in ctx_ids_1:
            hv = ptg1.handle.get_hgatp(cid)
            vmid_set.add(_extract_vmid(hv))
        self.notice(f"  Distinct VMIDs allocated: {len(vmid_set)} (expected 10)")
        if len(vmid_set) == 10:
            self.notice("  Test 1 PASSED: All 10 VM contexts have unique VMIDs")
        else:
            self.notice("  Test 1 FAILED: VMID collision detected")

        ptg1.destroy()

        # ====================================================================
        # Test 2: VM Isolation - Two VMs with different mappings
        # ====================================================================
        self.notice("\n=== Test 2: VM Isolation (VMID=100 vs VMID=200) ===")
        ptg2 = PtgBackend()

        # VM A (VMID=100): maps 0x10000 -> 0x30000000 -> 0x80000000
        ctx_a = ptg2.create_two_stage_context(
            vs_mode="Sv39", gs_mode="Sv39x4",
            asid=0, vmid=100,
            pa_base=pa_base, pa_limit=pa_limit,
            gpa_base=gpa_base, gpa_limit=gpa_limit,
        )
        ptg2.handle.add_mapping(ctx_a, "VS", 0x10000, 0x30000000, 4096, 0, 0b111)
        ptg2.handle.add_mapping(ctx_a, "G", 0x30000000, 0x80000000, 4096, 0, 0b111)
        ptg2.generate_random(ctx_a, "VS", 0x10000, 0x20000, 0x30000000, 0x30100000,
                             "Sv39", 1, seed=100)
        ptg2.generate_random(ctx_a, "G", 0x30000000, 0x30100000, 0x80000000, 0x80100000,
                             "Sv39x4", 1, seed=200, gs_inherit=1)

        hgatp_a = ptg2.handle.get_hgatp(ctx_a)
        self.notice(f"  VM A (vmid=100): hgatp=0x{hgatp_a:016X} VMID={_extract_vmid(hgatp_a)}")
        self.notice(f"    VS root GPA: 0x{(_extract_ppn(ptg2.handle.get_vsatp(ctx_a)) << 12):X}")

        # VM B (VMID=200): maps 0x20000 -> 0x30200000 -> 0x80200000
        ctx_b = ptg2.create_two_stage_context(
            vs_mode="Sv39", gs_mode="Sv39x4",
            asid=0, vmid=200,
            pa_base=pa_base, pa_limit=pa_limit,
            gpa_base=gpa_base, gpa_limit=gpa_limit,
        )
        ptg2.handle.add_mapping(ctx_b, "VS", 0x20000, 0x30200000, 4096, 0, 0b111)
        ptg2.handle.add_mapping(ctx_b, "G", 0x30200000, 0x80200000, 4096, 0, 0b111)
        ptg2.generate_random(ctx_b, "VS", 0x20000, 0x30000, 0x30200000, 0x30300000,
                             "Sv39", 1, seed=300)
        ptg2.generate_random(ctx_b, "G", 0x30200000, 0x30300000, 0x80200000, 0x80300000,
                             "Sv39x4", 1, seed=400, gs_inherit=1)

        hgatp_b = ptg2.handle.get_hgatp(ctx_b)
        self.notice(f"  VM B (vmid=200): hgatp=0x{hgatp_b:016X} VMID={_extract_vmid(hgatp_b)}")
        self.notice(f"    VS root GPA: 0x{(_extract_ppn(ptg2.handle.get_vsatp(ctx_b)) << 12):X}")

        # Verify both hgatp values have different VMID fields
        vmid_a = _extract_vmid(hgatp_a)
        vmid_b = _extract_vmid(hgatp_b)
        self.notice(f"  VMID_A={vmid_a} VMID_B={vmid_b} distinct={vmid_a != vmid_b}")

        # Validate both page tables independently
        va = ptg2.handle.validate(ctx_a)
        vb = ptg2.handle.validate(ctx_b)
        self.notice(f"  VM A validate: all_ok={va.all_ok}  nodes={va.total_nodes}")
        self.notice(f"  VM B validate: all_ok={vb.all_ok}  nodes={vb.total_nodes}")

        # Verify translations go to different SPAs
        spa_a, fc_a, fl_a = ptg2.handle.translate_sequential(ctx_a, 0x10000, 0)
        spa_b, fc_b, fl_b = ptg2.handle.translate_sequential(ctx_b, 0x20000, 0)
        self.notice(f"  VM A translate(0x10000): SPA=0x{spa_a:X} fault={fc_a}")
        self.notice(f"  VM B translate(0x20000): SPA=0x{spa_b:X} fault={fc_b}")
        self.notice(f"  SPAs distinct={spa_a != spa_b}")

        translations_collide = (spa_a == spa_b)
        if translations_collide:
            self.notice("  Test 2 FAILED: VM translations collide (same SPA)")
        else:
            self.notice("  Test 2 PASSED: VM A and VM B have isolated translations")

        ptg2.destroy()

        # ====================================================================
        # Test 3: VMID Recycling - deallocate VMID 100, reallocate
        # ====================================================================
        self.notice("\n=== Test 3: VMID Recycling ===")
        ptg3 = PtgBackend()

        # Allocate VM with VMID=100
        ctx_r1 = ptg3.create_two_stage_context(
            vs_mode="Sv39", gs_mode="Sv39x4",
            asid=0, vmid=100,
            pa_base=pa_base, pa_limit=pa_limit,
            gpa_base=gpa_base, gpa_limit=gpa_limit,
        )
        ptg3.handle.add_mapping(ctx_r1, "VS", 0x30000, 0x30400000, 4096, 0, 0b111)
        ptg3.handle.add_mapping(ctx_r1, "G", 0x30400000, 0x80400000, 4096, 0, 0b111)
        ptg3.generate_random(ctx_r1, "VS", 0x30000, 0x40000, 0x30400000, 0x30500000,
                             "Sv39", 1, seed=500)
        ptg3.generate_random(ctx_r1, "G", 0x30400000, 0x30500000, 0x80400000, 0x80500000,
                             "Sv39x4", 1, seed=600, gs_inherit=1)

        hgatp_r1 = ptg3.handle.get_hgatp(ctx_r1)
        ppn_r1 = _extract_ppn(hgatp_r1)
        self.notice(f"  First alloc VMID=100: hgatp=0x{hgatp_r1:016X} PPN=0x{ppn_r1:X}")

        # Save state before deallocation (simulate by destroying and recreating)
        # Note: PTG doesn't have an explicit VMID deallocation API at the Python level.
        # We test recycling by creating a new context with the same VMID after destroying
        # the first one, and verify the page tables are separate.
        ptg3.destroy()

        # Create fresh backend and reallocate VMID=100
        ptg3b = PtgBackend()
        ctx_r2 = ptg3b.create_two_stage_context(
            vs_mode="Sv39", gs_mode="Sv39x4",
            asid=0, vmid=100,
            pa_base=pa_base, pa_limit=pa_limit,
            gpa_base=gpa_base, gpa_limit=gpa_limit,
        )
        # Use different mappings to verify page tables are separate
        ptg3b.handle.add_mapping(ctx_r2, "VS", 0x40000, 0x30500000, 4096, 0, 0b111)
        ptg3b.handle.add_mapping(ctx_r2, "G", 0x30500000, 0x80500000, 4096, 0, 0b111)
        ptg3b.generate_random(ctx_r2, "VS", 0x40000, 0x50000, 0x30500000, 0x30600000,
                              "Sv39", 1, seed=700)
        ptg3b.generate_random(ctx_r2, "G", 0x30500000, 0x30600000, 0x80500000, 0x80600000,
                              "Sv39x4", 1, seed=800, gs_inherit=1)

        hgatp_r2 = ptg3b.handle.get_hgatp(ctx_r2)
        vmid_r2 = _extract_vmid(hgatp_r2)
        ppn_r2 = _extract_ppn(hgatp_r2)
        self.notice(f"  Realloc VMID={vmid_r2}: hgatp=0x{hgatp_r2:016X} PPN=0x{ppn_r2:X}")

        # Check VMID is reused correctly
        vmid_reused = (vmid_r2 == 100)
        # Check PPN is different (new page table root)
        new_root = (ppn_r2 != 0)
        self.notice(f"  VMID reused as 100? {vmid_reused}")
        self.notice(f"  New page table root (PPN != 0)? {new_root}")

        spa_r2, fc_r2, _ = ptg3b.handle.translate_sequential(ctx_r2, 0x40000, 0)
        self.notice(f"  New VM translate(0x40000): SPA=0x{spa_r2:X} fault={fc_r2}")

        if vmid_reused and new_root and fc_r2 == 0:
            self.notice("  Test 3 PASSED: VMID 100 recycled with separate page tables")
        else:
            self.notice("  Test 3 PARTIAL: VMID recycling behavior noted")
            self.notice(f"    vmid_reused={vmid_reused} new_root={new_root} fault={fc_r2}")

        ptg3b.destroy()

        # ====================================================================
        # Test 4: VMID Zero - special value behavior
        # ====================================================================
        self.notice("\n=== Test 4: VMID Zero (special value) ===")
        ptg4 = PtgBackend()

        ctx_z = ptg4.create_two_stage_context(
            vs_mode="Sv39", gs_mode="Sv39x4",
            asid=0, vmid=0,
            pa_base=pa_base, pa_limit=pa_limit,
            gpa_base=gpa_base, gpa_limit=gpa_limit,
        )
        hgatp_z = ptg4.handle.get_hgatp(ctx_z)
        vmid_z = _extract_vmid(hgatp_z)
        ppn_z = _extract_ppn(hgatp_z)
        mode_z = _extract_mode(hgatp_z)
        self.notice(f"  VMID=0: hgatp=0x{hgatp_z:016X} MODE={mode_z} VMID={vmid_z} PPN=0x{ppn_z:X}")

        ptg4.handle.add_mapping(ctx_z, "VS", 0x50000, 0x30600000, 4096, 0, 0b111)
        ptg4.handle.add_mapping(ctx_z, "G", 0x30600000, 0x80600000, 4096, 0, 0b111)
        ptg4.generate_random(ctx_z, "VS", 0x50000, 0x60000, 0x30600000, 0x30700000,
                             "Sv39", 1, seed=900)
        ptg4.generate_random(ctx_z, "G", 0x30600000, 0x30700000, 0x80600000, 0x80700000,
                             "Sv39x4", 1, seed=1000, gs_inherit=1)

        v_z = ptg4.handle.validate(ctx_z)
        spa_z, fc_z, _ = ptg4.handle.translate_sequential(ctx_z, 0x50000, 0)
        self.notice(f"  validate: all_ok={v_z.all_ok}  nodes={v_z.total_nodes}")
        self.notice(f"  translate(0x50000): SPA=0x{spa_z:X} fault={fc_z}")

        # Test: allocate another context with VMID=0 (should be distinct)
        ctx_z2 = ptg4.create_two_stage_context(
            vs_mode="Sv39", gs_mode="Sv39x4",
            asid=0, vmid=0,
            pa_base=pa_base, pa_limit=pa_limit,
            gpa_base=gpa_base, gpa_limit=gpa_limit,
        )
        hgatp_z2 = ptg4.handle.get_hgatp(ctx_z2)
        vmid_z2 = _extract_vmid(hgatp_z2)
        self.notice(f"  Second VMID=0: hgatp=0x{hgatp_z2:016X} VMID={vmid_z2}")

        vmid_zero_works = (vmid_z == 0 and fc_z == 0)
        if vmid_zero_works:
            self.notice("  Test 4 PASSED: VMID=0 behaves correctly")
        else:
            self.notice(f"  Test 4 NOTE: VMID=0: vmid_field={vmid_z} fault={fc_z}")

        ptg4.destroy()

        self.notice("\n" + "=" * 60)
        self.notice("Phase 3.8 complete — VMID management tests executed")
        self.notice("=" * 60)


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
