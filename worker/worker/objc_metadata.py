"""Static extraction of Objective-C class/method/property/protocol metadata
directly from a Mach-O binary's __objc_* runtime sections + chained fixups —
our own, from-scratch equivalent of class-dump (which is unreliable to build
for Linux). Struct layouts verified against Apple's open-source objc4 runtime
header (apple-oss-distributions/objc4, runtime/objc-runtime-new.h).

Superclass/protocol references that point outside this binary (imported from
another dylib, e.g. NSObject) are resolved by name via the chained-fixups
bind-symbol table when possible; anything we can't resolve is reported as
such rather than guessed. Categories and Swift metadata are out of scope here
(see worker/worker/extract.py's caller for how this is surfaced).
"""

import struct

from .machoimage import MachOImage

CLASS_RO_T_SIZE = 0x48
METHOD_LIST_FLAG_MASK = 0xFFFF0003
SMALL_METHOD_LIST_FLAG = 0x80000000


def _strip_objc_symbol_prefix(name: str | None) -> str | None:
    if not name:
        return name
    for prefix in ("_OBJC_CLASS_$_", "_OBJC_METACLASS_$_", "_OBJC_PROTOCOL_$_"):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def _parse_method_list(img: MachOImage, list_ptr: int | None) -> list[dict]:
    if list_ptr is None:
        return []
    if list_ptr & 1:
        return []  # relative_list_list_t ("list of lists") — not supported yet
    fileoff = img.vmaddr_to_fileoff(list_ptr)
    if fileoff is None:
        return []

    entsize_and_flags, count = struct.unpack_from("<II", img.data, fileoff)
    entsize = entsize_and_flags & ~METHOD_LIST_FLAG_MASK
    is_small = bool(entsize_and_flags & SMALL_METHOD_LIST_FLAG)
    if entsize == 0 or count > 20000:
        return []

    entries_off = fileoff + 8
    methods = []
    for i in range(count):
        entry_off = entries_off + i * entsize
        if entry_off + entsize > len(img.data):
            break

        if is_small:
            name_rel, types_rel, imp_rel = struct.unpack_from("<3i", img.data, entry_off)
            name_field_vmaddr = img.fileoff_to_vmaddr(entry_off)
            types_field_vmaddr = img.fileoff_to_vmaddr(entry_off + 4)
            imp_field_vmaddr = img.fileoff_to_vmaddr(entry_off + 8)

            selector = None
            if name_field_vmaddr is not None:
                selref_vmaddr = name_field_vmaddr + name_rel
                selref_fileoff = img.vmaddr_to_fileoff(selref_vmaddr)
                sel_str_vmaddr = img.read_ptr_field(selref_fileoff) if selref_fileoff is not None else None
                selector = img.read_cstring(sel_str_vmaddr) if sel_str_vmaddr else None

            type_encoding = None
            if types_field_vmaddr is not None:
                type_encoding = img.read_cstring(types_field_vmaddr + types_rel)

            address = (imp_field_vmaddr + imp_rel) if imp_field_vmaddr is not None else None
        else:
            name_vmaddr = img.read_ptr_field(entry_off)
            selector = img.read_cstring(name_vmaddr) if name_vmaddr else None
            types_vmaddr = img.read_ptr_field(entry_off + 8)
            type_encoding = img.read_cstring(types_vmaddr) if types_vmaddr else None
            address = img.read_ptr_field(entry_off + 16)

        if selector:
            methods.append({"selector": selector, "type_encoding": type_encoding, "address": address})
    return methods


def _parse_property_list(img: MachOImage, list_ptr: int | None) -> list[dict]:
    if list_ptr is None or list_ptr & 1:
        return []
    fileoff = img.vmaddr_to_fileoff(list_ptr)
    if fileoff is None:
        return []
    entsize, count = struct.unpack_from("<II", img.data, fileoff)  # no flag bits for property_list_t
    if entsize == 0 or count > 20000:
        return []
    entries_off = fileoff + 8
    properties = []
    for i in range(count):
        entry_off = entries_off + i * entsize
        name_vmaddr = img.read_ptr_field(entry_off)
        attrs_vmaddr = img.read_ptr_field(entry_off + 8)
        name = img.read_cstring(name_vmaddr) if name_vmaddr else None
        attributes = img.read_cstring(attrs_vmaddr) if attrs_vmaddr else None
        if name:
            properties.append({"name": name, "attributes": attributes})
    return properties


