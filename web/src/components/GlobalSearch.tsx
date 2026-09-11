import { useEffect, useMemo, useRef, useState } from "react";
import { FileTreeNode, ObjCClass, ObjCMethod } from "../api";
import { flattenFiles, iconFor } from "./FileTree";

interface MethodEntry {
  cls: ObjCClass;
  method: ObjCMethod;
  isClassMethod: boolean;
}

// High enough that scrolling the (already-scrollable) results panel gets you to
// everything in practice; only an extremely broad query would ever hit this.
const MAX_PER_GROUP = 200;

export default function GlobalSearch({
  tree,
  classes,
  onSelectFile,
  onSelectClass,
}: {
  tree: FileTreeNode[];
  classes: ObjCClass[];
  onSelectFile: (node: FileTreeNode) => void;
  onSelectClass: (cls: ObjCClass) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const allFiles = useMemo(() => flattenFiles(tree), [tree]);
  const allMethods = useMemo<MethodEntry[]>(() => {
    const entries: MethodEntry[] = [];
    for (const cls of classes) {
      for (const method of cls.instance_methods) entries.push({ cls, method, isClassMethod: false });
      for (const method of cls.class_methods) entries.push({ cls, method, isClassMethod: true });
    }
    return entries;
  }, [classes]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return null;
    const files = allFiles.filter((n) => n.name.toLowerCase().includes(q) || n.path.toLowerCase().includes(q));
    const matchedClasses = classes.filter((c) => c.name.toLowerCase().includes(q));
    const methods = allMethods.filter((e) => e.method.selector.toLowerCase().includes(q));
    return { files, classes: matchedClasses, methods };
  }, [query, allFiles, classes, allMethods]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      } else if (e.key === "Escape") {
        setOpen(false);
        inputRef.current?.blur();
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  function pickFile(node: FileTreeNode) {
    onSelectFile(node);
    setOpen(false);
    setQuery("");
  }

  function pickClass(cls: ObjCClass) {
    onSelectClass(cls);
    setOpen(false);
    setQuery("");
  }

  const totalResults = results ? results.files.length + results.classes.length + results.methods.length : 0;

  return (
    <div className="global-search" ref={containerRef}>
      <input
        ref={inputRef}
        className="global-search-input"
        placeholder="Search files, classes, methods…  (⌘K)"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
      />
      {open && results && (
        <div className="global-search-results">
          {totalResults === 0 && <div className="search-empty">No matches for "{query}"</div>}

          {results.files.length > 0 && (
            <div className="search-group">
              <div className="search-group-label">Files</div>
              {results.files.slice(0, MAX_PER_GROUP).map((node) => (
                <div key={node.path} className="search-result-row" onClick={() => pickFile(node)}>
                  <span className="tree-icon">{iconFor(node)}</span>
                  <span className="search-result-name">{node.name}</span>
                  <span className="search-result-sub">{node.path}</span>
                </div>
              ))}
              {results.files.length > MAX_PER_GROUP && (
                <div className="search-more">
                  +{results.files.length - MAX_PER_GROUP} more — refine your search
                </div>
              )}
            </div>
          )}

          {results.classes.length > 0 && (
            <div className="search-group">
              <div className="search-group-label">Classes</div>
              {results.classes.slice(0, MAX_PER_GROUP).map((cls) => (
                <div key={cls.name} className="search-result-row" onClick={() => pickClass(cls)}>
                  <span className="class-icon">◆</span>
                  <span className="search-result-name mono">{cls.name}</span>
                  {cls.superclass && <span className="search-result-sub">: {cls.superclass}</span>}
                </div>
              ))}
              {results.classes.length > MAX_PER_GROUP && (
                <div className="search-more">
                  +{results.classes.length - MAX_PER_GROUP} more — refine your search
                </div>
              )}
            </div>
          )}

          {results.methods.length > 0 && (
            <div className="search-group">
              <div className="search-group-label">Methods</div>
              {results.methods.slice(0, MAX_PER_GROUP).map((entry, i) => (
                <div key={i} className="search-result-row" onClick={() => pickClass(entry.cls)}>
                  <span className="class-icon">{entry.isClassMethod ? "+" : "−"}</span>
                  <span className="search-result-name mono">{entry.method.selector}</span>
                  <span className="search-result-sub">{entry.cls.name}</span>
                </div>
              ))}
              {results.methods.length > MAX_PER_GROUP && (
                <div className="search-more">
                  +{results.methods.length - MAX_PER_GROUP} more — refine your search
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
