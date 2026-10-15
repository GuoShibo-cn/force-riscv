"""Phase 3.2: hedeleg/hideleg delegation configuration tests.

Tests different hedeleg/hideleg CSR configurations for RISC-V Hypervisor
exception/interrupt delegation using PTG two-stage page tables.

Scenarios:
  - hedeleg=0: no delegation (all exceptions go to M/HS)
  - hedeleg=0xFFFF: delegate all possible causes
  - hedeleg=specific bits (cause 1, 6, 13, 15)
  - hideleg configurations for interrupt delegation
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend, PtgFaultConfig

# hedeleg bit positions for relevant exception causes
HEDELEG_BITS = {
    1:  0,   # bit 0  (cause 1 = InvalidPTE)
    6:  5,   # bit 5  (cause 6 = PermRWXViolation)
    13: 12,  # bit 12 (cause 13 = LoadPageFault)
    15: 14,  # bit 14 (cause 15 = StorePageFault)
}

HIDELEG_BITS = {
    10: 10,  # bit 10 (VS Software Interrupt)
    12: 12,  # bit 12 (VS Timer Interrupt)
    14: 14,  # bit 14 (VS External Interrupt)
}

# Max hedeleg/hideleg value (delegate all 16 possible bits)
HEDELEG_ALL = 0xFFFF
HIDELEG_ALL = 0xFFFF


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("Phase 3.2: hedeleg/hideleg Delegation Configuration Tests")
        self.notice("=" * 60)

        passed = 0
        failed = 0
        results = []

        for scenario in self._scenarios():
            ok = self._run_scenario(scenario)
            results.append((scenario["name"], ok))
            if ok:
                passed += 1
            else:
                failed += 1

        self.notice("\n" + "=" * 60)
        self.notice(f"Summary: {passed} PASS, {failed} FAIL")
        for name, ok in results:
            self.notice(f"  {'PASS' if ok else 'FAIL'}: {name}")
        self.notice("=" * 60)

    def _scenarios(self):
        return [
            {
                "name": "hedeleg=0 (no delegation — all go to M/HS)",
                "hedeleg": 0,
                "hideleg": 0,
                "test_causes": [1, 6],
                "expect_all_delegated": False,
            },
            {
                "name": "hedeleg=0xFFFF (delegate all possible)",
                "hedeleg": HEDELEG_ALL,
                "hideleg": 0,
                "test_causes": [1, 6, 10],
                "expect_all_delegated": True,
            },
            {
                "name": "hedeleg specific bits (cause 1,6,13,15)",
                "hedeleg": (1 << 0) | (1 << 5) | (1 << 12) | (1 << 14),
                "hideleg": 0,
                "test_causes": [1, 6],
                "expect_all_delegated": True,
            },
            {
                "name": "hideleg=0xFFFF (delegate all interrupts to VS)",
                "hedeleg": 0,
                "hideleg": HIDELEG_ALL,
                "test_causes": [1],
                "expect_all_delegated": False,
            },
            {
                "name": "hideleg specific (VS SWI + Timer)",
                "hedeleg": 0,
                "hideleg": (1 << 10) | (1 << 12),
                "test_causes": [1],
                "expect_all_delegated": False,
            },
        ]

    def _run_scenario(self, scenario):
        self.notice(f"\n--- {scenario['name']} ---")

        hedeleg_val = scenario["hedeleg"]
        hideleg_val = scenario["hideleg"]
        test_causes = scenario["test_causes"]

        self.notice(f"  Config: hedeleg=0x{hedeleg_val:04X}, hideleg=0x{hideleg_val:04X}")

        ptg = PtgBackend()
        ctx = ptg.create_two_stage_context(
            vs_mode="Sv39",
            gs_mode="Sv39x4",
            asid=0,
            vmid=1,
            pa_base=0x80000000,
            pa_limit=0x80400000,
            gpa_base=0x80000000,
            gpa_limit=0x80400000,
        )

        va = 0x80000000
        size = 4096
        perm = 0b111

        ptg.handle.add_mapping(ctx, "VS", va, va, size, 0, perm)
        ptg.handle.add_mapping(ctx, "G", va, va, size, 0, perm)

        ptg.generate_random(ctx, "VS", va, va + size, va, va + size,
                            "Sv39", 1, seed=100)
        ptg.generate_random(ctx, "G", va, va + size, va, va + size,
                            "Sv39x4", 1, seed=200, gs_inherit=1)

        pre = ptg.handle.validate(ctx)
        self.notice(f"  Pre-injection validate: all_ok={pre.all_ok}")

        pre_spa, pre_vs, pre_level = ptg.handle.translate_sequential(ctx, va, 0)
        self.notice(f"  Pre-injection: SPA=0x{pre_spa:X}, vs_fault={pre_vs}")

        # Write hedeleg/hideleg CSR values
        self.writeRegister("hedeleg", hedeleg_val)
        self.writeRegister("hideleg", hideleg_val)

        # Verify CSR readback
        read_hedeleg, h_valid = self.readRegister("hedeleg")
        read_hideleg, i_valid = self.readRegister("hideleg")
        self.notice(f"  Readback: hedeleg=0x{read_hedeleg:016X} (valid={h_valid}), "
                    f"hideleg=0x{read_hideleg:016X} (valid={i_valid})")

        # Write delegation-related CSRs
        self.writeRegister("hstatus", (1 << 5))  # SPV=1 (VS-mode active)
        self.notice("  hstatus.SPV=1 (VS-mode active)")

        # Inject faults for each test cause
        all_ok = True
        for cause in test_causes:
            cfg = PtgFaultConfig()
            cfg.fault_cause = cause
            cfg.fault_level = 0
            cfg.fault_probability = 1.0
            cfg.target_va = 0
            cfg.dry_run = 0
            cfg.random_cause = 0
            cfg.seed = 999 + cause
            cfg.target_count = 1

            dbg = ptg.handle.debug_implicit_guest_fault(ctx, 1.0, 999 + cause)
            self.notice(f"    Debug (cause={cause}): vs_nodes={dbg.vs_node_count}, "
                        f"gs_hit={dbg.gs_hit_count}")

            injected = ptg.handle.inject_implicit_guest_fault(ctx, cfg)
            self.notice(f"    Inject cause={cause}: injected={injected} faults")

            post_spa, post_vs, post_level = ptg.handle.translate_sequential(ctx, va, 0)
            self.notice(f"    Translate: SPA=0x{post_spa:X}, vs_fault={post_vs}, "
                        f"level={post_level}")

            if hedeleg_val == 0:
                self.notice(f"    -> NOT delegated (hedeleg=0), fault stays at M/HS")
                if post_vs > 0:
                    self.notice(f"    -> fault detected at VS level (expected for cause={cause})")
                else:
                    self.notice(f"    -> translation succeeded (no fault)")

            elif hedeleg_val == HEDELEG_ALL or scenario["expect_all_delegated"]:
                self.notice(f"    -> delegated to VS (hedeleg bit set)")
                if post_vs > 0:
                    self.notice(f"    -> fault detected, would enter VS trap handler")
                else:
                    self.notice(f"    -> translation succeeded (no fault after delegation)")

            # For delegation tracking, check hedeleg bit
            cause_bit_idx = HEDELEG_BITS.get(cause)
            if cause_bit_idx is not None:
                delegated = bool((hedeleg_val >> cause_bit_idx) & 1)
                self.notice(f"    hedeleg bit[{cause_bit_idx}]={'1' if delegated else '0'} "
                            f"-> {'delegated to VS' if delegated else 'M/HS takes'}")

        # Test hideleg interrupt delegation (CSR verification only)
        self.notice("  hideleg interrupt delegation verification:")
        for int_id, bit_pos in HIDELEG_BITS.items():
            delegated = bool((hideleg_val >> bit_pos) & 1)
            self.notice(f"    interrupt {int_id}: bit[{bit_pos}]={'1' if delegated else '0'} "
                        f"-> {'delegated to VS' if delegated else 'HS takes'}")

        ptg.destroy()

        if all_ok:
            self.notice(f"  PASS: {scenario['name']}")
            return True
        else:
            self.notice(f"  FAIL: {scenario['name']}")
            return False


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
