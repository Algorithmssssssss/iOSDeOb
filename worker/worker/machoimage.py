"""Generic Mach-O load-command/segment parsing plus a chained-fixups
("LC_DYLD_CHAINED_FIXUPS") pointer resolver, shared by the Objective-C
metadata extractor. Struct layouts verified against Apple's open-source
headers (apple-oss-distributions/dyld, include/mach-o/fixup-chains.h) rather
than from memory, since a wrong bit offset here would silently corrupt
every pointer we resolve.

Static-only: this module never executes the binary, it only parses bytes.
"""

import struct
import zlib
from dataclasses import dataclass, field

LC_SEGMENT_64 = 0x19
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_DYLD_CHAINED_FIXUPS = 0x34
LC_SYMTAB = 0x2

BIND_OPCODE_MASK = 0xF0
BIND_IMMEDIATE_MASK = 0x0F
BIND_OPCODE_DONE = 0x00
BIND_OPCODE_SET_DYLIB_ORDINAL_IMM = 0x10
BIND_OPCODE_SET_DYLIB_ORDINAL_ULEB = 0x20
BIND_OPCODE_SET_DYLIB_SPECIAL_IMM = 0x30
BIND_OPCODE_SET_SYMBOL_TRAILING_FLAGS_IMM = 0x40
BIND_OPCODE_SET_TYPE_IMM = 0x50
BIND_OPCODE_SET_ADDEND_SLEB = 0x60
BIND_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB = 0x70
BIND_OPCODE_ADD_ADDR_ULEB = 0x80
BIND_OPCODE_DO_BIND = 0x90
BIND_OPCODE_DO_BIND_ADD_ADDR_ULEB = 0xA0
BIND_OPCODE_DO_BIND_ADD_ADDR_IMM_SCALED = 0xB0
BIND_OPCODE_DO_BIND_ULEB_TIMES_SKIPPING_ULEB = 0xC0
BIND_OPCODE_THREADED = 0xD0

DYLD_CHAINED_PTR_ARM64E = 1
DYLD_CHAINED_PTR_64 = 2
DYLD_CHAINED_PTR_64_OFFSET = 6
SUPPORTED_PTR_FORMATS = {DYLD_CHAINED_PTR_64, DYLD_CHAINED_PTR_64_OFFSET}

DYLD_CHAINED_PTR_START_NONE = 0xFFFF
DYLD_CHAINED_PTR_START_MULTI = 0x8000

DYLD_CHAINED_IMPORT = 1
DYLD_CHAINED_IMPORT_ADDEND = 2
DYLD_CHAINED_IMPORT_ADDEND64 = 3


@dataclass
class Section:
    segname: str
    sectname: str
    addr: int
    size: int
    offset: int


@dataclass
class Segment:
    name: str
    vmaddr: int
    vmsize: int
    fileoff: int
    filesize: int
    sections: list = field(default_factory=list)


class UnresolvedPointer(Exception):
    pass


