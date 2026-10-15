from enum import Enum


class ExceptionClassRISCV(Enum):
    """RISC-V exception class codes.
    Values MUST match C++ EExceptionClassType in EnumsRISCV.h exactly.
    Note: C++ inserts EnvCallFromVU(10) and EnvCallFromHS(11) at 0xA-0xB,
    shifting all subsequent values by +2 vs RISC-V spec mcause layout.
    """
    INSTRUCTION_ADDRESS_MISALIGNED = 0x0
    INSTRUCTION_ACCESS_FAULT = 0x1
    ILLEGAL_INSTRUCTION = 0x2
    BREAKPOINT = 0x3
    LOAD_ADDRESS_MISALIGNED = 0x4
    LOAD_ACCESS_FAULT = 0x5
    STORE_AMO_ADDRESS_MISALIGNED = 0x6
    STORE_AMO_ACCESS_FAULT = 0x7
    ENV_CALL_FROM_U_MODE = 0x8
    ENV_CALL_FROM_S_MODE = 0x9
    ENV_CALL_FROM_VU = 0xA          # H-extension: env call from VU-mode
    ENV_CALL_FROM_HS = 0xB           # H-extension: env call from HS-mode
    ENV_CALL_FROM_M_MODE = 0xC
    INSTRUCTION_PAGE_FAULT = 0xD
    LOAD_PAGE_FAULT = 0xE
    STORE_AMO_PAGE_FAULT = 0xF

    # Hypervisor extension exceptions (values match C++ EExceptionClassType)
    INSTRUCTION_GUEST_PAGE_FAULT = 0x10
    LOAD_GUEST_PAGE_FAULT = 0x11
    STORE_AMO_GUEST_PAGE_FAULT = 0x12
    VIRTUAL_INSTRUCTION = 0x13

    TRAP_REDIRECTION = 0x99

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.value < other.value

        return NotImplemented
