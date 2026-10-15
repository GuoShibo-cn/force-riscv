"""Validate V2 guest-implicit faults through real Handcar execution."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from ptg_fault_v2_guest_scope_common import (  # noqa: E402
    IMPLICIT_SCOPE_SPEC,
    GuestScopeSequence,
)
from riscv.EnvRISCV import EnvRISCV  # noqa: E402
from riscv.GenThreadRISCV import GenThreadRISCV  # noqa: E402


class MainSequence(GuestScopeSequence):
    scope_spec = IMPLICIT_SCOPE_SPEC

    def generate(self, **kargs):
        option_names = (
            "GuestVsWalkLevel",
            "GuestGTargetLevel",
            "GuestFaultAccess",
        )
        option_values = [self.getOption(name) for name in option_names]
        if any(valid for _, valid in option_values):
            if not all(valid for _, valid in option_values):
                self.error("Guest-implicit matrix options must be specified together")
            self.implicit_matrix_case = tuple(int(value) for value, _ in option_values)
        super().generate(**kargs)


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
