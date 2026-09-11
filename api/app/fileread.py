"""On-demand read of a single member from an already-uploaded IPA (zip) for
file preview/download. We never re-extract the whole archive to disk here —
just look up one named entry and read its bytes into memory (bounded by
MAX_PREVIEW_BYTES), which carries none of the zip-slip risk that extracting to
disk does since nothing is written to the filesystem."""

import base64
import mimetypes
import plistlib
import zipfile
from dataclasses import dataclass
from typing import Optional

from .cgbi import is_cgbi_png, defry_cgbi_png

MAX_PREVIEW_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PREVIEW_BYTES = 3 * 1024 * 1024
HEX_DUMP_BYTES = 512

TEXT_EXTENSIONS = {
    ".plist", ".strings", ".json", ".txt", ".xml", ".h", ".m", ".mm", ".c", ".cc",
    ".cpp", ".swift", ".entitlements", ".pbxproj", ".storyboard", ".xib", ".md",
    ".yml", ".yaml", ".js", ".css", ".html", ".htm", ".sh", ".cfg", ".ini", ".log",
    ".nib.txt",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}


@dataclass
class FilePreview:
    path: str
    size_bytes: int
    kind: str  # "plist" | "text" | "image" | "binary" | "empty"
    mime_guess: Optional[str] = None
    text: Optional[str] = None
    parsed: Optional[object] = None
    image_base64: Optional[str] = None
    hex_preview: Optional[str] = None
    truncated: bool = False


def _ext(path: str) -> str:
    idx = path.rfind(".")
    return path[idx:].lower() if idx != -1 else ""


def _hex_dump(data: bytes) -> str:
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i : i + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:08x}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)


def read_member_preview(ipa_zip_path: str, member_path: str) -> FilePreview:
    with zipfile.ZipFile(ipa_zip_path) as zf:
        info = zf.getinfo(member_path)  # raises KeyError if absent
        size = info.file_size
        ext = _ext(member_path)
        mime_guess = mimetypes.guess_type(member_path)[0]

        if size == 0:
            return FilePreview(path=member_path, size_bytes=0, kind="empty", mime_guess=mime_guess)

        if ext in IMAGE_EXTENSIONS and size <= MAX_IMAGE_PREVIEW_BYTES:
            data = zf.read(member_path)
            if ext == ".png" and is_cgbi_png(data):
                try:
                    data = defry_cgbi_png(data)
                except Exception:
                    pass  # fall back to serving the original (possibly non-rendering) bytes
            return FilePreview(
                path=member_path,
                size_bytes=size,
                kind="image",
                mime_guess=mime_guess or "application/octet-stream",
                image_base64=base64.b64encode(data).decode("ascii"),
            )

        if size > MAX_PREVIEW_BYTES:
            with zf.open(member_path) as f:
                head = f.read(HEX_DUMP_BYTES)
            return FilePreview(
                path=member_path,
                size_bytes=size,
                kind="binary",
                mime_guess=mime_guess,
                hex_preview=_hex_dump(head),
                truncated=True,
            )

        data = zf.read(member_path)

        if ext == ".plist":
            try:
                parsed = plistlib.loads(data)
                return FilePreview(path=member_path, size_bytes=size, kind="plist", mime_guess=mime_guess, parsed=parsed)
            except Exception:
                pass  # fall through to text/binary handling below

        if ext in TEXT_EXTENSIONS:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = data.decode("utf-16")
                except UnicodeDecodeError:
                    text = data.decode("latin-1")
            return FilePreview(path=member_path, size_bytes=size, kind="text", mime_guess=mime_guess, text=text)

        try:
            text = data.decode("utf-8")
            return FilePreview(path=member_path, size_bytes=size, kind="text", mime_guess=mime_guess, text=text)
        except UnicodeDecodeError:
            return FilePreview(
                path=member_path,
                size_bytes=size,
                kind="binary",
                mime_guess=mime_guess,
                hex_preview=_hex_dump(data[:HEX_DUMP_BYTES]),
            )


def open_member_stream(ipa_zip_path: str, member_path: str):
    zf = zipfile.ZipFile(ipa_zip_path)
    info = zf.getinfo(member_path)  # raises KeyError if absent
    return zf, zf.open(member_path), info
