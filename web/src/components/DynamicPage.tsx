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

const CATEGORIES = ["objc_call", "network", "keychain", "crypto", "lifecycle", "error"] as const;

const CATEGORY_LABEL: Record<string, string> = {
  objc_call: "ObjC call",
  network: "Network",
  keychain: "Keychain",
  crypto: "Crypto",
  lifecycle: "Lifecycle",
  error: "Error",
};

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
        <span className={`dyn-badge tone-${event.category}`}>{CATEGORY_LABEL[event.category] ?? event.category}</span>
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

  const [categoryFilter, setCategoryFilter] = useState<Set<string>>(new Set(CATEGORIES));
  const [eventQuery, setEventQuery] = useState("");

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

  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      if (!categoryFilter.has(e.category)) return false;
      if (eventQuery.trim() && !e.summary.toLowerCase().includes(eventQuery.toLowerCase())) return false;
      return true;
    });
  }, [events, categoryFilter, eventQuery]);

  function toggleClass(name: string) {
    setSelectedClasses((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function toggleCategory(cat: string) {
    setCategoryFilter((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
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
              {CATEGORIES.map((cat) => (
                <button
                  key={cat}
                  className={`dyn-chip tone-${cat} ${categoryFilter.has(cat) ? "active" : ""}`}
                  onClick={() => toggleCategory(cat)}
                >
                  {CATEGORY_LABEL[cat]}
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
