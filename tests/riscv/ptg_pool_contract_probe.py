"""Isolated public-C-ABI probes for PTG root alignment and pool exhaustion."""

import argparse
import ctypes as c
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys


def child(path, scenario):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    lib = c.CDLL(str(path))
    signatures = {
        "ptg_create": (c.c_void_p, []),
        "ptg_destroy": (None, [c.c_void_p]),
        "ptg_last_error": (c.c_int, [c.c_void_p]),
        "ptg_register_pa_region": (None, [c.c_void_p, c.c_uint64, c.c_uint64]),
        "ptg_context_create": (c.c_uint32, [c.c_void_p, c.c_uint16, c.c_uint16]),
        "ptg_context_s_stage": (None, [c.c_void_p, c.c_uint32, c.c_int]),
        "ptg_context_gs_stage": (None, [c.c_void_p, c.c_uint32, c.c_int]),
        "ptg_context_satp": (c.c_uint64, [c.c_void_p, c.c_uint32]),
        "ptg_context_hgatp": (c.c_uint64, [c.c_void_p, c.c_uint32]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(lib, name)
        function.restype, function.argtypes = result, arguments
    h = lib.ptg_create()
    if not h:
        raise RuntimeError("no handle")
    try:
        base = 0xA0000000
        pool_size = {"alignment": 0x100000, "exhaustion": 0x1000, "exact-fit": 0x4000}[scenario]
        limit = base + pool_size
        lib.ptg_register_pa_region(h, base, limit)
        if lib.ptg_last_error(h):
            raise RuntimeError("PA registration failed")
        ctx = lib.ptg_context_create(h, 1, 1)
        if scenario == "alignment":
            lib.ptg_context_s_stage(h, ctx, 8)
            if lib.ptg_last_error(h):
                raise RuntimeError("S-stage setup failed")
        print("about to configure G-stage", flush=True)
        lib.ptg_context_gs_stage(h, ctx, 8)
        status = lib.ptg_last_error(h)
        if status:
            print(json.dumps({"scenario": scenario, "stage_status": status}), flush=True)
            return 0
        hgatp = lib.ptg_context_hgatp(h, ctx)
        root = (hgatp & ((1 << 44) - 1)) << 12
        print(json.dumps({
            "scenario": scenario, "stage_status": status,
            "pa_base": hex(base), "pa_limit_exclusive": hex(limit),
            "s_root": (hex((lib.ptg_context_satp(h, ctx) & ((1 << 44) - 1)) << 12)
                       if scenario == "alignment" else None),
            "hgatp": hex(hgatp), "g_root": hex(root),
            "g_root_aligned_16k": root % 0x4000 == 0,
            "g_root_fits_pool": base <= root and root + 0x4000 <= limit,
        }), flush=True)
        return 0
    finally:
        lib.ptg_destroy(h)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ptg-lib", type=Path, required=True)
    parser.add_argument("--child", choices=("alignment", "exhaustion", "exact-fit"))
    args = parser.parse_args()
    path = args.ptg_lib.resolve(strict=True)
    if args.child:
        return child(path, args.child)
    reports = []
    for scenario in ("exact-fit", "alignment", "exhaustion"):
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--ptg-lib", str(path),
             "--child", scenario],
            capture_output=True, text=True, timeout=20,
        )
        reports.append({
            "scenario": scenario, "return_code": process.returncode,
            "stdout": process.stdout, "stderr": process.stderr,
        })
    print(json.dumps({
        "library": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "probes": reports,
        "note": "Diagnostic results, not an acceptance PASS. No dependency files changed.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