def _parse_ivar_list(img: MachOImage, list_ptr: int | None) -> list[dict]:
    if list_ptr is None:
        return []
    fileoff = img.vmaddr_to_fileoff(list_ptr)
    if fileoff is None:
        return []
    entsize, count = struct.unpack_from("<II", img.data, fileoff)  # no flag bits for ivar_list_t
    if entsize == 0 or count > 20000:
        return []
    entries_off = fileoff + 8
    ivars = []
    for i in range(count):
        entry_off = entries_off + i * entsize
        offset_ptr_vmaddr = img.read_ptr_field(entry_off)
        name_vmaddr = img.read_ptr_field(entry_off + 8)
        type_vmaddr = img.read_ptr_field(entry_off + 16)
        name = img.read_cstring(name_vmaddr) if name_vmaddr else None
        type_encoding = img.read_cstring(type_vmaddr) if type_vmaddr else None
        ivar_offset = None
        if offset_ptr_vmaddr is not None:
            off_fileoff = img.vmaddr_to_fileoff(offset_ptr_vmaddr)
            if off_fileoff is not None:
                ivar_offset = struct.unpack_from("<i", img.data, off_fileoff)[0]
        if name:
            ivars.append({"name": name, "type_encoding": type_encoding, "offset": ivar_offset})
    return ivars


def _resolve_protocol_name(img: MachOImage, protocol_ptr_fileoff: int) -> str | None:
    protocol_vmaddr = img.read_ptr_field(protocol_ptr_fileoff)
    if protocol_vmaddr is None:
        bind_name = img.read_bind_symbol(protocol_ptr_fileoff)
        return _strip_objc_symbol_prefix(bind_name)
    proto_fileoff = img.vmaddr_to_fileoff(protocol_vmaddr)
    if proto_fileoff is None:
        return None
    name_vmaddr = img.read_ptr_field(proto_fileoff + 8)  # protocol_t.mangledName, after isa
    return img.read_cstring(name_vmaddr) if name_vmaddr else None


def _parse_protocol_list(img: MachOImage, list_ptr: int | None) -> list[str]:
    if list_ptr is None or list_ptr & 1:
        return []
    fileoff = img.vmaddr_to_fileoff(list_ptr)
    if fileoff is None:
        return []
    count = struct.unpack_from("<Q", img.data, fileoff)[0]
    if count > 5000:
        return []
    names = []
    for i in range(count):
        entry_off = fileoff + 8 + i * 8
        name = _resolve_protocol_name(img, entry_off)
        if name:
            names.append(name)
    return names


def _parse_class_ro(img: MachOImage, ro_vmaddr: int, methods_only: bool = False) -> dict | None:
    fileoff = img.vmaddr_to_fileoff(ro_vmaddr)
    if fileoff is None:
        return None

    name = None
    if not methods_only:
        name_vmaddr = img.read_ptr_field(fileoff + 24)
        name = img.read_cstring(name_vmaddr) if name_vmaddr else None

    base_methods_ptr = img.read_ptr_field(fileoff + 32)
    instance_methods = _parse_method_list(img, base_methods_ptr)

    if methods_only:
        return {"instance_methods": instance_methods}

    base_protocols_ptr = img.read_ptr_field(fileoff + 40)
    protocols = _parse_protocol_list(img, base_protocols_ptr)

    ivars_ptr = img.read_ptr_field(fileoff + 48)
    ivars = _parse_ivar_list(img, ivars_ptr)

    base_properties_ptr = img.read_ptr_field(fileoff + 64)
    properties = _parse_property_list(img, base_properties_ptr)

    return {
        "name": name,
        "instance_methods": instance_methods,
        "protocols": protocols,
        "ivars": ivars,
        "properties": properties,
    }


