import mimetypes
import os
import plistlib
import shutil
import tempfile
import zipfile
from typing import Callable

from .binarycache import save_binary_slice
from .machoinfo import extract_entitlements, find_preferred_slice
from .objc_metadata import extract_objc_classes
from .symtab import extract_code_symbols

EXTRACT_ROOT = os.environ.get("EXTRACT_DIR", "/work")

ProgressFn = Callable[[int, str | None, str | None], None]


def _safe_extract(zf: zipfile.ZipFile, dest: str) -> None:
    dest_abs = os.path.abspath(dest)
    for member in zf.infolist():
        member_path = os.path.abspath(os.path.join(dest, member.filename))
        if member_path != dest_abs and not member_path.startswith(dest_abs + os.sep):
            raise ValueError(f"Refusing to extract unsafe zip entry path: {member.filename!r}")
    zf.extractall(dest)


def _guess_mime(name: str) -> str | None:
    mime, _ = mimetypes.guess_type(name)
    return mime


def _build_file_tree(root_dir: str) -> list[dict]:
    nodes: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        rel_dir = os.path.relpath(dirpath, root_dir)
        rel_dir = "" if rel_dir == "." else rel_dir

        for d in dirnames:
            rel_path = f"{rel_dir}/{d}" if rel_dir else d
            nodes.append(
                {
                    "parent_path": rel_dir or None,
                    "path": rel_path,
                    "name": d,
                    "kind": "dir",
                    "size_bytes": None,
                    "mime_guess": None,
                    "is_main_binary": False,
                }
            )

        for fname in filenames:
            rel_path = f"{rel_dir}/{fname}" if rel_dir else fname
            full_path = os.path.join(dirpath, fname)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                size = None
            nodes.append(
                {
                    "parent_path": rel_dir or None,
                    "path": rel_path,
                    "name": fname,
                    "kind": "file",
                    "size_bytes": size,
                    "mime_guess": _guess_mime(fname),
                    "is_main_binary": False,
                }
            )
    return nodes


def _find_app_dir(root_dir: str) -> str | None:
    payload_dir = os.path.join(root_dir, "Payload")
    if not os.path.isdir(payload_dir):
        return None
    for entry in os.listdir(payload_dir):
        if entry.endswith(".app"):
            return os.path.join(payload_dir, entry)
    return None


def analyze(ipa_id: str, storage_path: str, progress: ProgressFn) -> dict:
    progress(5, "Extracting IPA", "extract")
    os.makedirs(EXTRACT_ROOT, exist_ok=True)
    work_dir = tempfile.mkdtemp(prefix="ipa_", dir=EXTRACT_ROOT)
    try:
        with zipfile.ZipFile(storage_path) as zf:
            _safe_extract(zf, work_dir)

        progress(30, "Building file tree", "extract")
        nodes = _build_file_tree(work_dir)

        plists_out: list[dict] = []
        objc_classes: list[dict] = []
        objc_warnings: list[str] = []
        symbols: list[dict] = []
        app_dir = _find_app_dir(work_dir)
        main_binary_rel = None

        if app_dir:
            info_plist_path = os.path.join(app_dir, "Info.plist")
            info = None
            if os.path.isfile(info_plist_path):
                with open(info_plist_path, "rb") as f:
                    info = plistlib.load(f)
                rel = os.path.relpath(info_plist_path, work_dir)
                plists_out.append({"node_path": rel, "kind": "info", "parsed": info})

            if info and info.get("CFBundleExecutable"):
                candidate = os.path.join(app_dir, info["CFBundleExecutable"])
                if os.path.isfile(candidate):
                    main_binary_rel = os.path.relpath(candidate, work_dir)

            progress(55, "Parsing entitlements", "extract")
            if main_binary_rel:
                binary_abs = os.path.join(work_dir, main_binary_rel)
                with open(binary_abs, "rb") as f:
                    binary_data = f.read()
                slice_offset, slice_size = find_preferred_slice(binary_data)
                sliced_data = (
                    binary_data[slice_offset : slice_offset + slice_size]
                    if (slice_offset or slice_size != len(binary_data))
                    else binary_data
                )
                save_binary_slice(ipa_id, sliced_data)

                try:
                    entitlements = extract_entitlements(binary_data, slice_offset)
                except Exception:
                    entitlements = None
                if entitlements is not None:
                    plists_out.append(
                        {"node_path": main_binary_rel, "kind": "entitlements", "parsed": entitlements}
                    )

                progress(65, "Parsing Objective-C class metadata", "extract")
                try:
                    objc_result = extract_objc_classes(binary_data, slice_offset)
                    objc_classes = objc_result["classes"]
                    objc_warnings = objc_result["warnings"]
                except Exception as exc:
                    objc_warnings = [f"Objective-C metadata extraction failed: {exc}"]

                progress(75, "Parsing symbol table", "extract")
                try:
                    symbols = extract_code_symbols(binary_data, slice_offset)
                except Exception:
                    symbols = []

        if main_binary_rel:
            for n in nodes:
                if n["path"] == main_binary_rel:
                    n["is_main_binary"] = True

        progress(90, "Finalizing", "extract")
        return {
            "file_tree": nodes,
            "plists": plists_out,
            "objc_classes": objc_classes,
            "objc_warnings": objc_warnings,
            "symbols": symbols,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