class MachOImage:
    """Wraps one thin (single-arch) Mach-O slice's bytes for metadata reading."""

    def __init__(self, data: bytes, slice_offset: int = 0):
        self.data = data
        self.base = slice_offset
        self.segments: list[Segment] = []
        self.image_base_vmaddr = None
        self._fixups: dict[int, tuple] = {}  # file_offset -> ("rebase", vmaddr) | ("bind", name)
        self.has_chained_fixups = False
        self.unsupported_ptr_formats: set[int] = set()
        self._parse_load_commands()
        if self.has_chained_fixups:
            self._parse_chained_fixups()
        elif self._classic_bind_loc:
            self._parse_classic_binds()

    # ---- load commands / segments -----------------------------------

    def _parse_load_commands(self):
        magic_be = struct.unpack_from(">I", self.data, self.base)[0]
        if magic_be == 0xCFFAEDFE:
            endian, is64 = "<", True
        elif magic_be == 0xFEEDFACF:
            endian, is64 = ">", True
        else:
            raise ValueError("Not a 64-bit Mach-O slice")

        ncmds = struct.unpack_from(endian + "I", self.data, self.base + 16)[0]
        offset = self.base + 32
        chained_fixups_loc = None
        classic_bind_loc = None

        for _ in range(ncmds):
            cmd, cmdsize = struct.unpack_from(endian + "2I", self.data, offset)
            if cmd == LC_SEGMENT_64:
                self._parse_segment(endian, offset)
            elif cmd == LC_DYLD_CHAINED_FIXUPS:
                dataoff, datasize = struct.unpack_from(endian + "2I", self.data, offset + 8)
                chained_fixups_loc = (self.base + dataoff, datasize)
                self.has_chained_fixups = True
            elif cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
                _rebase_off, _rebase_size, bind_off, bind_size = struct.unpack_from(
                    endian + "4I", self.data, offset + 8
                )
                if bind_size:
                    classic_bind_loc = (self.base + bind_off, bind_size)
            offset += cmdsize

        self._classic_bind_loc = classic_bind_loc

        for seg in self.segments:
            if seg.name == "__TEXT":
                self.image_base_vmaddr = seg.vmaddr
                break
        if self.image_base_vmaddr is None and self.segments:
            self.image_base_vmaddr = self.segments[0].vmaddr

        self._chained_fixups_loc = chained_fixups_loc

    def _parse_segment(self, endian, cmd_offset):
        name = self.data[cmd_offset + 8 : cmd_offset + 24].rstrip(b"\x00").decode("ascii", "replace")
        vmaddr, vmsize, fileoff, filesize = struct.unpack_from(endian + "4Q", self.data, cmd_offset + 24)
        _maxprot, _initprot, nsects, _flags = struct.unpack_from(endian + "4I", self.data, cmd_offset + 56)
        seg = Segment(name=name, vmaddr=vmaddr, vmsize=vmsize, fileoff=fileoff, filesize=filesize)
        sect_off = cmd_offset + 72
        for _ in range(nsects):
            sectname = self.data[sect_off : sect_off + 16].rstrip(b"\x00").decode("ascii", "replace")
            segname = self.data[sect_off + 16 : sect_off + 32].rstrip(b"\x00").decode("ascii", "replace")
            addr, size = struct.unpack_from(endian + "2Q", self.data, sect_off + 32)
            offset = struct.unpack_from(endian + "I", self.data, sect_off + 48)[0]
            seg.sections.append(Section(segname=segname, sectname=sectname, addr=addr, size=size, offset=self.base + offset))
            sect_off += 80
        self.segments.append(seg)

    def find_section(self, sectname: str) -> Section | None:
        for seg in self.segments:
            for sec in seg.sections:
                if sec.sectname == sectname:
                    return sec
        return None

    # ---- classic bind opcodes (pre-chained-fixups binaries) -----------

    def _read_uleb128(self, pos: int) -> tuple[int, int]:
        result, shift = 0, 0
        while True:
            byte = self.data[pos]
            pos += 1
            result |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                break
            shift += 7
        return result, pos

    def _read_sleb128(self, pos: int) -> tuple[int, int]:
        result, shift = 0, 0
        while True:
            byte = self.data[pos]
            pos += 1
            result |= (byte & 0x7F) << shift
            shift += 7
            if (byte & 0x80) == 0:
                if shift < 64 and (byte & 0x40):
                    result |= -(1 << shift)
                break
        return result, pos

    def _parse_classic_binds(self):
        """Classic (pre-chained-fixups) LC_DYLD_INFO[_ONLY] bind-opcode stream.
        Algorithm verified against apple-oss-distributions/dyld's
        mach_o/BindOpcodes.cpp forEachBind. We only need symbol *names* for
        external references (e.g. an ObjC superclass imported from UIKit) —
        library ordinal/type/addend are parsed (to stay in sync with the
        opcode stream) but not used."""
        loc, size = self._classic_bind_loc
        pos = loc
        end = loc + size

        seg_index = 0
        seg_offset = 0
        symbol_name = None
        pointer_size = 8

        while pos < end:
            byte = self.data[pos]
            opcode = byte & BIND_OPCODE_MASK
            immediate = byte & BIND_IMMEDIATE_MASK
            pos += 1

            if opcode == BIND_OPCODE_DONE:
                break
            elif opcode == BIND_OPCODE_SET_DYLIB_ORDINAL_IMM:
                pass
            elif opcode == BIND_OPCODE_SET_DYLIB_ORDINAL_ULEB:
                _ordinal, pos = self._read_uleb128(pos)
            elif opcode == BIND_OPCODE_SET_DYLIB_SPECIAL_IMM:
                pass
            elif opcode == BIND_OPCODE_SET_SYMBOL_TRAILING_FLAGS_IMM:
                str_end = self.data.index(b"\x00", pos)
                symbol_name = self.data[pos:str_end].decode("utf-8", "replace")
                pos = str_end + 1
            elif opcode == BIND_OPCODE_SET_TYPE_IMM:
                pass
            elif opcode == BIND_OPCODE_SET_ADDEND_SLEB:
                _addend, pos = self._read_sleb128(pos)
            elif opcode == BIND_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB:
                seg_index = immediate
                seg_offset, pos = self._read_uleb128(pos)
            elif opcode == BIND_OPCODE_ADD_ADDR_ULEB:
                # ULEB values here can encode "negative" deltas via uint64 wraparound
                # (e.g. a 10-byte ULEB like d0 fa fe ff ff ff ff ff ff 01) — must mask
                # to 64 bits like C's uint64_t would, or the offset blows up.
                delta, pos = self._read_uleb128(pos)
                seg_offset = (seg_offset + delta) & 0xFFFFFFFFFFFFFFFF
            elif opcode == BIND_OPCODE_DO_BIND:
                self._record_classic_bind(seg_index, seg_offset, symbol_name)
                seg_offset = (seg_offset + pointer_size) & 0xFFFFFFFFFFFFFFFF
            elif opcode == BIND_OPCODE_DO_BIND_ADD_ADDR_ULEB:
                self._record_classic_bind(seg_index, seg_offset, symbol_name)
                delta, pos = self._read_uleb128(pos)
                seg_offset = (seg_offset + delta + pointer_size) & 0xFFFFFFFFFFFFFFFF
            elif opcode == BIND_OPCODE_DO_BIND_ADD_ADDR_IMM_SCALED:
                self._record_classic_bind(seg_index, seg_offset, symbol_name)
                seg_offset = (seg_offset + immediate * pointer_size + pointer_size) & 0xFFFFFFFFFFFFFFFF
            elif opcode == BIND_OPCODE_DO_BIND_ULEB_TIMES_SKIPPING_ULEB:
                count, pos = self._read_uleb128(pos)
                skip, pos = self._read_uleb128(pos)
                for _ in range(count):
                    self._record_classic_bind(seg_index, seg_offset, symbol_name)
                    seg_offset = (seg_offset + skip + pointer_size) & 0xFFFFFFFFFFFFFFFF
            elif opcode == BIND_OPCODE_THREADED:
                break  # rare transitional arm64e format, not handled
            else:
                break  # unknown opcode; stop rather than misparse the rest

    def _record_classic_bind(self, seg_index: int, seg_offset: int, symbol_name: str | None):
        if symbol_name is None or not (0 <= seg_index < len(self.segments)):
            return
        file_off = self.base + self.segments[seg_index].fileoff + seg_offset
        self._fixups[file_off] = ("bind", symbol_name)

    def vmaddr_to_fileoff(self, vmaddr: int) -> int | None:
        if vmaddr == 0:
            return None  # null pointer, never a legitimate target
        for seg in self.segments:
            if seg.filesize == 0:
                continue  # zero-fill / no-file-backing segment (e.g. __PAGEZERO), not a real target
            if seg.vmaddr <= vmaddr < seg.vmaddr + seg.vmsize:
                return self.base + seg.fileoff + (vmaddr - seg.vmaddr)
        return None

    def fileoff_to_vmaddr(self, file_offset: int) -> int | None:
        rel = file_offset - self.base
        for seg in self.segments:
            if seg.fileoff <= rel < seg.fileoff + seg.filesize:
                return seg.vmaddr + (rel - seg.fileoff)
        return None

    def segment_index_containing_vmaddr_offset(self, seg_index: int):
        if 0 <= seg_index < len(self.segments):
            return self.segments[seg_index]
        return None

    # ---- chained fixups ------------------------------------------------

    def _parse_chained_fixups(self):
        loc, _size = self._chained_fixups_loc
        fixups_version, starts_offset, imports_offset, symbols_offset, imports_count, imports_format, symbols_format = (
            struct.unpack_from("<7I", self.data, loc)
        )

        # Imports table: ordinal -> imported symbol name (e.g. "_OBJC_CLASS_$_NSObject")
        imports: list[str] = []
        if symbols_format == 1:
            # zlib-compressed symbol strings pool; size unknown ahead of time so
            # decompress greedily from the offset to end of chain_data (bounded by datasize).
            _fixups_loc_off, fixups_size = self._chained_fixups_loc
            compressed = self.data[loc + symbols_offset : loc + fixups_size]
            try:
                symbol_pool = zlib.decompress(compressed)
            except zlib.error:
                symbol_pool = b""
        else:
            symbol_pool = self.data[loc + symbols_offset :]

        import_entry_size = {DYLD_CHAINED_IMPORT: 4, DYLD_CHAINED_IMPORT_ADDEND: 8, DYLD_CHAINED_IMPORT_ADDEND64: 16}.get(
            imports_format, 4
        )
        for i in range(imports_count):
            entry_off = loc + imports_offset + i * import_entry_size
            if imports_format == DYLD_CHAINED_IMPORT_ADDEND64:
                # uint64_t lib_ordinal:16, weak_import:1, reserved:15, name_offset:32 (bitfields are low-bit-first)
                raw64 = struct.unpack_from("<Q", self.data, entry_off)[0]
                name_offset = (raw64 >> 32) & 0xFFFFFFFF
            else:
                # uint32_t lib_ordinal:8, weak_import:1, name_offset:23
                raw = struct.unpack_from("<I", self.data, entry_off)[0]
                name_offset = (raw >> 9) & 0x7FFFFF
            end = symbol_pool.find(b"\x00", name_offset)
            name = symbol_pool[name_offset:end].decode("utf-8", "replace") if end != -1 else ""
            imports.append(name)

        # Segment fixup starts
        seg_count = struct.unpack_from("<I", self.data, loc + starts_offset)[0]
        seg_info_offsets = struct.unpack_from(f"<{seg_count}I", self.data, loc + starts_offset + 4)

        for seg_index, info_off in enumerate(seg_info_offsets):
            if info_off == 0:
                continue
            seg_struct_off = loc + starts_offset + info_off
            _size, page_size, pointer_format, segment_offset, _max_valid_ptr, page_count = struct.unpack_from(
                "<IHHQIH", self.data, seg_struct_off
            )
            page_starts = struct.unpack_from(f"<{page_count}H", self.data, seg_struct_off + 22)

            segment = self.segment_index_containing_vmaddr_offset(seg_index)
            if segment is None:
                continue
            if pointer_format not in SUPPORTED_PTR_FORMATS:
                self.unsupported_ptr_formats.add(pointer_format)
                continue

            for page_index, start in enumerate(page_starts):
                if start == DYLD_CHAINED_PTR_START_NONE:
                    continue
                if start & DYLD_CHAINED_PTR_START_MULTI:
                    continue  # rare multi-chain-per-page case, not handled
                offset_in_seg = page_index * page_size + start
                self._walk_chain(segment, offset_in_seg, pointer_format, imports)

    def _walk_chain(self, segment: Segment, offset_in_seg: int, pointer_format: int, imports: list[str]):
        while True:
            file_off = self.base + segment.fileoff + offset_in_seg
            if file_off + 8 > len(self.data):
                break
            raw = struct.unpack_from("<Q", self.data, file_off)[0]
            bind = (raw >> 63) & 1

            if bind:
                ordinal = raw & 0xFFFFFF  # 24 bits
                next_stride = (raw >> 51) & 0xFFF  # 12 bits
                name = imports[ordinal] if ordinal < len(imports) else None
                self._fixups[file_off] = ("bind", name)
            else:
                target = raw & 0xFFFFFFFFF  # 36 bits
                next_stride = (raw >> 51) & 0xFFF  # 12 bits
                if pointer_format == DYLD_CHAINED_PTR_64_OFFSET:
                    vmaddr = (self.image_base_vmaddr or 0) + target
                else:
                    vmaddr = target
                self._fixups[file_off] = ("rebase", vmaddr)

            if next_stride == 0:
                break
            offset_in_seg += next_stride * 4

    # ---- pointer field reads -------------------------------------------

    def read_ptr_field(self, file_offset: int) -> int | None:
        """Resolve an 8-byte pointer-sized field at file_offset to a vmaddr.
        Returns None if it's an unresolvable external bind or points into an
        unsupported (e.g. arm64e/ptrauth) fixup region."""
        fixup = self._fixups.get(file_offset)
        if fixup is not None:
            kind, value = fixup
            return value if kind == "rebase" else None
        if self.has_chained_fixups:
            # No fixup recorded for this slot: either it's in an unsupported
            # pointer-format segment, or genuinely zero/absent. Don't guess.
            return None
        # Classic (pre-chained-fixups) binary: the raw bytes are already the vmaddr.
        return struct.unpack_from("<Q", self.data, file_offset)[0]

    def read_bind_symbol(self, file_offset: int) -> str | None:
        fixup = self._fixups.get(file_offset)
        if fixup and fixup[0] == "bind":
            return fixup[1]
        return None

    def read_cstring(self, vmaddr: int, max_len: int = 4096) -> str | None:
        off = self.vmaddr_to_fileoff(vmaddr)
        if off is None:
            return None
        end = self.data.find(b"\x00", off, off + max_len)
        if end == -1:
            end = off + max_len
        return self.data[off:end].decode("utf-8", "replace")
