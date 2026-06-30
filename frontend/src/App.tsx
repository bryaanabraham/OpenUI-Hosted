import "@openuidev/react-ui/components.css";
import "@openuidev/react-ui/styles/index.css";
import "./index.css";

import { Renderer } from "@openuidev/react-lang";
import { openuiLibrary } from "@openuidev/react-ui/genui-lib";
import { useRef, useState, useCallback, useEffect } from "react";

const API_BASE = "/api";

interface SessionSummary {
  session_id: string;
  label: string;
  message_count: number;
  has_cache: boolean;
  last_active: number;
}

function buildCode(layout: string, dataObj: Record<string, any>) {
  let code = "";
  // Data variables MUST be defined at the top before the layout uses them!
  for (const [key, val] of Object.entries(dataObj)) {
    code += `${key} = ${JSON.stringify(val)}\n`;
  }
  code += "\n" + layout;
  return "```openui-lang\n" + code.trim() + "\n```";
}

export default function App() {
  const sessionIdRef = useRef<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const [refreshMode, setRefreshMode] = useState<boolean>(false);
  const [hasCache, setHasCache] = useState<boolean>(false);
  const [hasDataset, setHasDataset] = useState<boolean>(false);
  
  const [openuiCode, setOpenuiCode] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [inputValue, setInputValue] = useState<string>("");
  
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true);

  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refreshSessionList = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/sessions`);
      if (res.ok) {
        setSessions(await res.json());
      }
    } catch (e) {
      console.error("Failed to fetch sessions:", e);
    }
  }, []);

  useEffect(() => {
    refreshSessionList();
  }, [refreshSessionList]);

  const loadSession = useCallback(async (sid: string) => {
    if (isStreaming) return;
    try {
      const res = await fetch(`${API_BASE}/sessions/${sid}`);
      if (!res.ok) return;
      const data = await res.json();

      sessionIdRef.current = sid;
      setSessionId(sid);

      setHasCache(data.has_cache);
      setHasDataset(data.has_dataset || false);
      setRefreshMode(false);

      if (data.cached_layout && data.cached_data) {
        setOpenuiCode(buildCode(data.cached_layout, data.cached_data));
      } else {
        setOpenuiCode(null);
      }

      setIsStreaming(false);
    } catch (e) {
      console.error("Failed to load session:", e);
    }
  }, [isStreaming]);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    setIsUploading(true);
    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
      formData.append("files", files[i]);
    }
    if (sessionIdRef.current) {
      formData.append("session_id", sessionIdRef.current);
    }

    try {
      const res = await fetch(`${API_BASE}/upload`, {
        method: "POST",
        body: formData
      });
      if (res.ok) {
        const data = await res.json();
        if (data.session_id && data.session_id !== sessionIdRef.current) {
          sessionIdRef.current = data.session_id;
          setSessionId(data.session_id);
        }
        setHasDataset(true);
        refreshSessionList();
        alert("Dataset loaded successfully! You can now ask the Data Analyst to build a dashboard.");
      } else {
        alert("Failed to upload dataset.");
      }
    } catch (err) {
      console.error(err);
      alert("Error uploading file.");
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleSubmit = useCallback(async () => {
    const message = inputValue.trim();
    if (!message || isStreaming) return;

    setInputValue("");
    setIsStreaming(true);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      let endpoint = "/generative_ui";
      if (refreshMode) {
        endpoint = "/agentic_ai";
      } else if (hasDataset) {
        endpoint = "/generate_from_data";
      }

      let response = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          session_id: sessionIdRef.current ?? undefined
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        if (response.status === 400 && endpoint === "/agentic_ai") {
          if (errorData.detail && errorData.detail.includes("Schema mismatch detected")) {
            alert(errorData.detail + " Automatically switching to Full Generation mode...");
            setRefreshMode(false);
            endpoint = "/generate_from_data";
            response = await fetch(`${API_BASE}${endpoint}`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                message,
                session_id: sessionIdRef.current ?? undefined
              }),
              signal: controller.signal,
            });
            if (!response.ok) throw new Error("Backend error during fallback");
          } else {
            setHasCache(false);
            setRefreshMode(false);
            alert("The backend server was restarted and lost your session cache.");
            throw new Error("Backend error");
          }
        } else {
          throw new Error("Backend error");
        }
      }

      const newSessionId = response.headers.get("X-Session-Id");
      if (newSessionId && newSessionId !== sessionIdRef.current) {
        sessionIdRef.current = newSessionId;
        setSessionId(newSessionId);
      }
      
      const data = await response.json();
      
      const layoutCode = data.layout_code || data.backend_Printed_layout_code;
      if (layoutCode && data.data_variables) {
        setOpenuiCode(buildCode(layoutCode, data.data_variables));
        if (!refreshMode) setHasCache(true);
      }

      setTimeout(() => refreshSessionList(), 1500);

    } catch (err: any) {
      if (err.name !== "AbortError") {
        console.error("❌ Fetch error:", err);
      }
    } finally {
      setIsStreaming(false);
    }
  }, [inputValue, isStreaming, refreshMode, hasDataset, refreshSessionList]);

  const handleNewChat = useCallback(() => {
    abortRef.current?.abort();
    sessionIdRef.current = null;
    setSessionId(null);
    setOpenuiCode(null);
    setHasCache(false);
    setHasDataset(false);
    setRefreshMode(false);
    setIsStreaming(false);
    setInputValue("");
  }, []);

  const handleDeleteSession = useCallback(async (sid: string, e: React.MouseEvent) => {
    e.stopPropagation();
    await fetch(`${API_BASE}/sessions/${sid}`, { method: "DELETE" }).catch(() => { });
    if (sessionIdRef.current === sid) handleNewChat();
    refreshSessionList();
  }, [handleNewChat, refreshSessionList]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div style={{ height: "100vh", width: "100vw", overflow: "hidden", display: "flex", flexDirection: "column" }}>
      {/* Top bar */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "8px 16px", background: "#fff", borderBottom: "1px solid #e5e5e5", flexShrink: 0,
        fontFamily: "system-ui, sans-serif",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            style={{
              background: "transparent", border: "none", color: "#888", cursor: "pointer", fontSize: 16, padding: "2px 6px"
            }}
          >
            {sidebarOpen ? "◁" : "▷"}
          </button>
          <span style={{ color: "#111", fontWeight: 700, fontSize: 14 }}>⚡ OpenUI API Tester (Stateful JSON)</span>
          {sessionId && (
            <span style={{
              color: "#666", fontSize: 11, background: "#f5f5f5", border: "1px solid #ddd", borderRadius: 4, padding: "2px 7px", fontFamily: "monospace"
            }}>
              session: {sessionId.slice(0, 8)}…
            </span>
          )}
          {hasCache && (
            <span style={{
              color: "#16a34a", fontSize: 11, background: "rgba(22, 163, 74, 0.08)",
              border: "1px solid rgba(22, 163, 74, 0.2)", borderRadius: 4, padding: "2px 7px", fontWeight: 600
            }}>
              ✓ Layout Cached
            </span>
          )}
          {hasDataset && (
            <span style={{
              color: "#2563eb", fontSize: 11, background: "rgba(37, 99, 235, 0.08)",
              border: "1px solid rgba(37, 99, 235, 0.2)", borderRadius: 4, padding: "2px 7px", fontWeight: 600
            }}>
              📊 Dataset Active
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={handleNewChat}
            style={{
              background: "#fff", border: "1px solid #d1d5db", borderRadius: 6, padding: "4px 12px",
              fontSize: 12, fontWeight: 500, color: "#374151", cursor: "pointer",
            }}
          >
            + New Dash
          </button>
        </div>
      </div>

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Sidebar */}
        {sidebarOpen && (
          <div style={{
            width: 260, background: "#fafafa", borderRight: "1px solid #e5e5e5", display: "flex", flexDirection: "column",
            flexShrink: 0, overflow: "hidden"
          }}>
            <div style={{ padding: "12px 16px", fontSize: 11, fontWeight: 600, color: "#888", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Backend Sessions
            </div>
            <div style={{ flex: 1, overflowY: "auto" }}>
              {sessions.length === 0 ? (
                <div style={{ padding: 16, color: "#aaa", fontSize: 13 }}>No active sessions.</div>
              ) : (
                sessions.map((s) => (
                  <div
                    key={s.session_id}
                    onClick={() => loadSession(s.session_id)}
                    style={{
                      padding: "10px 16px", cursor: "pointer", borderBottom: "1px solid #eee",
                      background: sessionId === s.session_id ? "#e0f2fe" : "transparent",
                      display: "flex", justifyContent: "space-between", alignItems: "center"
                    }}
                  >
                    <div style={{ display: "flex", flexDirection: "column", gap: 4, overflow: "hidden" }}>
                      <span style={{ fontSize: 13, color: sessionId === s.session_id ? "#0369a1" : "#333", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {s.label}
                      </span>
                      <span style={{ fontSize: 11, color: "#999" }}>
                        {s.message_count} msgs {s.has_cache && "• cached"}
                      </span>
                    </div>
                    <button
                      onClick={(e) => handleDeleteSession(s.session_id, e)}
                      style={{
                        background: "transparent", border: "none", color: "#f87171", cursor: "pointer",
                        padding: 4, fontSize: 14, opacity: 0.8
                      }}
                      title="Delete"
                    >
                      ×
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* Main Content Area */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>
          
          <div style={{ flex: 1, overflow: "auto", padding: "24px 32px" }}>
            {openuiCode ? (
              <Renderer response={openuiCode} library={openuiLibrary} isStreaming={isStreaming} />
            ) : (
              <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#aaa" }}>
                Enter a prompt below or upload a dataset to generate a dashboard.
              </div>
            )}
          </div>

          {/* Prompt Area */}
          <div style={{
            padding: "16px 32px", background: "#fff", borderTop: "1px solid #eee", flexShrink: 0, display: "flex", gap: 12, alignItems: "flex-end"
          }}>
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
              {hasCache && (
                <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "#4b5563", fontWeight: 500, cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={refreshMode}
                    onChange={(e) => setRefreshMode(e.target.checked)}
                    style={{ accentColor: "#2563eb", width: 14, height: 14 }}
                  />
                  Mode 2: Refresh Data Only (Preserve Layout)
                </label>
              )}
              
              <div style={{ position: "relative" }}>
                <textarea
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={hasDataset ? "Ask the Analyst what to build..." : (refreshMode ? "Ask for new data..." : "Describe a dashboard...")}
                  disabled={isStreaming}
                  style={{
                    width: "100%", height: 60, padding: "12px 14px", borderRadius: 8, border: "1px solid #d1d5db",
                    background: "#f9fafb", fontSize: 14, fontFamily: "inherit", resize: "none", outline: "none",
                  }}
                />
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input type="file" ref={fileInputRef} onChange={handleFileUpload} accept=".csv, .xlsx, .xls, .pdf, .docx, .txt" multiple style={{ display: "none" }} />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isUploading || isStreaming}
                  style={{
                    background: "#f3f4f6", border: "1px solid #d1d5db", borderRadius: 6, padding: "6px 12px",
                    fontSize: 12, fontWeight: 500, color: "#374151", cursor: "pointer", display: "flex", alignItems: "center", gap: 6
                  }}
                >
                  {isUploading ? "Uploading..." : "📎 Upload Dataset (.csv/.xlsx/.pdf/.docx)"}
                </button>
                <span style={{ fontSize: 11, color: "#888" }}>
                  Upload a dataset to instantly activate the AI Data Analyst.
                </span>
              </div>
            </div>

            <button
              onClick={handleSubmit}
              disabled={!inputValue.trim() || isStreaming || isUploading}
              style={{
                background: hasDataset ? "#2563eb" : "#111", color: "#fff", border: "none", borderRadius: 8, padding: "0 24px", height: 60,
                fontSize: 14, fontWeight: 600, cursor: (isStreaming || isUploading) ? "not-allowed" : "pointer", opacity: (!inputValue.trim() || isStreaming) ? 0.5 : 1,
                transition: "background 0.2s"
              }}
            >
              {isStreaming ? "Analyzing..." : (hasDataset ? "Analyze & Build" : "Generate")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
