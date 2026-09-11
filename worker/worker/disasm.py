"""On-demand, single-function disassembly via radare2. Deliberately avoids
r2's whole-binary `aa`/`aaa` analysis (measured at multiple minutes even on a
~40MB real app binary — far too slow for an interactive "click a function"
UI); `af @ addr` analyzes just the one function and is sub-second regardless
of binary size, since it only follows control flow from that entry point."""

import r2pipe

from .callerscan import find_callers

MAX_CALLERS = 200


def disassemble_function(binary_path: str, address: int, whole_binary_data: bytes) -> dict:
    r2 = r2pipe.open(binary_path, ["-2", "-e", "bin.cache=true", "-e", "scr.color=0"])
    decompiled_code = None
    decompile_error = None
    try:
        r2.cmd(f"af @ {address}")
        info_list = r2.cmdj(f"afij @ {address}") or []
        info = info_list[0] if info_list else {}
        pdf = r2.cmdj(f"pdfj @ {address}") or {"ops": []}

        try:
            pdg_out = r2.cmd(f"pdg @ {address}")
            if pdg_out and pdg_out.strip():
                decompiled_code = pdg_out
            else:
                decompile_error = "Decompiler (r2ghidra) produced no output for this function."
        except Exception as exc:
            decompile_error = f"Decompilation failed: {exc}"
    finally:
        r2.quit()

    ops = []
    calls_out = []
    for op in pdf.get("ops", []):
        entry = {
            "address": op.get("addr"),
            "bytes": op.get("bytes"),
            "disasm": op.get("disasm") or op.get("opcode"),
            "type": op.get("type"),
        }
        ops.append(entry)
        if op.get("type") == "call" and op.get("jump"):
            calls_out.append({"address": op.get("addr"), "target": op.get("jump")})

    callers_in = find_callers(whole_binary_data, 0, address)[:MAX_CALLERS]

    return {
        "address": address,
        "name": info.get("name"),
        "size": info.get("size"),
        "signature": info.get("signature"),
        "ops": ops,
        "calls_out": calls_out,
        "callers_in": callers_in,
        "decompiled_code": decompiled_code,
        "decompile_error": decompile_error,
    }
