"""Probe legacy PTG mapping-index semantics using only the public C ABI."""

import argparse
import ctypes as c
import hashlib
import json
from pathlib import Path


class Block(c.Structure):
    _fields_ = [("pa", c.c_uint64), ("size", c.c_size_t), ("data", c.POINTER(c.c_uint8))]


class Blocks(c.Structure):
    _fields_ = [("num_blocks", c.c_size_t), ("blocks", c.POINTER(Block))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ptg-lib", required=True, type=Path)
    args = parser.parse_args()
    path = args.ptg_lib.resolve(strict=True)
    lib = c.CDLL(str(path))
    signatures = {
        "ptg_create": (c.c_void_p, []),
        "ptg_destroy": (None, [c.c_void_p]),
        "ptg_last_error": (c.c_int, [c.c_void_p]),
        "ptg_register_pa_region": (None, [c.c_void_p, c.c_uint64, c.c_uint64]),
        "ptg_context_create": (c.c_uint32, [c.c_void_p, c.c_uint16, c.c_uint16]),
        "ptg_context_s_stage": (None, [c.c_void_p, c.c_uint32, c.c_int]),
        "ptg_context_satp": (c.c_uint64, [c.c_void_p, c.c_uint32]),
        "ptg_context_clear": (None, [c.c_void_p, c.c_uint32, c.c_int]),
        "ptg_dump_binary_blocks": (c.POINTER(Blocks), [c.c_void_p, c.c_uint32, c.c_int]),
        "ptg_free_blocks": (None, [c.POINTER(Blocks)]),
        "ptg_add_mapping": (
            None,
            [c.c_void_p, c.c_uint32, c.c_int, c.c_uint64, c.c_uint64,
             c.c_uint64, c.c_uint8, c.c_uint8],
        ),
        "ptg_mapping_find_pa": (c.c_uint64, [c.c_void_p, c.c_uint32, c.c_int, c.c_uint64]),
        "ptg_mapping_find_vas": (
            c.c_uint32,
            [c.c_void_p, c.c_uint32, c.c_int, c.c_uint64, c.POINTER(c.c_uint64), c.c_uint32],
        ),
        "ptg_translate": (
            c.c_uint64, [c.c_void_p, c.c_uint32, c.c_uint64, c.c_int, c.POINTER(c.c_uint8)],
        ),
        "ptg_remap_va": (None, [c.c_void_p, c.c_uint32, c.c_int, c.c_uint64, c.c_uint64]),
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
            raise RuntimeError("PTG setup/query failed: {}".format(status))

    def context():
        ctx = lib.ptg_context_create(handle, 1, 0)
        check()
        lib.ptg_context_s_stage(handle, ctx, 8)
        check()
        return ctx

    def mapping(ctx, va, pa):
        lib.ptg_add_mapping(handle, ctx, 0, va, pa, 0x1000, 0, 0x67)
        check()

    def forward(ctx, va):
        pa = lib.ptg_mapping_find_pa(handle, ctx, 0, va)
        return {"pa": hex(pa), "status": lib.ptg_last_error(handle)}

    def reverse(ctx, pa):
        count = lib.ptg_mapping_find_vas(handle, ctx, 0, pa, None, 0)
        check()
        values = (c.c_uint64 * count)()
        written = lib.ptg_mapping_find_vas(handle, ctx, 0, pa, values, count)
        check()
        if written != count:
            raise RuntimeError("mapping index changed during query")
        return [hex(va) for va in values]

    def translate(ctx, va):
        fault = c.c_uint8()
        pa = lib.ptg_translate(handle, ctx, va, 0, c.byref(fault))
        return {"pa": hex(pa), "fault": fault.value}

    def raw_leaf(ctx, va):
        layout = lib.ptg_dump_binary_blocks(handle, ctx, 0)
        check()
        if not layout:
            raise RuntimeError("missing raw page-table blocks")
        try:
            blocks = [
                (block.pa, c.string_at(block.data, block.size))
                for block in layout.contents.blocks[:layout.contents.num_blocks]
            ]
        finally:
            lib.ptg_free_blocks(layout)
        table = (lib.ptg_context_satp(handle, ctx) & ((1 << 44) - 1)) << 12
        check()
        for level in (2, 1, 0):
            slot = table + ((va >> (12 + 9 * level)) & 0x1FF) * 8
            data = next(
                (buf[slot - base:slot - base + 8] for base, buf in blocks
                 if base <= slot and slot + 8 <= base + len(buf)),
                None,
            )
            if data is None:
                raise RuntimeError("PTE slot missing from raw image")
            pte = int.from_bytes(data, "little")
            if not pte & 1 or pte & 0xE:
                return {
                    "slot": hex(slot), "pte": hex(pte), "level": level,
                    "valid": bool(pte & 1),
                    "page_base": hex(((pte >> 10) & ((1 << 44) - 1)) << 12),
                }
            table = ((pte >> 10) & ((1 << 44) - 1)) << 12
        raise RuntimeError("raw Sv39 walk has no leaf")

    try:
        lib.ptg_register_pa_region(handle, 0x80000000, 0x90000000)
        check()
        ctx = context()
        mapping(ctx, 0x4000, 0x84000000)
        mapping(ctx, 0x8000, 0x84000000)
        mapping(ctx, 0x10000, 0)
        healthy = {
            "base": forward(ctx, 0x4000),
            "interior": forward(ctx, 0x4008),
            "interior_translation": translate(ctx, 0x4008),
            "aliases": reverse(ctx, 0x84000000),
            "valid_pa_zero": forward(ctx, 0x10000),
            "zero_translation": translate(ctx, 0x10000),
            "missing": forward(ctx, 0x60000),
            "raw_leaf": raw_leaf(ctx, 0x4000),
        }
        if healthy["interior_translation"] != {"pa": "0x84000008", "fault": 0}:
            raise RuntimeError("healthy nonidentity mapping did not translate correctly")
        if healthy["zero_translation"] != {"pa": "0x0", "fault": 0}:
            raise RuntimeError("PA=0 mapping is not a valid baseline")
        lib.ptg_context_clear(handle, ctx, 0)
        check()
        cleared = {
            "base": forward(ctx, 0x4000),
            "aliases": reverse(ctx, 0x84000000),
            "translation": translate(ctx, 0x4000),
            "raw_leaf": raw_leaf(ctx, 0x4000),
        }
        remap_ctx = context()
        mapping(remap_ctx, 0x200000, 0x85000000)
        lib.ptg_remap_va(handle, remap_ctx, 0, 0x200008, 0x86000000)
        check()
        remapped = {
            "base": forward(remap_ctx, 0x200000),
            "interior": forward(remap_ctx, 0x200008),
            "old_aliases": reverse(remap_ctx, 0x85000000),
            "new_aliases": reverse(remap_ctx, 0x86000000),
            "base_translation": translate(remap_ctx, 0x200000),
            "raw_leaf": raw_leaf(remap_ctx, 0x200000),
        }
        hazards = {
            "zero_is_ambiguous": healthy["valid_pa_zero"] == healthy["missing"],
            "interior_lookup_is_exact_only": (
                healthy["interior"] == {"pa": "0x0", "status": 0}
                and healthy["interior_translation"] == {"pa": "0x84000008", "fault": 0}
            ),
            "clear_leaves_stale_index": (
                cleared["base"] == {"pa": "0x84000000", "status": 0}
                and cleared["raw_leaf"]["pte"] == "0x0"
            ),
            "interior_remap_leaves_stale_base": (
                remapped["base"] == {"pa": "0x85000000", "status": 0}
                and remapped["raw_leaf"]["valid"]
                and remapped["raw_leaf"]["page_base"] == "0x86000000"
            ),
        }
        print(json.dumps({
            "library": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "healthy": healthy, "after_clear": cleared, "after_interior_remap": remapped,
            "hazards": hazards,
        }, indent=2))
        return 1 if any(hazards.values()) else 0
    finally:
        lib.ptg_destroy(handle)


if __name__ == "__main__":
    raise SystemExit(main())
