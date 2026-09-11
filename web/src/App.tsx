import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import {
  DisasmResult,
  FilePreview,
  FileTreeNode,
  FunctionEntry,
  IPA,
  Job,
  ObjCClass,
  PlistEntry,
  deleteIpa,
  fileDownloadUrl,
  getClasses,
  getDisasm,
  getFilePreview,
  getFunctions,
  getJob,
  getPlists,
  getTree,
  jobSocketUrl,
  listIpas,
  listJobs,
  requestDisasm,
} from "./api";
import UploadForm from "./components/UploadForm";
import FileTree from "./components/FileTree";
import PlistViewer from "./components/PlistViewer";
import FileViewer from "./components/FileViewer";
import ClassBrowser from "./components/ClassBrowser";
import ClassHeaderView from "./components/ClassHeaderView";
import GlobalSearch from "./components/GlobalSearch";
import FunctionBrowser from "./components/FunctionBrowser";
import DisassemblyView from "./components/DisassemblyView";
import McpDocsPage from "./components/McpDocsPage";
import ComparePage from "./components/ComparePage";
import DynamicPage from "./components/DynamicPage";

type WorkspaceTab = "files" | "classes" | "functions" | "dynamic";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function App() {
  const [ipas, setIpas] = useState<IPA[]>([]);
  const [selectedIpaId, setSelectedIpaId] = useState<string | null>(null);
  const [selectedIpa, setSelectedIpa] = useState<IPA | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [tree, setTree] = useState<FileTreeNode[]>([]);
  const [plists, setPlists] = useState<PlistEntry[]>([]);
  const [selectedNode, setSelectedNode] = useState<FileTreeNode | null>(null);
  const [filePreview, setFilePreview] = useState<FilePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [tab, setTab] = useState<WorkspaceTab>("files");
  const [classes, setClasses] = useState<ObjCClass[]>([]);
  const [classWarnings, setClassWarnings] = useState<string[]>([]);
  const [selectedClass, setSelectedClass] = useState<ObjCClass | null>(null);
  const [functions, setFunctions] = useState<FunctionEntry[]>([]);
  const [selectedFunctionAddress, setSelectedFunctionAddress] = useState<number | null>(null);
  const [disasmResult, setDisasmResult] = useState<DisasmResult | null>(null);
  const [disasmLoading, setDisasmLoading] = useState(false);
  const [disasmError, setDisasmError] = useState<string | null>(null);
  const [showDocs, setShowDocs] = useState(false);
  const [showCompare, setShowCompare] = useState(false);
  const [disasmProgress, setDisasmProgress] = useState<Job | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const disasmWsRef = useRef<WebSocket | null>(null);

  const refreshIpas = useCallback(() => {
    listIpas().then(setIpas).catch(console.error);
  }, []);

  useEffect(() => {
    refreshIpas();
  }, [refreshIpas]);

  const loadResults = useCallback((ipaId: string) => {
    getTree(ipaId).then(setTree).catch(console.error);
    getPlists(ipaId).then(setPlists).catch(console.error);
    getClasses(ipaId)
      .then((r) => {
        setClasses(r.classes);
        setClassWarnings(r.warnings);
      })
      .catch(console.error);
    getFunctions(ipaId).then(setFunctions).catch(console.error);
  }, []);

  useEffect(() => {
    if (!selectedIpaId) return;
    setTree([]);
    setPlists([]);
    setSelectedNode(null);
    setFilePreview(null);
    setClasses([]);
    setClassWarnings([]);
    setSelectedClass(null);
    setFunctions([]);
    setSelectedFunctionAddress(null);
    setDisasmResult(null);
    setDisasmError(null);
    disasmWsRef.current?.close();
    setTab("files");

    let cancelled = false;

    async function init() {
      const ipa = ipas.find((i) => i.id === selectedIpaId) ?? null;
      setSelectedIpa(ipa);

      if (ipa?.status === "ready") {
        loadResults(selectedIpaId);
        return;
      }

      const jobs = await listJobs(selectedIpaId);
      const latest = jobs[jobs.length - 1];
      if (!latest || cancelled) return;
      setJob(latest);

      if (latest.status === "done") {
        loadResults(selectedIpaId);
        return;
      }

      const ws = new WebSocket(jobSocketUrl(latest.id));
      wsRef.current = ws;
      ws.onmessage = (evt) => {
        const payload = JSON.parse(evt.data);
        setJob((prev) => (prev ? { ...prev, ...payload } : prev));
        if (payload.status === "done") {
          loadResults(selectedIpaId);
          refreshIpas();
          ws.close();
        } else if (payload.status === "failed") {
          refreshIpas();
          ws.close();
        }
      };
      ws.onerror = () => {
        const poll = setInterval(async () => {
          const j = await getJob(latest.id);
          setJob(j);
          if (j.status === "done" || j.status === "failed") {
            clearInterval(poll);
            loadResults(selectedIpaId);
            refreshIpas();
          }
        }, 2000);
      };
    }

    init();

    return () => {
      cancelled = true;
      wsRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIpaId]);

  const infoPlist = plists.find((p) => p.kind === "info");
  const entitlements = plists.find((p) => p.kind === "entitlements");
  const selectedKnownPlist = selectedNode && plists.find((p) => p.node_path === selectedNode.path);

  useEffect(() => {
    setFilePreview(null);
    setPreviewError(null);
    if (!selectedIpaId || !selectedNode || selectedNode.kind !== "file" || selectedKnownPlist) {
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    getFilePreview(selectedIpaId, selectedNode.path)
      .then((preview) => {
        if (!cancelled) setFilePreview(preview);
      })
      .catch((e) => {
        if (!cancelled) setPreviewError((e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIpaId, selectedNode, selectedKnownPlist]);

  useEffect(() => {
    disasmWsRef.current?.close();
    setDisasmResult(null);
    setDisasmError(null);
    setDisasmProgress(null);
    if (!selectedIpaId || selectedFunctionAddress == null) return;

    let cancelled = false;
    setDisasmLoading(true);

    async function run() {
      try {
        const resp = await requestDisasm(selectedIpaId!, selectedFunctionAddress!);
        if (cancelled) return;

        if (resp.cached && resp.result) {
          setDisasmResult(resp.result);
          setDisasmLoading(false);
          return;
        }

        if (!resp.job_id) {
          setDisasmError("Disassembly request did not return a job.");
          setDisasmLoading(false);
          return;
        }

        const finish = async () => {
          try {
            const result = await getDisasm(selectedIpaId!, selectedFunctionAddress!);
            if (!cancelled) setDisasmResult(result);
          } catch (e) {
            if (!cancelled) setDisasmError((e as Error).message);
          } finally {
            if (!cancelled) setDisasmLoading(false);
          }
        };

        const ws = new WebSocket(jobSocketUrl(resp.job_id));
        disasmWsRef.current = ws;
        ws.onmessage = (evt) => {
          const payload = JSON.parse(evt.data);
          setDisasmProgress((prev) => (prev ? { ...prev, ...payload } : payload));
          if (payload.status === "done") {
            ws.close();
            finish();
          } else if (payload.status === "failed") {
            ws.close();
            if (!cancelled) {
              setDisasmError(payload.message || "Disassembly failed.");
              setDisasmLoading(false);
            }
          }
        };
        ws.onerror = () => {
          const poll = setInterval(async () => {
            const j = await getJob(resp.job_id!);
            setDisasmProgress(j);
            if (j.status === "done") {
              clearInterval(poll);
              finish();
            } else if (j.status === "failed") {
              clearInterval(poll);
              if (!cancelled) {
                setDisasmError(j.error_message || "Disassembly failed.");
                setDisasmLoading(false);
              }
            }
          }, 1500);
        };
      } catch (e) {
        if (!cancelled) {
          setDisasmError((e as Error).message);
          setDisasmLoading(false);
        }
      }
    }

    run();

    return () => {
      cancelled = true;
    };
  }, [selectedIpaId, selectedFunctionAddress]);

  function jumpToAddress(address: number) {
    setTab("functions");
    setSelectedFunctionAddress(address);
  }

  async function handleDeleteIpa(ipa: IPA, e: MouseEvent) {
    e.stopPropagation();
    if (!window.confirm(`Delete "${ipa.original_filename}" and all of its analysis data? This can't be undone.`)) {
      return;
    }
    try {
      await deleteIpa(ipa.id);
      if (selectedIpaId === ipa.id) {
        setSelectedIpaId(null);
        setSelectedIpa(null);
      }
      refreshIpas();
    } catch (e) {
      window.alert(`Failed to delete: ${(e as Error).message}`);
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header-title">
          <span className="app-logo">🔎</span>
          <div>
            <div className="app-title">iOSDeOb</div>
            <div className="app-subtitle">IPA static analysis workbench</div>
          </div>
        </div>
        {!showDocs && !showCompare && selectedIpa?.status === "ready" && (
          <GlobalSearch
            tree={tree}
            classes={classes}
            onSelectFile={(node) => {
              setTab("files");
              setSelectedNode(node);
            }}
            onSelectClass={(cls) => {
              setTab("classes");
              setSelectedClass(cls);
            }}
          />
        )}

        {!showDocs && (
          <button
            className="btn btn-secondary"
            onClick={() => {
              setShowCompare((v) => !v);
              setShowDocs(false);
            }}
          >
            {showCompare ? "← Back to workbench" : "⚖️ Compare scans"}
          </button>
        )}

        <button
          className="btn btn-secondary"
          onClick={() => {
            setShowDocs((v) => !v);
            setShowCompare(false);
          }}
        >
          {showDocs ? "← Back to workbench" : "🔌 MCP setup"}
        </button>

        <div className="app-header-phase">Phase 1–3 · Files, classes &amp; disassembly</div>
      </header>

      <div className="app-body">
        <aside className="sidebar">
          <UploadForm
            onUploaded={(ipa) => {
              refreshIpas();
              setSelectedIpaId(ipa.id);
            }}
          />
          <div className="ipa-list">
            {ipas.map((ipa) => (
              <div
                key={ipa.id}
                className={`ipa-row ${selectedIpaId === ipa.id ? "selected" : ""}`}
                onClick={() => setSelectedIpaId(ipa.id)}
              >
                <div className="ipa-row-main">
                  <div className="ipa-name" title={ipa.original_filename}>
                    {ipa.original_filename}
                  </div>
                  <div className="ipa-sub">{formatSize(ipa.size_bytes)}</div>
                </div>
                <span className={`pill pill-${ipa.status}`}>{ipa.status}</span>
                <button
                  className="ipa-delete-btn"
                  title="Delete this scan"
                  onClick={(e) => handleDeleteIpa(ipa, e)}
                >
                  🗑
                </button>
              </div>
            ))}
          </div>
        </aside>

        <main className="main">
          {showDocs && <McpDocsPage />}

          {showCompare && !showDocs && <ComparePage ipas={ipas} />}

          {!showDocs && !showCompare && !selectedIpaId && (
            <div className="empty-state">
              <div className="empty-state-icon">📦</div>
              <div>Upload an .ipa to get started.</div>
            </div>
          )}

          {!showDocs && !showCompare && selectedIpaId && selectedIpa?.status !== "ready" && (
            <div className="job-status">
              <div className="job-status-label">
                Status: <span className={`pill pill-${selectedIpa?.status ?? job?.status}`}>{selectedIpa?.status ?? job?.status}</span>
              </div>
              {job && (
                <>
                  <div className="progress-bar-outer">
                    <div className="progress-bar-inner" style={{ width: `${job.progress_pct}%` }} />
                  </div>
                  <div className="job-message">{job.message}</div>
                  {job.error_message && <div className="error-text">{job.error_message}</div>}
                </>
              )}
            </div>
          )}

          {!showDocs && !showCompare && selectedIpaId && selectedIpa?.status === "ready" && (
            <>
              <div className="tab-bar">
                <button className={`tab-btn ${tab === "files" ? "active" : ""}`} onClick={() => setTab("files")}>
                  Files
                </button>
                <button className={`tab-btn ${tab === "classes" ? "active" : ""}`} onClick={() => setTab("classes")}>
                  Classes {classes.length > 0 && <span className="tab-count">{classes.length}</span>}
                </button>
                <button className={`tab-btn ${tab === "functions" ? "active" : ""}`} onClick={() => setTab("functions")}>
                  Functions {functions.length > 0 && <span className="tab-count">{functions.length}</span>}
                </button>
                <button className={`tab-btn ${tab === "dynamic" ? "active" : ""}`} onClick={() => setTab("dynamic")}>
                  🧬 Dynamic
                </button>
              </div>

              {tab === "files" && (
                <div className="workspace">
                  <div className="tree-panel">
                    <div className="panel-heading">Bundle contents</div>
                    <FileTree nodes={tree} onSelect={setSelectedNode} selectedPath={selectedNode?.path ?? null} />
                  </div>
                  <div className="detail-panel">
                    {!selectedNode && infoPlist && <PlistViewer title="Info.plist" data={infoPlist.parsed} />}
                    {!selectedNode && !infoPlist && (
                      <div className="empty-hint">Select a file in the tree to inspect it.</div>
                    )}
                    {!selectedNode && entitlements && (
                      <PlistViewer title="Entitlements" data={entitlements.parsed} />
                    )}

                    {selectedNode && selectedKnownPlist && (
                      <PlistViewer
                        title={`${selectedKnownPlist.kind} · ${selectedNode.name}`}
                        data={selectedKnownPlist.parsed}
                      />
                    )}

                    {selectedNode && !selectedKnownPlist && selectedNode.kind === "dir" && (
                      <div className="file-detail">
                        <h3>{selectedNode.name}</h3>
                        <div className="muted">Directory · {selectedNode.children.length} item(s)</div>
                      </div>
                    )}

                    {selectedNode && !selectedKnownPlist && selectedNode.kind === "file" && (
                      <>
                        {previewLoading && <div className="empty-hint">Loading…</div>}
                        {previewError && <div className="error-text">{previewError}</div>}
                        {filePreview && (
                          <FileViewer
                            title={selectedNode.name}
                            preview={filePreview}
                            downloadUrl={fileDownloadUrl(selectedIpaId, selectedNode.path)}
                          />
                        )}
                        {selectedNode.is_main_binary && (
                          <div className="badge badge-clickable" onClick={() => setTab("functions")}>
                            Main executable — browse its functions →
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
              )}

              {tab === "classes" && (
                <div className="workspace">
                  <div className="tree-panel">
                    <ClassBrowser classes={classes} selected={selectedClass?.name ?? null} onSelect={setSelectedClass} />
                  </div>
                  <div className="detail-panel">
                    {classWarnings.length > 0 && (
                      <div className="notice">{classWarnings.join(" ")}</div>
                    )}
                    {selectedClass ? (
                      <ClassHeaderView cls={selectedClass} onJumpToAddress={jumpToAddress} />
                    ) : (
                      <div className="empty-hint">
                        {classes.length === 0
                          ? "No Objective-C classes found (Swift-only binary, or a binary this parser couldn't read)."
                          : "Select a class to view its interface."}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {tab === "functions" && (
                <div className="workspace">
                  <div className="tree-panel">
                    <FunctionBrowser
                      functions={functions}
                      selectedAddress={selectedFunctionAddress}
                      onSelect={(fn) => setSelectedFunctionAddress(fn.address)}
                    />
                  </div>
                  <div className="detail-panel">
                    {selectedFunctionAddress == null && (
                      <div className="empty-hint">Select a function to disassemble it.</div>
                    )}
                    {selectedFunctionAddress != null && disasmLoading && (
                      <div className="job-status">
                        <div className="job-status-label">Disassembling…</div>
                        {disasmProgress && (
                          <div className="progress-bar-outer">
                            <div className="progress-bar-inner" style={{ width: `${disasmProgress.progress_pct}%` }} />
                          </div>
                        )}
                      </div>
                    )}
                    {disasmError && <div className="error-text">{disasmError}</div>}
                    {disasmResult && !disasmLoading && (
                      <DisassemblyView result={disasmResult} onJumpTo={jumpToAddress} />
                    )}
                  </div>
                </div>
              )}

              {tab === "dynamic" && selectedIpaId && (
                <DynamicPage
                  ipaId={selectedIpaId}
                  classes={classes}
                  bundleIdGuess={
                    (infoPlist?.parsed as { CFBundleIdentifier?: string } | undefined)?.CFBundleIdentifier ?? null
                  }
                />
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
