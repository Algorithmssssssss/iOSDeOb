"""Minimal, dependency-free Mach-O parsing: just enough to locate the embedded
entitlements plist inside a binary's LC_CODE_SIGNATURE blob. Static-only,
never executes the binary. Format references: Apple's <mach-o/loader.h> and
<mach-o/fat.h>, and the well-documented codesign "SuperBlob" layout."""

import plistlib
import struct

FAT_MAGIC = 0xCAFEBABE
CPU_TYPE_ARM64 = 0x0100000C
CPU_SUBTYPE_ARM64E = 2

MH_MAGIC_64_BE_READ = 0xFEEDFACF  # big-endian file (rare)
MH_CIGAM_64_BE_READ = 0xCFFAEDFE  # little-endian file (normal case)
MH_MAGIC_BE_READ = 0xFEEDFACE
MH_CIGAM_BE_READ = 0xCEFAEDFE

LC_CODE_SIGNATURE = 0x1D
CSMAGIC_EMBEDDED_SIGNATURE = 0xFADE0CC0
CSSLOT_ENTITLEMENTS = 5
CSMAGIC_EMBEDDED_ENTITLEMENTS = 0xFADE7171


def find_preferred_slice(data: bytes) -> tuple[int, int]:
    """Returns (offset, size) of the best arm64 slice, or the whole file if it's
    thin. Prefers plain arm64 over arm64e: arm64e pointers are authenticated
    (ptrauth-signed), which our chained-fixups resolver doesn't decode, so
    picking a plain arm64 slice when one exists avoids silently-wrong metadata."""
    magic_be = struct.unpack_from(">I", data, 0)[0]
    if magic_be != FAT_MAGIC:
        return (0, len(data))

    nfat_arch = struct.unpack_from(">I", data, 4)[0]
    offset = 8
    fallback = None
    arm64e_slice = None
    for _ in range(nfat_arch):
        cputype, cpusubtype, slice_offset, slice_size, _align = struct.unpack_from(">5I", data, offset)
        offset += 20
        if fallback is None:
            fallback = (slice_offset, slice_size)
        if cputype == CPU_TYPE_ARM64:
            if (cpusubtype & 0xFF) == CPU_SUBTYPE_ARM64E:
                arm64e_slice = (slice_offset, slice_size)
            else:
                return (slice_offset, slice_size)
    return arm64e_slice or fallback or (0, len(data))


def _find_code_signature(data: bytes, base: int) -> tuple[int, int] | None:
    magic_be = struct.unpack_from(">I", data, base)[0]
    if magic_be == MH_CIGAM_64_BE_READ:
        endian, is64 = "<", True
    elif magic_be == MH_MAGIC_64_BE_READ:
        endian, is64 = ">", True
    elif magic_be == MH_CIGAM_BE_READ:
        endian, is64 = "<", False
    elif magic_be == MH_MAGIC_BE_READ:
        endian, is64 = ">", False
    else:
        return None

    header_size = 32 if is64 else 28
    ncmds = struct.unpack_from(endian + "I", data, base + 16)[0]
    offset = base + header_size
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from(endian + "2I", data, offset)
        if cmd == LC_CODE_SIGNATURE:
            dataoff, datasize = struct.unpack_from(endian + "2I", data, offset + 8)
            return (base + dataoff, datasize)
        offset += cmdsize
    return None


def _extract_entitlements_blob(data: bytes, superblob_offset: int) -> bytes | None:
    magic, _length, count = struct.unpack_from(">3I", data, superblob_offset)
    if magic != CSMAGIC_EMBEDDED_SIGNATURE:
        return None
    index_offset = superblob_offset + 12
    for i in range(count):
        blob_type, blob_offset = struct.unpack_from(">2I", data, index_offset + i * 8)
        if blob_type == CSSLOT_ENTITLEMENTS:
            abs_offset = superblob_offset + blob_offset
            blob_magic, blob_len = struct.unpack_from(">2I", data, abs_offset)
            if blob_magic != CSMAGIC_EMBEDDED_ENTITLEMENTS:
                return None
            return data[abs_offset + 8 : abs_offset + blob_len]
    return None


def extract_entitlements(data: bytes, slice_offset: int) -> dict | None:
    cs_location = _find_code_signature(data, slice_offset)
    if not cs_location:
        return None

    cs_offset, _cs_size = cs_location
    plist_bytes = _extract_entitlements_blob(data, cs_offset)
    if not plist_bytes:
        return None

    try:
        return plistlib.loads(plist_bytes)
    except Exception:
        return None
