"""Read-only dependency probe: demonstrate legacy VS export fallback without FORCE APIs."""

import argparse
import ctypes as c
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ptg-lib", required=True, type=Path)
    args = parser.parse_args()
    path = args.ptg_lib.resolve(strict=True)
    lib = c.CDLL(str(path))
    write_type = c.CFUNCTYPE(None, c.c_uint64, c.POINTER(c.c_uint8), c.c_size_t, c.c_void_p)
    signatures = {
        "ptg_create": (c.c_void_p, []),
        "ptg_destroy": (None, [c.c_void_p]),
        "ptg_last_error": (c.c_int, [c.c_void_p]),
        "ptg_register_pa_region": (None, [c.c_void_p, c.c_uint64, c.c_uint64]),
        "ptg_register_gpa_region": (None, [c.c_void_p, c.c_uint16, c.c_uint64, c.c_uint64]),
        "ptg_context_create": (c.c_uint32, [c.c_void_p, c.c_uint16, c.c_uint16]),
        "ptg_context_vs_stage": (None, [c.c_void_p, c.c_uint32, c.c_int]),
        "ptg_context_gs_stage": (None, [c.c_void_p, c.c_uint32, c.c_int]),
        "ptg_context_vsatp": (c.c_uint64, [c.c_void_p, c.c_uint32]),
        "ptg_add_mapping": (None, [c.c_void_p, c.c_uint32, c.c_int, c.c_uint64,
                                   c.c_uint64, c.c_uint64, c.c_uint8, c.c_uint8]),
        "ptg_context_clear": (None, [c.c_void_p, c.c_uint32, c.c_int]),
        "ptg_dump_binary_write": (None, [c.c_void_p, c.c_uint32, c.c_int, write_type, c.c_void_p]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(lib, name)
        function.restype, function.argtypes = result, arguments
    handle = lib.ptg_create()
    if not handle:
        raise RuntimeError("ptg_create failed")

    def check():
        status = lib.ptg_last_error(handle)
        if status:
            raise RuntimeError("PTG setup failed: {}".format(status))

    def export():
        addresses = []

        @write_type
        def collect(pa, data, size, userdata):
            addresses.append({"address": hex(pa), "size": size})

        lib.ptg_dump_binary_write(handle, context, 1, collect, None)
        return {"last_error": lib.ptg_last_error(handle), "blocks": addresses}

    try:
        lib.ptg_register_pa_region(handle, 0xA0000000, 0xB0000000)
        lib.ptg_register_gpa_region(handle, 1, 0x80000000, 0x90000000)
        context = lib.ptg_context_create(handle, 1, 1)
        lib.ptg_context_vs_stage(handle, context, 8)
        lib.ptg_context_gs_stage(handle, context, 8)
        check()
        lib.ptg_add_mapping(handle, context, 1, 0x40000000, 0x82000000, 0x1000, 0, 0x67)
        check()
        root_gpa = (lib.ptg_context_vsatp(handle, context) & ((1 << 44) - 1)) << 12
        healthy = export()
        if healthy["last_error"] != 0 or not healthy["blocks"] or any(
            not 0xA0000000 <= int(block["address"], 16) < 0xB0000000
            for block in healthy["blocks"]
        ):
            raise RuntimeError("healthy VS export did not establish SPA-backed baseline")
        lib.ptg_context_clear(handle, context, 2)
        check()
        missing_gstage = export()
        fallback = missing_gstage["last_error"] == 0 and any(
            int(block["address"], 16) == root_gpa for block in missing_gstage["blocks"]
        )
        print(json.dumps({
            "library": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "vs_root_gpa": hex(root_gpa), "healthy_export": healthy,
            "after_clearing_g_stage": missing_gstage, "unsafe_fallback_observed": fallback,
            "note": "Probe only; no FORCE/ISS memory writes, no dependency files changed.",
        }, indent=2))
        return 1 if fallback else 0
    finally:
        lib.ptg_destroy(handle)


if __name__ == "__main__":
    raise SystemExit(main())
