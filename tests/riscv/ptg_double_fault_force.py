"""Phase 3.2: Simultaneous VS and G-stage double fault tests.

Tests the architectural priority when both VS-stage and G-stage page tables
are configured to fault on the same GVA access.

RISC-V Hypervisor priority rules:
  1. VS-stage faults (invalid PTE, reserved bits) are checked FIRST
     during the page walk. If VS-stage fails, G-stage is never consulted.
  2. G-stage faults (GuestLoad/Store/InstructionPageFault) only fire when
     VS-stage walk completes successfully.
  3. When BOTH stages are pre-configured to fault, the VS-stage fault
     takes priority because the walk terminates at VS-stage.
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend, PtgFaultConfig


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("Phase 3.2: Double Fault (VS + G simultaneous)")
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
                "name": "VS ReservedIllegal(1) + G no-mapping -> VS wins",
                "vs_cause": 1,          # ReservedIllegal at VS PTE
                "vs_level": 0,
                "gs_no_mapping": True,  # G-stage has no translation
                "expected_winner": "VS",
            },
            {
                "name": "VS PermRWX(6) + G ReservedIllegal(2) -> VS wins",
                "vs_cause": 6,          # PermRWXViolation at VS leaf
                "vs_level": 0,
                "gs_cause": 2,          # ReservedIllegal at G-stage
                "gs_level": 0,
                "gs_no_mapping": False,
                "expected_winner": "VS",
            },
            {
                "name": "VS InvalidPTE(1) + G ADUpdate(10) -> VS wins",
                "vs_cause": 1,
                "vs_level": 0,
                "gs_cause": 10,
                "gs_level": 0,
                "gs_no_mapping": False,
                "expected_winner": "VS",
            },
            {
                "name": "VS root level Reserved(2) + G leaf Invalid(1) -> VS wins",
                "vs_cause": 2,
                "vs_level": 2,          # root PGD level
                "gs_cause": 1,
                "gs_level": 0,
                "gs_no_mapping": False,
                "expected_winner": "VS",
            },
            {
                "name": "Both stages fault at leaf -> VS takes priority",
                "vs_cause": 1,
                "vs_level": 0,
                "gs_cause": 6,
                "gs_level": 0,
                "gs_no_mapping": False,
                "expected_winner": "VS",
            },
        ]

    def _run_scenario(self, scenario):
        self.notice(f"\n--- {scenario['name']} ---")

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

        gs_no_mapping = scenario.get("gs_no_mapping", False)
        if not gs_no_mapping:
            ptg.generate_random(ctx, "G", va, va + size, va, va + size,
                                "Sv39x4", 1, seed=200, gs_inherit=1)
            self.notice("  G-stage has VALID mappings")
        else:
            self.notice("  G-stage has NO mappings (inherently invalid)")

        pre = ptg.handle.validate(ctx)
        self.notice(f"  Pre-injection validate: all_ok={pre.all_ok}")

        pre_spa, pre_vs, pre_level = ptg.handle.translate_sequential(ctx, va, 0)
        self.notice(f"  Pre-injection: SPA=0x{pre_spa:X}, vs_fault={pre_vs}, level={pre_level}")

        # Inject VS-stage fault
        vs_cfg = PtgFaultConfig()
        vs_cfg.fault_cause = scenario["vs_cause"]
        vs_cfg.fault_level = scenario["vs_level"]
        vs_cfg.fault_probability = 1.0
        vs_cfg.target_va = 0
        vs_cfg.dry_run = 0
        vs_cfg.random_cause = 0
        vs_cfg.seed = 1000
        vs_cfg.target_count = 1

        injected_vs = ptg.handle.inject_implicit_guest_fault(ctx, vs_cfg)
        self.notice(f"  VS-stage fault injected: {injected_vs} "
                    f"(cause={scenario['vs_cause']})")

        # Inject G-stage fault (if not already inherently invalid)
        if not gs_no_mapping:
            gs_cfg = PtgFaultConfig()
            gs_cfg.fault_cause = scenario["gs_cause"]
            gs_cfg.fault_level = scenario["gs_level"]
            gs_cfg.fault_probability = 1.0
            gs_cfg.target_va = 0
            gs_cfg.dry_run = 0
            gs_cfg.random_cause = 0
            gs_cfg.seed = 2000
            gs_cfg.target_count = 1

            injected_gs = ptg.handle.inject_implicit_guest_fault(ctx, gs_cfg)
            self.notice(f"  G-stage fault injected: {injected_gs} "
                        f"(cause={scenario['gs_cause']})")
        else:
            self.notice("  G-stage is inherently invalid (no G page tables)")

        # Post-injection translation — both faults exist simultaneously
        post_spa, post_vs, post_level = ptg.handle.translate_sequential(ctx, va, 0)
        self.notice(f"  Post-injection: SPA=0x{post_spa:X}, vs_fault={post_vs}, "
                    f"level={post_level}")

        # Determine which fault fired
        if post_vs == 0:
            self.notice("  Result: No fault (translation succeeded)")
        elif post_vs >= 20:
            self.notice(f"  Result: G-stage fault (cause={post_vs}) — "
                        f"spec violation or unexpected")
        else:
            self.notice(f"  Result: VS-stage fault (cause={post_vs}) — "
                        f"VS wins priority (expected)")

        # Validate: VS-stage should always win for all scenarios
        # because VS is checked first during the two-stage walk
        expected_winner = scenario["expected_winner"]
        if expected_winner == "VS" and post_vs > 0 and post_vs < 20:
            self.notice(f"  PASS: VS fault (cause={post_vs}) fires before G-stage")
            ptg.destroy()
            return True
        elif expected_winner == "VS" and post_vs == 0:
            self.notice(f"  FAIL: Expected VS fault but translation succeeded")
            ptg.destroy()
            return False
        elif expected_winner == "VS" and post_vs >= 20:
            self.notice(f"  FAIL: Expected VS fault but G fault (cause={post_vs}) fired")
            ptg.destroy()
            return False
        else:
            self.notice(f"  FAIL: Unexpected fault stage (code={post_vs})")
            ptg.destroy()
            return False


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
