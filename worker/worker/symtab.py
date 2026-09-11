"""Parses LC_SYMTAB to recover named code symbols (functions) that survived
stripping — a cheap complement to the ObjC method addresses we already have
from objc_metadata.py, giving us a fuller "jump to a named function" index
without ever running radare2's (slow) whole-binary analysis. Layout verified
against Apple's cctools <mach-o/loader.h> and <mach-o/nlist.h>."""

import struct

from .machoimage import MachOImage

LC_SYMTAB = 0x2
N_STAB = 0xE0
N_TYPE = 0x0E
N_SECT = 0xE

NLIST_64_SIZE = 16


def _find_symtab_command(data: bytes, base: int) -> tuple[int, int, int, int] | None:
    magic_be = struct.unpack_from(">I", data, base)[0]
    if magic_be not in (0xCFFAEDFE, 0xFEEDFACF):
        return None
    endian = "<" if magic_be == 0xCFFAEDFE else ">"

    ncmds = struct.unpack_from(endian + "I", data, base + 16)[0]
    offset = base + 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from(endian + "2I", data, offset)
        if cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from(endian + "4I", data, offset + 8)
            return (base + symoff, nsyms, base + stroff, strsize)
        offset += cmdsize
    return None


def extract_code_symbols(data: bytes, slice_offset: int = 0) -> list[dict]:
    """Returns [{name, address}], limited to symbols that fall inside a
    __TEXT,__text section (i.e. actual code, not data/globals)."""
    img = MachOImage(data, slice_offset)
    text_section = None
    for seg in img.segments:
        if seg.name == "__TEXT":
            for sec in seg.sections:
                if sec.sectname == "__text":
                    text_section = sec
                    break
    if text_section is None:
        return []

    symtab_loc = _find_symtab_command(data, slice_offset)
    if symtab_loc is None:
        return []
    symoff, nsyms, stroff, _strsize = symtab_loc

    symbols = []
    for i in range(nsyms):
        entry_off = symoff + i * NLIST_64_SIZE
        if entry_off + NLIST_64_SIZE > len(data):
            break
        n_strx, n_type, _n_sect, _n_desc, n_value = struct.unpack_from("<IBBHQ", data, entry_off)

        if n_type & N_STAB:
            continue  # debugging symbol
        if (n_type & N_TYPE) != N_SECT:
            continue  # not defined in a section (undefined/common/etc.)
        if not (text_section.addr <= n_value < text_section.addr + text_section.size):
            continue  # not code

        name_off = stroff + n_strx
        end = data.find(b"\x00", name_off)
        if end == -1:
            continue
        name = data[name_off:end].decode("utf-8", "replace")
        if not name:
            continue
        symbols.append({"name": name, "address": n_value})

    return symbols
