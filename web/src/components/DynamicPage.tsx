import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DynamicRun,
  DynamicTraceEvent,
  ObjCClass,
  listDynamicEvents,
  listDynamicRuns,
  startDynamicTrace,
  stopJob,
} from "../api";

const KNOWN_CATEGORIES = ["objc_call", "network", "keychain", "crypto", "custom", "lifecycle", "error"] as const;

const CATEGORY_LABEL: Record<string, string> = {
  objc_call: "ObjC call",
  network: "Network",
  keychain: "Keychain",
  crypto: "Crypto",
  custom: "Custom",
  lifecycle: "Lifecycle",
  error: "Error",
};

function categoryLabel(cat: string): string {
  return CATEGORY_LABEL[cat] ?? cat;
}

function isRunning(run: DynamicRun | null): boolean {
  return !!run && (run.status === "queued" || run.status === "running");
}

function formatOffset(ms: number): string {
  return `${(ms / 1000).toFixed(2)}s`;
}

function EventRow({ event }: { event: DynamicTraceEvent }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="dyn-event" onClick={() => setExpanded((v) => !v)}>
      <div className="dyn-event-main">
        <span className="dyn-event-time mono">{formatOffset(event.ts_offset_ms)}</span>
        <span className={`dyn-badge tone-${event.category}`}>{categoryLabel(event.category)}</span>
        <span className="dyn-event-summary mono">{event.summary}</span>
      </div>
      {expanded && (
        <pre className="code-block dyn-event-detail">{JSON.stringify(event.detail, null, 2)}</pre>
      )}
    </div>
  );
}

