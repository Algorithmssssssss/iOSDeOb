"""Caches each IPA's already-sliced (single-arch) main binary to a writable
volume, so on-demand disassembly requests don't need to re-open/re-unzip the
whole IPA (which can be 100s of MB) for every function a user clicks."""

import os

BINARIES_DIR = os.environ.get("BINARIES_DIR", "/binaries")


def cache_path(ipa_id: str) -> str:
    return os.path.join(BINARIES_DIR, f"{ipa_id}.bin")


def save_binary_slice(ipa_id: str, sliced_data: bytes) -> None:
    os.makedirs(BINARIES_DIR, exist_ok=True)
    with open(cache_path(ipa_id), "wb") as f:
        f.write(sliced_data)


def load_binary_slice(ipa_id: str) -> bytes:
    with open(cache_path(ipa_id), "rb") as f:
        return f.read()


def has_cached_binary(ipa_id: str) -> bool:
    return os.path.isfile(cache_path(ipa_id))


def delete_cached_binary(ipa_id: str) -> None:
    if has_cached_binary(ipa_id):
        os.remove(cache_path(ipa_id))
