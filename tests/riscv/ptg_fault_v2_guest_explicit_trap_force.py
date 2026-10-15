"""Validate V2 guest-explicit faults through real Handcar execution."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from ptg_fault_v2_guest_scope_common import (  # noqa: E402
    EXPLICIT_SCOPE_SPEC,
    GuestScopeSequence,
)
from riscv.EnvRISCV import EnvRISCV  # noqa: E402
from riscv.GenThreadRISCV import GenThreadRISCV  # noqa: E402


class MainSequence(GuestScopeSequence):
    scope_spec = EXPLICIT_SCOPE_SPEC

    def generate(self, **kargs):
        option_names = ("GuestExplicitAddressKind", "GuestGTargetLevel")
        option_values = [self.getOption(name) for name in option_names]
        if any(valid for _, valid in option_values):
            if not all(valid for _, valid in option_values):
                self.error("Guest-explicit matrix options must be specified together")
            self.explicit_address_kind, self.explicit_g_target_level = (
                int(value) for value, _ in option_values
            )
        super().generate(**kargs)


MainSequenceClass = MainSequence
GenThreadClass = GenThreadRISCV
EnvClass = EnvRISCV
