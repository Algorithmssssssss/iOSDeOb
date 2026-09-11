import { useState } from "react";
import { DisasmResult } from "../api";

function hex(n?: number | null): string {
  return n != null ? `0x${n.toString(16)}` : "?";
}

export default function DisassemblyView({
  result,
  onJumpTo,
}: {
  result: DisasmResult;
  onJumpTo: (address: number) => void;
}) {
  const hasDecompiled = !!result.decompiled_code;
  const [view, setView] = useState<"decompiled" | "assembly">(hasDecompiled ? "decompiled" : "assembly");

  return (
    <div className="file-viewer">
      <div className="file-viewer-toolbar">
        <div className="file-viewer-title">
          <h3>{result.name ?? hex(result.address)}</h3>
          <span className="file-viewer-meta">
            {hex(result.address)} {result.size != null ? `· ${result.size} bytes` : ""}
          </span>
        </div>
        <div className="view-toggle">
          <button
            className={`toggle-btn ${view === "decompiled" ? "active" : ""}`}
            onClick={() => setView("decompiled")}
            disabled={!hasDecompiled}
            title={hasDecompiled ? undefined : result.decompile_error ?? "Not available"}
          >
            Pseudo-C
          </button>
          <button className={`toggle-btn ${view === "assembly" ? "active" : ""}`} onClick={() => setView("assembly")}>
            Assembly
          </button>
        </div>
      </div>
      {result.signature && <div className="disasm-signature">{result.signature}</div>}

      {view === "decompiled" && hasDecompiled && (
        <pre className="code-block disasm-listing">{result.decompiled_code}</pre>
      )}
      {view === "decompiled" && !hasDecompiled && (
        <div className="notice">{result.decompile_error ?? "Decompilation isn't available for this function."}</div>
      )}

      {view === "assembly" && (
        <pre className="code-block disasm-listing">
          {result.ops.map((op, i) => (
            <div key={i} className="disasm-line">
              <span className="disasm-addr">{hex(op.address)}</span>
              <span className="disasm-bytes">{op.bytes}</span>
              <span className="disasm-op">{op.disasm}</span>
            </div>
          ))}
        </pre>
      )}

      <div className="xref-section">
        <div className="xref-col">
          <div className="panel-heading">Calls out ({result.calls_out.length})</div>
          {result.calls_out.length === 0 && <div className="empty-hint small">No direct calls found.</div>}
          {result.calls_out.map((c, i) => (
            <div key={i} className="xref-row" onClick={() => onJumpTo(c.target)}>
              <span className="xref-addr">{hex(c.address)}</span>
              <span className="xref-arrow">→</span>
              <span className="xref-name">{c.target_name ?? hex(c.target)}</span>
            </div>
          ))}
        </div>

        <div className="xref-col">
          <div className="panel-heading">Called by ({result.callers_in.length})</div>
          <div className="notice small">
            Direct-call callers only — Objective-C message sends (the majority of calls in this app)
            dispatch dynamically via objc_msgSend and won't show up here.
          </div>
          {result.callers_in.length === 0 && <div className="empty-hint small">No direct callers found.</div>}
          {result.callers_in.map((c, i) => (
            <div key={i} className="xref-row" onClick={() => onJumpTo(c.address)}>
              <span className="xref-addr">{hex(c.address)}</span>
              <span className="xref-name">{c.caller_name ?? "(unnamed)"}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
