"""MCP server for iOSDeOb — lets an MCP-compatible AI client (Claude Code,
Claude Desktop, etc.) upload an .ipa to the iOSDeOb analysis stack and query
its file tree, Objective-C classes, functions, and — most importantly — the
Ghidra-decompiled pseudo-C for any function, so the model can reason about
what the app actually does.

Runs directly on the host (not inside Docker) over the stdio transport, and
talks to the already-running docker-compose stack's public API port. Start
the stack first (`docker compose up -d` in the project root), then register
this script's interpreter + path with your MCP client (e.g. `claude mcp add`,
or the mcpServers block in claude_desktop_config.json).
"""

import functools
import os
import time
from pathlib import Path
from typing import Any

import requests
from mcp.server.mcpserver import MCPServer

API_BASE = os.environ.get("IOSDEOB_API_BASE", "http://localhost:8080/api")
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 300


class NotFoundError(Exception):
    """Raised when the API returns 404 — an unknown ipa_id, path, class, etc."""


mcp = MCPServer(
    name="iosdeob",
    instructions=(
        "Static analysis of iOS .ipa files: file browsing, Objective-C class/method "
        "metadata, and on-demand ARM64 disassembly + Ghidra decompilation. Typical "
        "flow: upload_ipa -> list_classes/list_functions (optionally with a query) to "
        "find something interesting -> get_class or get_function_detail for the full "
        "picture. get_function_detail is the main way to actually read what code does "
        "(it returns Ghidra's decompiled pseudo-C). Only static analysis is performed; "
        "nothing is ever executed. FairPlay-encrypted (straight-from-App-Store) "
        "binaries won't parse correctly — use a dev-signed/ad-hoc/decrypted build."
    ),
)


def _get(path: str, **kwargs) -> Any:
    resp = requests.get(f"{API_BASE}{path}", timeout=30, **kwargs)
    if resp.status_code == 404:
        raise NotFoundError(path)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, **kwargs) -> Any:
    resp = requests.post(f"{API_BASE}{path}", timeout=30, **kwargs)
    if resp.status_code == 404:
        raise NotFoundError(path)
    resp.raise_for_status()
    return resp.json()


def _not_found_returns(message: str):
    """Converts a NotFoundError raised anywhere inside the wrapped tool into a
    clean {"error": ...} result instead of letting an HTTP exception/traceback
    reach the MCP client (e.g. for a made-up ipa_id, path, or class name)."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except NotFoundError:
                return {"error": message}

        return wrapper

    return decorator


def _flatten_tree(nodes: list[dict], out: list[dict]) -> list[dict]:
    for n in nodes:
        out.append(
            {
                "path": n["path"],
                "name": n["name"],
                "kind": n["kind"],
                "size_bytes": n.get("size_bytes"),
                "is_main_binary": n.get("is_main_binary", False),
            }
        )
        if n["kind"] == "dir":
            _flatten_tree(n["children"], out)
    return out


def _paginate(items: list[Any], limit: int) -> dict:
    limit = max(1, min(limit, MAX_LIST_LIMIT))
    return {
        "total_matches": len(items),
        "returned_count": min(len(items), limit),
        "truncated": len(items) > limit,
        "results": items[:limit],
    }


@mcp.tool()
def upload_ipa(file_path: str, wait: bool = True, timeout_seconds: int = 300) -> dict:
    """Upload a local .ipa file to iOSDeOb for static analysis.

    Args:
        file_path: Absolute path to the .ipa file on this machine.
        wait: If True (default), block until extraction finishes (or fails/times out)
            and return the final scan status. If False, return immediately with the
            new scan's id and status "pending" — check back later with get_scan_info.
        timeout_seconds: Max time to wait for extraction when wait=True.

    Returns the scan record: {id, original_filename, size_bytes, status, error_message}.
    `status` becomes "ready" once file_tree/classes/functions/plists are queryable.
    """
    path = Path(file_path).expanduser()
    if not path.is_file():
        return {"error": f"File not found: {path}"}
    if path.suffix.lower() != ".ipa":
        return {"error": f"Not a .ipa file: {path}"}

    with open(path, "rb") as f:
        resp = requests.post(
            f"{API_BASE}/ipas/upload",
            files={"file": (path.name, f, "application/octet-stream")},
            timeout=120,
        )
    resp.raise_for_status()
    ipa = resp.json()

    if not wait:
        return ipa

    ipa_id = ipa["id"]
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        info = _get(f"/ipas/{ipa_id}")
        if info["status"] in ("ready", "failed"):
            return info
        time.sleep(2)
    return {**ipa, "status": "timeout", "note": "Still processing; call get_scan_info later."}


@mcp.tool()
def list_scans() -> list[dict]:
    """List every .ipa previously uploaded to iOSDeOb, most recent first."""
    return _get("/ipas")


@mcp.tool()
@_not_found_returns("Scan not found.")
def get_scan_info(ipa_id: str) -> dict:
    """Get a scan's status plus its extraction job history (progress, errors)."""
    ipa = _get(f"/ipas/{ipa_id}")
    ipa["jobs"] = _get(f"/ipas/{ipa_id}/jobs")
    return ipa


