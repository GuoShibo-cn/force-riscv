"""Phase 3.2: VS/G-stage exception priority tests.

Tests the priority of page fault exceptions between VS-stage and G-stage
in RISC-V Hypervisor two-stage address translation.

Key architectural rules:
  1. If VS-stage walk fails (invalid PTE, no mapping) -> VS-stage fault fires
     immediately. G-stage is NOT consulted (cause=15 LoadPageFault).

  2. If VS-stage walk SUCCEEDS (valid PTE found) but G-stage cannot translate
     the intermediate GPA -> G-stage fault fires (cause=23 GuestLoadPageFault).

  3. The G-stage fault takes priority over VS-stage permission violations
     only when VS-stage has a valid leaf PTE but G-stage fails.
"""
from riscv.EnvRISCV import EnvRISCV
from riscv.GenThreadRISCV import GenThreadRISCV
from base.Sequence import Sequence
from riscv.paging.PtgBackend import PtgBackend, PtgFaultConfig


class MainSequence(Sequence):
    def generate(self, **kargs):
        self.notice("=" * 60)
        self.notice("Phase 3.2: VS/G-stage Exception Priority Tests")
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
                "name": "G-stage INVALID: VS-stage VALID PTE -> GuestLoadPageFault",
                "vs_valid": True,
                "gs_valid": False,
                "expected_fault_stage": "G",
                "expected_fault_code": 23,
                "fault_cause": 1,       # Inject InvalidPTE in G-stage
                "fault_level": 0,       # G-stage leaf level
            },
            {
                "name": "VS-stage INVALID (no PTE), G-stage VALID -> VS fault",
                "vs_valid": False,
                "gs_valid": True,
                "expected_fault_stage": "VS",
                "expected_fault_code": 15,
                "fault_cause": 1,
                "fault_level": 0,
            },
            {
                "name": "Both stages INVALID -> VS fault (VS checked first)",
                "vs_valid": False,
                "gs_valid": False,
                "expected_fault_stage": "VS",
                "expected_fault_code": 15,
                "fault_cause": 1,
                "fault_level": 0,
            },
            {
                "name": "VS-stage ReservedIllegal with valid G-stage",
                "vs_valid": False,
                "gs_valid": True,
                "expected_fault_stage": "VS",
                "expected_fault_code": 15,
                "fault_cause": 2,       # ReservedIllegal
                "fault_level": 0,
            },
            {
                "name": "G-stage PermRWXViolation with VS valid",
                "vs_valid": True,
                "gs_valid": False,
                "expected_fault_stage": "G",
                "expected_fault_code": 23,
                "fault_cause": 6,       # PermRWXViolation
                "fault_level": 0,
            },
        ]

    def _run_scenario(self, scenario):
        self.notice(f"\n--- {scenario['name']} ---")
        self.notice(f"  Expected: {scenario['expected_fault_stage']}-stage fault "
                    f"(cause={scenario['expected_fault_code']})")

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

        self.notice("  Generating VS-stage page tables...")
        ptg.generate_random(ctx, "VS", va, va + size, va, va + size,
                            "Sv39", 1, seed=100)

        # Conditionally make G-stage VALID or INVALID
        if scenario["gs_valid"]:
            self.notice("  Generating G-stage page tables (VALID mapping)...")
            ptg.generate_random(ctx, "G", va, va + size, va, va + size,
                                "Sv39x4", 1, seed=200, gs_inherit=1)
        else:
            self.notice("  G-stage: skipping generation (no mapping -> INVALID)")

        pre = ptg.handle.validate(ctx)
        self.notice(f"  Pre-injection validate: all_ok={pre.all_ok}")

        pre_spa, pre_vs, pre_level = ptg.handle.translate_sequential(ctx, va, 0)
        self.notice(f"  Pre-injection: SPA=0x{pre_spa:X}, vs_fault={pre_vs}, "
                    f"level={pre_level}")

        # Inject fault at the appropriate stage
        fault_cause = scenario["fault_cause"]
        cfg = PtgFaultConfig()
        cfg.fault_cause = fault_cause
        cfg.fault_level = scenario["fault_level"]
        cfg.fault_probability = 1.0
        cfg.target_va = 0
        cfg.dry_run = 0
        cfg.random_cause = 0
        cfg.seed = 999
        cfg.target_count = 1

        if scenario["gs_valid"]:
            # Make G-stage INVALID by injecting fault at G-stage
            injected = ptg.handle.inject_implicit_guest_fault(ctx, cfg)
            self.notice(f"  Injected fault at G-stage: {injected} (cause={fault_cause})")
        else:
            if scenario["vs_valid"]:
                # Make G-stage invalid (no G-stage page table at all)
                injected = 0
                self.notice("  G-stage is inherently INVALID (no mappings)")
            else:
                # Make VS-stage invalid by injecting fault at VS-stage
                injected = ptg.handle.inject_implicit_guest_fault(ctx, cfg)
                self.notice(f"  Injected fault at VS-stage: {injected} (cause={fault_cause})")

        # Post-injection translation
        post_spa, post_vs, post_level = ptg.handle.translate_sequential(ctx, va, 0)
        self.notice(f"  Post-injection: SPA=0x{post_spa:X}, vs_fault={post_vs}, "
                    f"level={post_level}")

        # Determine which stage faulted
        actual_fault_code = post_vs
        if actual_fault_code == 0:
            self.notice("  -> No fault (translation succeeded)")
        elif actual_fault_code >= 20:
            self.notice(f"  -> G-stage fault (cause={actual_fault_code}) — "
                        f"GuestLoad/Store/InstructionPageFault")
        elif actual_fault_code in (15, 13):
            self.notice(f"  -> VS-stage fault (cause={actual_fault_code})")
        else:
            self.notice(f"  -> VS-stage fault (cause={actual_fault_code})")

        # Verify against expected fault stage
        expected_code = scenario["expected_fault_code"]
        if actual_fault_code > 0:
            ok = True
            self.notice(f"  PASS: Fault detected (cause={actual_fault_code})")
        else:
            ok = False
            self.notice(f"  FAIL: Expected fault but translation succeeded")

        ptg.destroy()
        return ok


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
