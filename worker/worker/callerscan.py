"""Finds callers of a given address by scanning the __text section's raw
bytes for ARM64 BL (branch-with-link) instructions whose target matches —
without running radare2's full-binary analysis (too slow for on-demand use,
see extract.py). ARM64 instructions are fixed 4 bytes wide, so this is a
simple, fast vectorized scan; encoding cross-checked against a real call
instruction's target as reported by radare2 itself before relying on it.

BL encoding: bits[31:26] == 0b100101, imm26 = bits[25:0] (signed, x4 for the
byte offset), target = address of the BL instruction + imm26 * 4.
"""

import numpy as np

from .machoimage import MachOImage

BL_TOP6 = 0b100101


def find_callers(data: bytes, slice_offset: int, target_vmaddr: int) -> list[int]:
    img = MachOImage(data, slice_offset)
    text_section = None
    for seg in img.segments:
        if seg.name == "__TEXT":
            for sec in seg.sections:
                if sec.sectname == "__text":
                    text_section = sec
    if text_section is None:
        return []

    size = text_section.size - (text_section.size % 4)
    raw = data[text_section.offset : text_section.offset + size]
    words = np.frombuffer(raw, dtype="<u4")

    is_bl = (words >> 26) == BL_TOP6
    imm26 = (words & 0x3FFFFFF).astype(np.int64)
    negative = imm26 >= (1 << 25)
    imm26 = np.where(negative, imm26 - (1 << 26), imm26)

    instr_vmaddr = text_section.addr + np.arange(len(words), dtype=np.int64) * 4
    targets = instr_vmaddr + imm26 * 4

    matches = is_bl & (targets == target_vmaddr)
    return [int(a) for a in instr_vmaddr[matches]]