@mcp.tool()
@_not_found_returns("Scan not found.")
def list_files(ipa_id: str, query: str | None = None, limit: int = DEFAULT_LIST_LIMIT) -> dict:
    """List files in the unzipped .ipa bundle, optionally filtered by a substring
    match on name or path (case-insensitive). Use this to find e.g. Info.plist,
    specific storyboards/nibs, embedded frameworks, or resource files."""
    tree = _get(f"/ipas/{ipa_id}/tree")
    flat = _flatten_tree(tree, [])
    if query:
        q = query.lower()
        flat = [n for n in flat if q in n["path"].lower() or q in n["name"].lower()]
    return _paginate(flat, limit)


@mcp.tool()
def read_file(ipa_id: str, path: str) -> dict:
    """Read one file's content from the bundle (path as returned by list_files).
    Text and plist files come back in full (plists as parsed JSON); large or
    binary files come back as a hex preview of the first bytes plus metadata
    rather than the full content. Image bytes are never returned here — use the
    web UI to view images."""
    resp = requests.get(f"{API_BASE}/ipas/{ipa_id}/file", params={"path": path}, timeout=30)
    if resp.status_code == 404:
        return {"error": "File not found in this scan's bundle."}
    resp.raise_for_status()
    data = resp.json()
    if data.get("kind") == "image":
        return {
            "path": path,
            "kind": "image",
            "size_bytes": data.get("size_bytes"),
            "mime_guess": data.get("mime_guess"),
            "note": "Image content omitted from MCP responses; open it in the iOSDeOb web UI to view it.",
        }
    data.pop("image_base64", None)
    return data


@mcp.tool()
@_not_found_returns("Scan not found.")
def get_info_plist(ipa_id: str) -> dict:
    """Get the app's parsed Info.plist (bundle id, version, permissions usage
    strings, URL schemes, etc.)."""
    for p in _get(f"/ipas/{ipa_id}/plists"):
        if p["kind"] == "info":
            return p["parsed"]
    return {"error": "Info.plist not found — is the scan still processing?"}


@mcp.tool()
@_not_found_returns("Scan not found.")
def get_entitlements(ipa_id: str) -> dict:
    """Get the main binary's code-signing entitlements (app groups, keychain
    access groups, associated domains, capabilities, etc.)."""
    for p in _get(f"/ipas/{ipa_id}/plists"):
        if p["kind"] == "entitlements":
            return p["parsed"]
    return {"error": "No entitlements found for this binary."}


