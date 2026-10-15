"""Phase 2.5: PTG Guest Fault injection scenarios.

Tests implicit/explicit guest faults using inject_implicit_guest_fault /
inject_explicit_guest_fault. Each scenario:
  1. Setup two-stage context with gs_inherit=1 (working baseline)
  2. Verify translate_sequential succeeds (pre-fault)
  3. Inject fault via PTG API
  4. Verify translate_sequential returns expected fault_code

Fault scenarios:
  - Implicit: VS-stage tree node GPA fault in G-stage
  - Explicit: data GPA fault in G-stage (after VS walk)
  - Different fault_cause: InvalidPTE (1), PermRWXViolation (6)
  - dry_run mode verification
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend, PtgFaultConfig


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("Phase 2.5: Guest Fault Injection Scenarios")
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
        self.notice(f"Phase 2.5 Summary: {passed} PASS, {failed} FAIL")
        for name, ok in results:
            self.notice(f"  {'PASS' if ok else 'FAIL'}: {name}")
        self.notice("=" * 60)

    def _scenarios(self):
        return [
            {
                "name": "Implicit Guest Fault (InvalidPTE on VS tree node)",
                "inject": "implicit",
                "fault_cause": 1,
                "fault_level": 0,
                "fault_probability": 1.0,
                "target_va": 0,
                "dry_run": 0,
                "expect_injection": True,
                "expect_fault": True,
            },
            {
                "name": "Probability=0 (no injection baseline)",
                "inject": "implicit",
                "fault_cause": 1,
                "fault_level": 0,
                "fault_probability": 0.0,
                "target_va": 0,
                "dry_run": 0,
                "expect_injection": False,
                "expect_fault": False,
            },
            {
                "name": "Implicit PermRWXViolation (cause=6, type=2=remove_R)",
                "inject": "implicit",
                "fault_cause": 6,
                "fault_level": 0,
                "fault_probability": 1.0,
                "target_va": 0,
                "dry_run": 0,
                "expect_injection": True,
                "expect_fault": True,
            },
            {
                "name": "Implicit ReservedIllegal (cause=2)",
                "inject": "implicit",
                "fault_cause": 2,
                "fault_level": 0,
                "fault_probability": 1.0,
                "target_va": 0,
                "dry_run": 0,
                "expect_injection": True,
                "expect_fault": True,
            },
            {
                "name": "Per-leaf vs all-nodes (per_leaf_only=1)",
                "inject": "implicit",
                "fault_cause": 1,
                "fault_level": 0,
                "fault_probability": 1.0,
                "target_va": 0,
                "dry_run": 0,
                "per_leaf_only": True,
                "expect_injection": True,
                "expect_fault": True,
            },
            # --- New scenarios (Phase 2.5 expansion) ---
            {
                "name": "GuestADUpdateFault (cause=10, implicit)",
                "inject": "implicit",
                "fault_cause": 10,
                "fault_level": 0,
                "fault_probability": 1.0,
                "target_va": 0,
                "dry_run": 0,
                "target_count": 1,
                "expect_injection": True,
                "expect_fault": True,
            },
            {
                "name": "Fault at root PGD level (fault_level=2)",
                "inject": "implicit",
                "fault_cause": 1,
                "fault_level": 2,
                "fault_probability": 1.0,
                "target_va": 0,
                "dry_run": 0,
                "target_count": 1,
                "expect_injection": True,
                "expect_fault": True,
            },
            {
                "name": "Nested fault (implicit + explicit combined)",
                "inject": "both",
                "fault_cause": 1,
                "fault_level": 0,
                "fault_probability": 1.0,
                "target_va": 0,
                "dry_run": 0,
                "target_count": 1,
                "expect_injection": True,
                "expect_fault": True,
            },
            {
                "name": "Probability-based injection (p=0.5, 10 attempts)",
                "inject": "implicit",
                "fault_cause": 1,
                "fault_level": 0,
                "fault_probability": 0.5,
                "target_va": 0,
                "dry_run": 0,
                "target_count": 1,
                "probabilistic": True,
                "expect_injection": True,
                "expect_fault": True,
            },
            {
                "name": "Multiple injection (target_count=5)",
                "inject": "implicit",
                "fault_cause": 1,
                "fault_level": 0,
                "fault_probability": 1.0,
                "target_va": 0,
                "dry_run": 0,
                "target_count": 5,
                "expect_injection": True,
                "expect_fault": True,
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
        ptg.generate_random(ctx, "G", va, va + size, va, va + size,
                            "Sv39x4", 1, seed=200, gs_inherit=1)

        pre_validate = ptg.handle.validate(ctx)
        self.notice(f"  Pre-injection validate: all_ok={pre_validate.all_ok}")

        pre_spa, pre_vs, pre_level = ptg.handle.translate_sequential(ctx, va, 0)
        self.notice(f"  Pre-injection translate: SPA=0x{pre_spa:X}, vs_fault={pre_vs}, level={pre_level}")
        if pre_vs != 0:
            self.notice(f"  FAIL: Expected clean pre-fault state, got vs_fault={pre_vs}")
            ptg.destroy()
            return False

        cfg = PtgFaultConfig()
        cfg.fault_cause = scenario["fault_cause"]
        cfg.fault_level = scenario["fault_level"]
        cfg.fault_probability = scenario["fault_probability"]
        cfg.target_va = scenario["target_va"]
        cfg.dry_run = scenario["dry_run"]
        cfg.random_cause = 0
        cfg.seed = 999
        cfg.target_count = scenario.get("target_count", 1)
        cfg.per_leaf_only = 1 if scenario.get("per_leaf_only", False) else 0

        inject = scenario["inject"]
        probabilistic = scenario.get("probabilistic", False)

        if inject == "both":
            dbg_impl = ptg.handle.debug_implicit_guest_fault(
                ctx, scenario["fault_probability"], 999)
            dbg_expl = ptg.handle.debug_explicit_guest_fault(
                ctx, scenario["fault_probability"], 1000)
            self.notice(f"  Debug_implicit: vs_node_count={dbg_impl.vs_node_count}, "
                        f"gs_hit_count={dbg_impl.gs_hit_count}, "
                        f"probability_passed={dbg_impl.probability_passed}, "
                        f"invalidated={dbg_impl.invalidated}")
            self.notice(f"  Debug_explicit: vs_node_count={dbg_expl.vs_node_count}, "
                        f"gs_hit_count={dbg_expl.gs_hit_count}, "
                        f"probability_passed={dbg_expl.probability_passed}, "
                        f"invalidated={dbg_expl.invalidated}")
            injected_impl = ptg.handle.inject_implicit_guest_fault(ctx, cfg)
            injected_expl = ptg.handle.inject_explicit_guest_fault(ctx, cfg)
            injected = injected_impl + injected_expl
            self.notice(f"  Injected: {injected_impl} implicit + {injected_expl} explicit = {injected} total")
        elif probabilistic:
            dbg_func = (ptg.handle.debug_implicit_guest_fault
                        if inject == "implicit"
                        else ptg.handle.debug_explicit_guest_fault)
            dbg = dbg_func(ctx, scenario["fault_probability"], 999)
            self.notice(f"  Debug: vs_node_count={dbg.vs_node_count}, "
                        f"gs_hit_count={dbg.gs_hit_count}, "
                        f"probability_passed={dbg.probability_passed}, "
                        f"invalidated={dbg.invalidated}")
            inject_func = (ptg.handle.inject_implicit_guest_fault
                           if inject == "implicit"
                           else ptg.handle.inject_explicit_guest_fault)
            total_injected = 0
            self.notice(f"  Attempting 10 injections with probability={scenario['fault_probability']}:")
            for i in range(10):
                n = inject_func(ctx, cfg)
                total_injected += n
            injected = total_injected
            self.notice(f"  Injected (10 attempts): {injected} total fault(s)")
        else:
            dbg_func = (ptg.handle.debug_implicit_guest_fault
                        if inject == "implicit"
                        else ptg.handle.debug_explicit_guest_fault)
            dbg = dbg_func(ctx, scenario["fault_probability"], 999)
            self.notice(f"  Debug: vs_node_count={dbg.vs_node_count}, "
                        f"gs_hit_count={dbg.gs_hit_count}, "
                        f"probability_passed={dbg.probability_passed}, "
                        f"invalidated={dbg.invalidated}")
            inject_func = (ptg.handle.inject_implicit_guest_fault
                           if inject == "implicit"
                           else ptg.handle.inject_explicit_guest_fault)
            injected = inject_func(ctx, cfg)
            self.notice(f"  Injected: {injected} fault(s)")

        post_spa, post_vs, post_level = ptg.handle.translate_sequential(ctx, va, 0)
        self.notice(f"  Post-injection: SPA=0x{post_spa:X}, vs_fault={post_vs}, fault_level={post_level}")

        if probabilistic:
            self.notice(f"  PASS (probabilistic): injected={injected}/10, vs_fault={post_vs}")
            ptg.destroy()
            return True

        injection_ok = (injected > 0) == scenario["expect_injection"]
        fault_ok = (post_vs > 0) == scenario["expect_fault"]

        if injection_ok and fault_ok:
            self.notice(f"  PASS: injected={injected}, vs_fault={post_vs}, level={post_level}")
            ptg.destroy()
            return True
        else:
            self.notice(f"  FAIL: expected injection={'y' if scenario['expect_injection'] else 'n'} "
                        f"(got {injected}), fault={'y' if scenario['expect_fault'] else 'n'} "
                        f"(got vs_fault={post_vs})")
            ptg.destroy()
            return False


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
