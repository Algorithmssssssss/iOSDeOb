"""Fix up Apple's CgBI-chunked PNGs (produced by Xcode's build-time PNG
optimizer for standalone image resources) so they render in a normal browser.

CgBI PNGs differ from standard PNGs in three ways: an extra 'CgBI' chunk before
IHDR, IDAT payloads are raw DEFLATE (no zlib header/checksum), and pixel data is
stored as premultiplied-alpha BGRA instead of RGBA. We rebuild a standard PNG
(fixing the zlib wrapper) so Pillow's real PNG decoder can do the hard part
(scanline de-filtering), then fix the channel order and un-premultiply alpha
ourselves. Reference: this is the same transform tools like "pngdefry" do.
"""

import struct
import zlib
from io import BytesIO

import numpy as np
from PIL import Image

PNG_SIGNATURE = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])


def _iter_chunks(data: bytes):
    i = 8
    n = len(data)
    while i + 8 <= n:
        length = int.from_bytes(data[i : i + 4], "big")
        ctype = data[i + 4 : i + 8]
        payload = data[i + 8 : i + 8 + length]
        yield ctype, payload
        i += 12 + length
        if ctype == b"IEND":
            break


def _write_chunk(ctype: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + ctype
        + payload
        + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF)
    )


def is_cgbi_png(data: bytes) -> bool:
    if data[:8] != PNG_SIGNATURE:
        return False
    for ctype, _ in _iter_chunks(data):
        if ctype == b"CgBI":
            return True
        if ctype == b"IDAT":
            return False
    return False


def defry_cgbi_png(data: bytes) -> bytes:
    """Returns a standard, browser-renderable PNG. Raises on anything unexpected
    (caller should catch and fall back to serving the original bytes)."""

    ihdr = None
    idat_parts: list[bytes] = []
    for ctype, payload in _iter_chunks(data):
        if ctype == b"IHDR":
            ihdr = payload
        elif ctype == b"IDAT":
            idat_parts.append(payload)

    if ihdr is None or not idat_parts:
        raise ValueError("Missing IHDR/IDAT in CgBI PNG")

    width, height, bitdepth, colortype, _compression, _filter_method, _interlace = struct.unpack(
        ">IIBBBBB", ihdr
    )
    if bitdepth != 8 or colortype != 6:
        raise ValueError(f"Unsupported CgBI PNG format (bitdepth={bitdepth}, colortype={colortype})")

    raw_compressed = b"".join(idat_parts)
    decompressor = zlib.decompressobj(-15)  # raw DEFLATE: CgBI strips the zlib header/checksum
    filtered_scanlines = decompressor.decompress(raw_compressed) + decompressor.flush()

    rewrapped_idat = zlib.compress(filtered_scanlines)
    rebuilt_png = (
        PNG_SIGNATURE
        + _write_chunk(b"IHDR", ihdr)
        + _write_chunk(b"IDAT", rewrapped_idat)
        + _write_chunk(b"IEND", b"")
    )

    img = Image.open(BytesIO(rebuilt_png))
    img.load()
    arr = np.asarray(img.convert("RGBA"))  # bytes are actually [B, G, R, A_premultiplied] per pixel

    stored_b, stored_g, stored_r, alpha = (arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3])
    alpha_f = alpha.astype(np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = np.where(alpha_f > 0, 255.0 / alpha_f, 0.0)

    def unpremultiply(channel: np.ndarray) -> np.ndarray:
        return np.clip(channel.astype(np.float32) * scale, 0, 255).astype(np.uint8)

    fixed = np.stack(
        [unpremultiply(stored_r), unpremultiply(stored_g), unpremultiply(stored_b), alpha],
        axis=-1,
    )
    fixed_img = Image.fromarray(fixed, mode="RGBA")

    out = BytesIO()
    fixed_img.save(out, format="PNG")
    return out.getvalue()