@mcp.tool()
@_not_found_returns("Scan not found.")
def list_classes(ipa_id: str, query: str | None = None, limit: int = DEFAULT_LIST_LIMIT) -> dict:
    """Search Objective-C classes by (substring, case-insensitive) name. Returns
    a compact summary per class — use get_class for the full method/property list
    of one specific class."""
    resp = _get(f"/ipas/{ipa_id}/classes")
    classes = resp["classes"]
    if query:
        q = query.lower()
        classes = [c for c in classes if q in c["name"].lower()]

    summarized = [
        {
            "name": c["name"],
            "superclass": c.get("superclass"),
            "protocols": c.get("protocols", []),
            "instance_method_count": len(c.get("instance_methods", [])),
            "class_method_count": len(c.get("class_methods", [])),
            "property_count": len(c.get("properties", [])),
        }
        for c in classes
    ]
    page = _paginate(summarized, limit)
    page["warnings"] = resp.get("warnings", [])
    return page


@mcp.tool()
@_not_found_returns("Scan not found.")
def get_class(ipa_id: str, class_name: str) -> dict:
    """Get one Objective-C class's full interface: superclass, protocols, ivars
    (with offsets), properties (with attributes), and every method (selector,
    type encoding, and its address — feed that address into get_function_detail
    to see what the method's code actually does)."""
    for c in _get(f"/ipas/{ipa_id}/classes")["classes"]:
        if c["name"] == class_name:
            return c
    return {"error": f"Class {class_name!r} not found in this scan."}


@mcp.tool()
@_not_found_returns("Scan not found.")
def list_functions(ipa_id: str, query: str | None = None, limit: int = DEFAULT_LIST_LIMIT) -> dict:
    """Search known functions by (substring, case-insensitive) name — covers every
    Objective-C method (formatted like -[ClassName selector:]) plus named C
    symbols recovered from the binary's symbol table. Not exhaustive: functions
    with no retained symbol and no ObjC metadata won't appear here, but can still
    be reached by address via get_function_detail if you find their address some
    other way (e.g. as a call target inside another function's disassembly)."""
    functions = _get(f"/ipas/{ipa_id}/functions")
    if query:
        q = query.lower()
        functions = [f for f in functions if q in f["name"].lower()]
    return _paginate(functions, limit)


@mcp.tool()
@_not_found_returns("Scan not found.")
def get_function_detail(
    ipa_id: str,
    address: int,
    include_assembly: bool = False,
    timeout_seconds: int = 90,
) -> dict:
    """Disassemble and decompile one function by address (from list_functions,
    get_class's method addresses, or a calls_out/callers_in address from a
    previous get_function_detail call). Runs radare2 + the Ghidra decompiler
    on demand for just this function (fast — a couple of seconds even on huge
    binaries) and caches the result, so repeat calls for the same address are
    instant.

    Returns: name, size, signature, decompiled_code (Ghidra's pseudo-C — this is
    the main thing to read to understand what the function does), calls_out
    (direct calls this function makes, with resolved names where known),
    callers_in (direct callers found by scanning for BL instructions — this
    misses Objective-C message sends, i.e. most ObjC-to-ObjC calls, since those
    dispatch dynamically via objc_msgSend rather than a direct branch).

    Set include_assembly=True to also get the raw ARM64 instruction listing
    (omitted by default since decompiled_code is usually what you actually want
    and the raw listing can be long).
    """
    body = _post(f"/ipas/{ipa_id}/disasm", json={"address": address})

    if body.get("cached") and body.get("result"):
        result = body["result"]
    else:
        job_id = body.get("job_id")
        if not job_id:
            return {"error": "Failed to enqueue disassembly job."}
        deadline = time.time() + timeout_seconds
        result = None
        while time.time() < deadline:
            job = _get(f"/jobs/{job_id}")
            if job["status"] == "done":
                result = _get(f"/ipas/{ipa_id}/disasm/{address}")
                break
            if job["status"] == "failed":
                return {"error": job.get("error_message") or "Disassembly failed."}
            time.sleep(1)
        if result is None:
            return {"error": "Timed out waiting for disassembly.", "job_id": job_id}

    if not include_assembly:
        result.pop("ops", None)
    return result


if __name__ == "__main__":
    mcp.run()
