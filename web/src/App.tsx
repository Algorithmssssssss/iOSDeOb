import { useCallback, useEffect, useState } from "react";
import { IPA, listIpas } from "./api";
import NavRail, { type AppView } from "./components/NavRail";
import WorkbenchPage from "./components/WorkbenchPage";
import ComparePage from "./components/ComparePage";
import DynamicPage from "./components/DynamicPage";
import McpDocsPage from "./components/McpDocsPage";

const SECTION_TITLE: Record<AppView, string> = {
  workbench: "Workbench",
  compare: "Compare scans",
  dynamic: "Dynamic analysis",
  docs: "MCP documentation",
};

export default function App() {
  const [ipas, setIpas] = useState<IPA[]>([]);
  const [view, setView] = useState<AppView>("workbench");
  const [selectedIpaId, setSelectedIpaId] = useState<string | null>(null);

  const refreshIpas = useCallback(() => {
    listIpas().then(setIpas).catch(console.error);
  }, []);

  useEffect(() => {
    refreshIpas();
  }, [refreshIpas]);

  const selectedIpa = ipas.find((i) => i.id === selectedIpaId) ?? null;

  return (
    <div className="shell">
      <NavRail view={view} onChange={setView} />

      <div className="frame">
        <div className="topbar">
          {view === "workbench" && selectedIpa ? (
            <div className="breadcrumb">
              <span className="section">Workbench</span>
              <span className="sep">/</span>
              <span className="scan mono">{selectedIpa.original_filename}</span>
              <span className={`pill pill-${selectedIpa.status}`}>{selectedIpa.status}</span>
            </div>
          ) : (
            <div className="breadcrumb">
              <span className="section">{SECTION_TITLE[view]}</span>
            </div>
          )}
        </div>

        <div className="body">
          {view === "workbench" && (
            <WorkbenchPage
              ipas={ipas}
              selectedIpaId={selectedIpaId}
              onSelectIpa={setSelectedIpaId}
              onIpasChanged={refreshIpas}
            />
          )}
          {view === "compare" && <ComparePage ipas={ipas} />}
          {view === "dynamic" && <DynamicPage ipas={ipas} />}
          {view === "docs" && <McpDocsPage />}
        </div>
      </div>
    </div>
  );
}