export default function DynamicPage({
  ipaId,
  classes,
  bundleIdGuess,
}: {
  ipaId: string;
  classes: ObjCClass[];
  bundleIdGuess: string | null;
}) {
  const [runs, setRuns] = useState<DynamicRun[]>([]);
  const [activeRun, setActiveRun] = useState<DynamicRun | null>(null);
  const [events, setEvents] = useState<DynamicTraceEvent[]>([]);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const [bundleId, setBundleId] = useState("");
  const [classQuery, setClassQuery] = useState("");
  const [selectedClasses, setSelectedClasses] = useState<Set<string>>(new Set());
  const [traceNetwork, setTraceNetwork] = useState(true);
  const [traceCrypto, setTraceCrypto] = useState(true);
  const [durationSecs, setDurationSecs] = useState(30);
  const [customScript, setCustomScript] = useState("");
  const [customScriptFileName, setCustomScriptFileName] = useState<string | null>(null);
  const [showScriptEditor, setShowScriptEditor] = useState(false);

  // Hidden-categories model (not an allow-list): anything new — including
  // arbitrary category names a custom script sends — is visible by default.
  const [hiddenCategories, setHiddenCategories] = useState<Set<string>>(new Set());
  const [eventQuery, setEventQuery] = useState("");

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refreshRuns = useCallback(() => {
    listDynamicRuns(ipaId)
      .then((r) => {
        setRuns(r);
        setActiveRun((prev) => {
          if (prev) {
            const updated = r.find((run) => run.id === prev.id);
            if (updated) return updated;
          }
          return r[0] ?? null;
        });
      })
      .catch(console.error);
  }, [ipaId]);

  useEffect(() => {
    setRuns([]);
    setActiveRun(null);
    setEvents([]);
    setBundleId(bundleIdGuess ?? "");
    refreshRuns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ipaId]);

  useEffect(() => {
    setEvents([]);
  }, [activeRun?.id]);

  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (!activeRun) return;

    const poll = () => {
      listDynamicEvents(ipaId, activeRun.id, events.length > 0 ? events[events.length - 1].seq : 0)
        .then((newEvents) => {
          if (newEvents.length > 0) {
            setEvents((prev) => [...prev, ...newEvents]);
          }
        })
        .catch(console.error);
      if (isRunning(activeRun)) {
        refreshRuns();
      }
    };

    poll();
    if (isRunning(activeRun)) {
      pollRef.current = setInterval(poll, 1200);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRun?.id, activeRun?.status]);

  const filteredClasses = useMemo(() => {
    if (!classQuery.trim()) return classes;
    const q = classQuery.toLowerCase();
    return classes.filter((c) => c.name.toLowerCase().includes(q));
  }, [classes, classQuery]);

  const presentCategories = useMemo(() => {
    const seen = new Set<string>(KNOWN_CATEGORIES);
    events.forEach((e) => seen.add(e.category));
    return Array.from(seen);
  }, [events]);

  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      if (hiddenCategories.has(e.category)) return false;
      if (eventQuery.trim() && !e.summary.toLowerCase().includes(eventQuery.toLowerCase())) return false;
      return true;
    });
  }, [events, hiddenCategories, eventQuery]);

  function toggleClass(name: string) {
    setSelectedClasses((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function toggleCategory(cat: string) {
    setHiddenCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }

  function handleScriptFile(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      setCustomScript(String(reader.result ?? ""));
      setCustomScriptFileName(file.name);
      setShowScriptEditor(true);
    };
    reader.readAsText(file);
  }

  function clearScript() {
    setCustomScript("");
    setCustomScriptFileName(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleStart() {
    setStarting(true);
    setStartError(null);
    try {
      const run = await startDynamicTrace(ipaId, {
        bundle_id: bundleId.trim() || undefined,
        classes: Array.from(selectedClasses),
        trace_network: traceNetwork,
        trace_crypto: traceCrypto,
        duration_secs: durationSecs,
        custom_script: customScript.trim() || undefined,
      });
      setRuns((prev) => [run, ...prev]);
      setActiveRun(run);
    } catch (e) {
      setStartError((e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  async function handleStop() {
    if (!activeRun) return;
    try {
      const run = await stopJob(activeRun.id);
      setActiveRun(run);
    } catch (e) {
      window.alert(`Failed to stop: ${(e as Error).message}`);
    }
  }

  return (
    <div className="dynamic-page">
      <div className="dynamic-config-panel">
        <div className="panel-heading">Start a trace</div>
        <label className="dyn-field">
          <span>Bundle ID</span>
          <input
            className="search-input"
            value={bundleId}
            onChange={(e) => setBundleId(e.target.value)}
            placeholder="com.example.app"
          />
        </label>

        <label className="dyn-field">
          <span>Hook classes ({selectedClasses.size} selected)</span>
          <input
            className="search-input"
            placeholder={`Search ${classes.length} classes…`}
            value={classQuery}
            onChange={(e) => setClassQuery(e.target.value)}
          />
        </label>
        <div className="dyn-class-list">
          {filteredClasses.slice(0, 300).map((c) => (
            <label key={c.name} className="dyn-class-row">
              <input
                type="checkbox"
                checked={selectedClasses.has(c.name)}
                onChange={() => toggleClass(c.name)}
              />
              <span className="mono">{c.name}</span>
            </label>
          ))}
          {filteredClasses.length === 0 && <div className="empty-hint small">No matches.</div>}
        </div>

        <label className="dyn-checkbox-field">
          <input type="checkbox" checked={traceNetwork} onChange={(e) => setTraceNetwork(e.target.checked)} />
          <span>Trace network calls (NSURLSession / NSURLConnection)</span>
        </label>
        <label className="dyn-checkbox-field">
          <input type="checkbox" checked={traceCrypto} onChange={(e) => setTraceCrypto(e.target.checked)} />
          <span>Trace crypto, keychain &amp; SSL pinning checkpoints</span>
        </label>

        <div className="dyn-field">
          <span>Custom Frida script (optional)</span>
          <div className="dyn-script-upload">
            <input
              ref={fileInputRef}
              type="file"
              accept=".js"
              id="dyn-script-file"
              className="dyn-script-file-input"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleScriptFile(file);
              }}
            />
            <label htmlFor="dyn-script-file" className="btn btn-secondary dyn-script-upload-btn">
              📄 Upload .js
            </label>
            {customScriptFileName && <span className="dyn-script-filename mono">{customScriptFileName}</span>}
            {customScript && (
              <>
                <button className="btn btn-secondary" onClick={() => setShowScriptEditor((v) => !v)}>
                  {showScriptEditor ? "Hide" : "Edit"}
                </button>
                <button className="btn btn-secondary" onClick={clearScript}>
                  Clear
                </button>
              </>
            )}
          </div>
          <div className="muted dyn-script-hint">
            Runs alongside the hooks above, in its own script — a syntax error or exception in it won't affect
            the built-in hooks. Anything it <code className="mono">send()</code>s is logged as a{" "}
            <code className="mono">custom</code> event below.
          </div>
          {(showScriptEditor || (!customScriptFileName && customScript === "")) && (
            <textarea
              className="dyn-script-editor mono"
              placeholder={"// Paste or write a Frida script here, e.g.:\nInterceptor.attach(Module.findGlobalExportByName('SecItemAdd'), {\n  onEnter() { send({ summary: 'SecItemAdd called' }); }\n});"}
              value={customScript}
              onChange={(e) => {
                setCustomScript(e.target.value);
                if (customScriptFileName) setCustomScriptFileName(null);
              }}
            />
          )}
        </div>

        <label className="dyn-field">
          <span>Duration (seconds, max 300)</span>
          <input
            className="search-input"
            type="number"
            min={1}
            max={300}
            value={durationSecs}
            onChange={(e) => setDurationSecs(Number(e.target.value))}
          />
        </label>

        {startError && <div className="error-text">{startError}</div>}

        <button className="btn" disabled={starting || isRunning(activeRun)} onClick={handleStart}>
          {starting ? "Starting…" : "▶ Start trace"}
        </button>

        {runs.length > 0 && (
          <>
            <div className="panel-heading dyn-runs-heading">Past runs</div>
            <div className="dyn-runs-list">
              {runs.map((run) => (
                <div
                  key={run.id}
                  className={`dyn-run-row ${activeRun?.id === run.id ? "selected" : ""}`}
                  onClick={() => setActiveRun(run)}
                >
                  <span className={`pill pill-${run.status}`}>{run.status}</span>
                  <span className="mono dyn-run-bundle">{run.config?.bundle_id ?? "?"}</span>
                  {run.config?.has_custom_script && <span title="Used a custom script">📄</span>}
                  <span className="muted dyn-run-time">
                    {run.started_at ? new Date(run.started_at).toLocaleTimeString() : "—"}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="dynamic-results-panel">
        {!activeRun && <div className="empty-hint">Configure and start a trace to see live results here.</div>}

        {activeRun && (
          <>
            <div className="dyn-run-header">
              <span className={`pill pill-${activeRun.status}`}>{activeRun.status}</span>
              <span className="mono">{activeRun.config?.bundle_id}</span>
              {isRunning(activeRun) && (
                <button className="btn btn-secondary" onClick={handleStop} disabled={activeRun.stop_requested}>
                  {activeRun.stop_requested ? "Stopping…" : "■ Stop"}
                </button>
              )}
            </div>
            {isRunning(activeRun) && (
              <div className="progress-bar-outer">
                <div className="progress-bar-inner" style={{ width: `${activeRun.progress_pct}%` }} />
              </div>
            )}
            {activeRun.message && <div className="dyn-run-message muted">{activeRun.message}</div>}
            {activeRun.error_message && <div className="error-text">{activeRun.error_message}</div>}

            <div className="dyn-event-filters">
              {presentCategories.map((cat) => (
                <button
                  key={cat}
                  className={`dyn-chip tone-${cat} ${!hiddenCategories.has(cat) ? "active" : ""}`}
                  onClick={() => toggleCategory(cat)}
                >
                  {categoryLabel(cat)}
                </button>
              ))}
              <input
                className="search-input dyn-event-search"
                placeholder="Filter events…"
                value={eventQuery}
                onChange={(e) => setEventQuery(e.target.value)}
              />
            </div>

            <div className="dyn-event-list">
              {filteredEvents.length === 0 && <div className="empty-hint small">No events yet.</div>}
              {filteredEvents.map((e) => (
                <EventRow key={e.seq} event={e} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
