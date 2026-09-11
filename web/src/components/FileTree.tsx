import { useEffect, useMemo, useState } from "react";
import { FileTreeNode } from "../api";

export function flattenFiles(nodes: FileTreeNode[], into: FileTreeNode[] = []): FileTreeNode[] {
  for (const n of nodes) {
    into.push(n);
    if (n.kind === "dir") flattenFiles(n.children, into);
  }
  return into;
}

function formatSize(bytes?: number | null): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function iconFor(node: FileTreeNode, open = false): string {
  if (node.kind === "dir") {
    if (node.name.endsWith(".app")) return "📦";
    return open ? "📂" : "📁";
  }
  if (node.is_main_binary) return "⚙️";
  const ext = node.name.includes(".") ? node.name.slice(node.name.lastIndexOf(".")).toLowerCase() : "";
  if (ext === ".plist" || ext === ".entitlements") return "📋";
  if ([".png", ".jpg", ".jpeg", ".gif", ".bmp"].includes(ext)) return "🖼️";
  if ([".json", ".xml", ".strings", ".txt", ".md", ".yml", ".yaml"].includes(ext)) return "📝";
  if (ext === ".car") return "🎨";
  if (ext === ".mobileprovision") return "🔏";
  if (ext === ".nib" || ext === ".storyboardc") return "🧩";
  return "📄";
}

function collectInitialOpen(nodes: FileTreeNode[], depth: number, into: Set<string>) {
  if (depth >= 2) return;
  for (const n of nodes) {
    if (n.kind === "dir") {
      into.add(n.path);
      collectInitialOpen(n.children, depth + 1, into);
    }
  }
}

function ancestorPaths(path: string): string[] {
  const parts = path.split("/");
  const result: string[] = [];
  for (let i = 1; i < parts.length; i++) {
    result.push(parts.slice(0, i).join("/"));
  }
  return result;
}

function TreeNode({
  node,
  depth,
  onSelect,
  selectedPath,
  openPaths,
  onToggle,
}: {
  node: FileTreeNode;
  depth: number;
  onSelect: (node: FileTreeNode) => void;
  selectedPath: string | null;
  openPaths: Set<string>;
  onToggle: (path: string) => void;
}) {
  const isDir = node.kind === "dir";
  const open = openPaths.has(node.path);

  return (
    <div>
      <div
        className={`tree-row ${selectedPath === node.path ? "selected" : ""}`}
        data-path={node.path}
        style={{ paddingLeft: 8 + depth * 16 }}
        onClick={() => {
          if (isDir) onToggle(node.path);
          onSelect(node);
        }}
      >
        {isDir && <span className="tree-caret">{open ? "▾" : "▸"}</span>}
        <span className="tree-icon">{iconFor(node, open)}</span>
        <span className="tree-name">{node.name}</span>
        {!isDir && <span className="tree-size">{formatSize(node.size_bytes)}</span>}
      </div>
      {isDir && open && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              onSelect={onSelect}
              selectedPath={selectedPath}
              openPaths={openPaths}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function FileTree({
  nodes,
  onSelect,
  selectedPath,
}: {
  nodes: FileTreeNode[];
  onSelect: (node: FileTreeNode) => void;
  selectedPath: string | null;
}) {
  const [openPaths, setOpenPaths] = useState<Set<string>>(() => {
    const s = new Set<string>();
    collectInitialOpen(nodes, 0, s);
    return s;
  });
  const [query, setQuery] = useState("");

  const searchResults = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return null;
    return flattenFiles(nodes).filter(
      (n) => n.name.toLowerCase().includes(q) || n.path.toLowerCase().includes(q)
    );
  }, [nodes, query]);

  // Reveal the selected node (e.g. jumped to from search) by opening its ancestor dirs,
  // then scroll it into view.
  useEffect(() => {
    if (!selectedPath) return;
    setOpenPaths((prev) => {
      const ancestors = ancestorPaths(selectedPath);
      if (ancestors.every((p) => prev.has(p))) return prev;
      const next = new Set(prev);
      ancestors.forEach((p) => next.add(p));
      return next;
    });
    requestAnimationFrame(() => {
      const el = document.querySelector(`.file-tree [data-path="${CSS.escape(selectedPath)}"]`);
      el?.scrollIntoView({ block: "nearest" });
    });
  }, [selectedPath]);

  function onToggle(path: string) {
    setOpenPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  if (nodes.length === 0) {
    return <div className="empty-hint">No files yet.</div>;
  }

  return (
    <div className="file-tree-wrap">
      <input
        className="search-input"
        placeholder={`Filter files…`}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {searchResults ? (
        <div className="search-flat-list">
          {searchResults.length === 0 && <div className="empty-hint">No matches.</div>}
          {searchResults.map((n) => (
            <div
              key={n.path}
              className={`search-result-row ${selectedPath === n.path ? "selected" : ""}`}
              onClick={() => onSelect(n)}
            >
              <span className="tree-icon">{iconFor(n)}</span>
              <span className="search-result-name">{n.name}</span>
              <span className="search-result-sub">{n.path}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="file-tree">
          {nodes.map((n) => (
            <TreeNode
              key={n.path}
              node={n}
              depth={0}
              onSelect={onSelect}
              selectedPath={selectedPath}
              openPaths={openPaths}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}
    </div>
  );
}