def _resolve_class_name_only(img: MachOImage, class_vmaddr: int) -> str | None:
    class_fileoff = img.vmaddr_to_fileoff(class_vmaddr)
    if class_fileoff is None:
        return None
    data_vmaddr = img.read_ptr_field(class_fileoff + 32)
    if data_vmaddr is None:
        return None
    ro_fileoff = img.vmaddr_to_fileoff(data_vmaddr & ~0x7)
    if ro_fileoff is None:
        return None
    name_vmaddr = img.read_ptr_field(ro_fileoff + 24)
    return img.read_cstring(name_vmaddr) if name_vmaddr else None


def _parse_class(img: MachOImage, class_vmaddr: int) -> dict | None:
    class_fileoff = img.vmaddr_to_fileoff(class_vmaddr)
    if class_fileoff is None:
        return None

    isa_vmaddr = img.read_ptr_field(class_fileoff + 0)
    superclass_vmaddr = img.read_ptr_field(class_fileoff + 8)
    superclass_bind = img.read_bind_symbol(class_fileoff + 8) if superclass_vmaddr is None else None
    data_vmaddr = img.read_ptr_field(class_fileoff + 32)
    if data_vmaddr is None:
        return None

    ro = _parse_class_ro(img, data_vmaddr & ~0x7)
    if ro is None or not ro["name"]:
        return None

    class_methods: list[dict] = []
    if isa_vmaddr is not None:
        meta_fileoff = img.vmaddr_to_fileoff(isa_vmaddr)
        if meta_fileoff is not None:
            meta_data_vmaddr = img.read_ptr_field(meta_fileoff + 32)
            if meta_data_vmaddr is not None:
                meta_ro = _parse_class_ro(img, meta_data_vmaddr & ~0x7, methods_only=True)
                if meta_ro:
                    class_methods = meta_ro["instance_methods"]

    superclass_name = None
    if superclass_vmaddr is not None:
        superclass_name = _resolve_class_name_only(img, superclass_vmaddr)
    elif superclass_bind:
        superclass_name = _strip_objc_symbol_prefix(superclass_bind)

    return {
        "name": ro["name"],
        "superclass": superclass_name,
        "superclass_resolved": superclass_vmaddr is not None or superclass_bind is not None,
        "instance_methods": ro["instance_methods"],
        "class_methods": class_methods,
        "properties": ro["properties"],
        "protocols": ro["protocols"],
        "ivars": ro["ivars"],
    }


def extract_objc_classes(data: bytes, slice_offset: int = 0) -> dict:
    """Returns {"classes": [...], "warnings": [...]}. Never raises for malformed
    input beyond what Python's struct module itself would refuse to unpack.
    `data` is the whole file's bytes; `slice_offset` locates the chosen arch
    slice within it (see machoinfo.find_preferred_slice)."""

    warnings: list[str] = []
    try:
        img = MachOImage(data, slice_offset)
    except Exception as exc:
        return {"classes": [], "warnings": [f"Could not parse Mach-O headers: {exc}"]}

    if img.unsupported_ptr_formats:
        warnings.append(
            "This binary uses a pointer-authentication (arm64e) fixup format that isn't "
            "decoded yet; some class metadata may be missing or incomplete."
        )

    classlist_section = img.find_section("__objc_classlist")
    if classlist_section is None:
        return {"classes": [], "warnings": warnings + ["No __objc_classlist section found (no Objective-C classes, or Swift-only binary)."]}

    count = classlist_section.size // 8
    classes = []
    unresolved = 0
    for i in range(count):
        ptr_field_off = classlist_section.offset + i * 8
        class_vmaddr = img.read_ptr_field(ptr_field_off)
        if class_vmaddr is None:
            unresolved += 1
            continue
        parsed = _parse_class(img, class_vmaddr)
        if parsed:
            classes.append(parsed)
        else:
            unresolved += 1

    if unresolved:
        warnings.append(f"{unresolved} of {count} classes could not be fully resolved.")

    classes.sort(key=lambda c: c["name"].lower())
    return {"classes": classes, "warnings": warnings}
