import { useMemo, useState } from "react";
import { ObjCClass } from "../api";

export default function ClassBrowser({
  classes,
  selected,
  onSelect,
}: {
  classes: ObjCClass[];
  selected: string | null;
  onSelect: (cls: ObjCClass) => void;
}) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    if (!query.trim()) return classes;
    const q = query.toLowerCase();
    return classes.filter((c) => c.name.toLowerCase().includes(q));
  }, [classes, query]);

  return (
    <div className="class-browser">
      <input
        className="search-input"
        placeholder={`Search ${classes.length} classes…`}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="class-list">
        {filtered.map((c) => (
          <div
            key={c.name}
            className={`class-row ${selected === c.name ? "selected" : ""}`}
            onClick={() => onSelect(c)}
          >
            <span className="class-icon">◆</span>
            <span className="class-name">{c.name}</span>
          </div>
        ))}
        {filtered.length === 0 && <div className="empty-hint">No matches.</div>}
      </div>
    </div>
  );
}
