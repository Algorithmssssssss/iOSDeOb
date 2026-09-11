import { useMemo, useState } from "react";
import { FunctionEntry } from "../api";

export default function FunctionBrowser({
  functions,
  selectedAddress,
  onSelect,
}: {
  functions: FunctionEntry[];
  selectedAddress: number | null;
  onSelect: (fn: FunctionEntry) => void;
}) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    if (!query.trim()) return functions;
    const q = query.toLowerCase();
    return functions.filter((f) => f.name.toLowerCase().includes(q));
  }, [functions, query]);

  return (
    <div className="class-browser">
      <input
        className="search-input"
        placeholder={`Search ${functions.length} functions…`}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="class-list">
        {filtered.map((fn) => (
          <div
            key={fn.address}
            className={`class-row ${selectedAddress === fn.address ? "selected" : ""}`}
            onClick={() => onSelect(fn)}
          >
            <span className="class-icon">{fn.source === "objc_method" ? (fn.is_class_method ? "+" : "−") : "ƒ"}</span>
            <span className="class-name">{fn.name}</span>
          </div>
        ))}
        {filtered.length === 0 && <div className="empty-hint">No matches.</div>}
      </div>
    </div>
  );
}
