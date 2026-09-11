import { useEffect, useMemo, useState } from "react";
import { ClassChanged, ClassSummary, CompareResult, FileChanged, FileEntry, IPA, compareScans } from "../api";

function formatSize(bytes?: number | null): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDelta(a?: number | null, b?: number | null): string {
  if (a == null || b == null) return "";
  const delta = a - b;
  const sign = delta > 0 ? "+" : "";
  return `${sign}${formatDelta.bytes(delta)}`;
}
formatDelta.bytes = (n: number) => {
  const abs = Math.abs(n);
  if (abs < 1024) return `${n} B`;
  if (abs < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
};

function DiffColumn<T>({
  title,
  count,
  tone,
  items,
  filterText,
  renderRow,
}: {
  title: string;
  count: number;
  tone: "a" | "b" | "changed" | "neutral";
  items: T[];
  filterText: (item: T) => string;
  renderRow: (item: T) => React.ReactNode;
}) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    if (!query.trim()) return items;
    const q = query.toLowerCase();
    return items.filter((item) => filterText(item).toLowerCase().includes(q));
  }, [items, query, filterText]);

  return (
    <div className="diff-col">
      <div className={`diff-col-header tone-${tone}`}>
        <span>{title}</span>
        <span className="diff-count">{count}</span>
      </div>
      {items.length > 8 && (
        <input className="search-input diff-col-search" placeholder="Filter…" value={query} onChange={(e) => setQuery(e.target.value)} />
      )}
      <div className="diff-col-list">
        {filtered.length === 0 && <div className="empty-hint small">Nothing here.</div>}
        {filtered.map((item, i) => (
          <div key={i} className="diff-row">
            {renderRow(item)}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ComparePage({ ipas }: { ipas: IPA[] }) {
  const readyIpas = useMemo(() => ipas.filter((ipa) => ipa.status === "ready"), [ipas]);
  const [aId, setAId] = useState("");
  const [bId, setBId] = useState("");
  const [result, setResult] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!aId || !bId || aId === bId) {
      setResult(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    compareScans(aId, bId)
      .then((r) => {
        if (!cancelled) setResult(r);
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [aId, bId]);

  return (
    <div className="compare-page">
      <div className="compare-picker">
        <select className="compare-select" value={aId} onChange={(e) => setAId(e.target.value)}>
          <option value="">Scan A…</option>
          {readyIpas.map((ipa) => (
            <option key={ipa.id} value={ipa.id} disabled={ipa.id === bId}>
              {ipa.original_filename}
            </option>
          ))}
        </select>
        <span className="compare-vs">vs</span>
        <select className="compare-select" value={bId} onChange={(e) => setBId(e.target.value)}>
          <option value="">Scan B…</option>
          {readyIpas.map((ipa) => (
            <option key={ipa.id} value={ipa.id} disabled={ipa.id === aId}>
              {ipa.original_filename}
            </option>
          ))}
        </select>
      </div>

      {!aId || !bId ? (
        <div className="empty-hint">Pick two scans to compare.</div>
      ) : aId === bId ? (
        <div className="notice">Pick two different scans.</div>
      ) : loading ? (
        <div className="empty-hint">Comparing…</div>
      ) : error ? (
        <div className="error-text">{error}</div>
      ) : result ? (
        <div className="compare-results">
          <section className="compare-section">
            <h2>
              Files <span className="muted">· {result.files.common_total} identical or unchanged</span>
            </h2>
            <div className="diff-grid diff-grid-3">
              <DiffColumn
                title="Only in A"
                count={result.files.only_in_a_total}
                tone="a"
                items={result.files.only_in_a}
                filterText={(f: FileEntry) => f.path}
                renderRow={(f: FileEntry) => (
                  <>
                    <span className="diff-row-main mono">{f.path}</span>
                    {f.kind === "file" && <span className="diff-row-meta">{formatSize(f.size_bytes)}</span>}
                  </>
                )}
              />
              <DiffColumn
                title="Only in B"
                count={result.files.only_in_b_total}
                tone="b"
                items={result.files.only_in_b}
                filterText={(f: FileEntry) => f.path}
                renderRow={(f: FileEntry) => (
                  <>
                    <span className="diff-row-main mono">{f.path}</span>
                    {f.kind === "file" && <span className="diff-row-meta">{formatSize(f.size_bytes)}</span>}
                  </>
                )}
              />
              <DiffColumn
                title="Changed size"
                count={result.files.changed_total}
                tone="changed"
                items={result.files.changed}
                filterText={(f: FileChanged) => f.path}
                renderRow={(f: FileChanged) => (
                  <>
                    <span className="diff-row-main mono">{f.path}</span>
                    <span className="diff-row-meta">{formatDelta(f.size_a, f.size_b)}</span>
                  </>
                )}
              />
            </div>
          </section>

          <section className="compare-section">
            <h2>
              Classes <span className="muted">· {result.classes.common_total} shared</span>
            </h2>
            <div className="diff-grid diff-grid-3">
              <DiffColumn
                title="Only in A"
                count={result.classes.only_in_a_total}
                tone="a"
                items={result.classes.only_in_a}
                filterText={(c: ClassSummary) => c.name}
                renderRow={(c: ClassSummary) => (
                  <>
                    <span className="diff-row-main mono">{c.name}</span>
                    <span className="diff-row-meta">{c.superclass}</span>
                  </>
                )}
              />
              <DiffColumn
                title="Only in B"
                count={result.classes.only_in_b_total}
                tone="b"
                items={result.classes.only_in_b}
                filterText={(c: ClassSummary) => c.name}
                renderRow={(c: ClassSummary) => (
                  <>
                    <span className="diff-row-main mono">{c.name}</span>
                    <span className="diff-row-meta">{c.superclass}</span>
                  </>
                )}
              />
              <DiffColumn
                title="Changed"
                count={result.classes.changed_total}
                tone="changed"
                items={result.classes.changed}
                filterText={(c: ClassChanged) => c.name}
                renderRow={(c: ClassChanged) => (
                  <>
                    <span className="diff-row-main mono">{c.name}</span>
                    <span className="diff-row-meta">
                      {c.a.instance_method_count}→{c.b.instance_method_count} methods
                    </span>
                  </>
                )}
              />
            </div>
          </section>

          <section className="compare-section">
            <h2>
              Functions <span className="muted">· {result.functions.common_total} shared</span>
            </h2>
            <div className="diff-grid diff-grid-2">
              <DiffColumn
                title="Only in A"
                count={result.functions.only_in_a_total}
                tone="a"
                items={result.functions.only_in_a}
                filterText={(n: string) => n}
                renderRow={(n: string) => <span className="diff-row-main mono">{n}</span>}
              />
              <DiffColumn
                title="Only in B"
                count={result.functions.only_in_b_total}
                tone="b"
                items={result.functions.only_in_b}
                filterText={(n: string) => n}
                renderRow={(n: string) => <span className="diff-row-main mono">{n}</span>}
              />
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
