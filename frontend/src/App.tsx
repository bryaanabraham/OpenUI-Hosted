import "@openuidev/react-ui/components.css";
import "@openuidev/react-ui/styles/index.css";
import "./index.css";

import { openAIMessageFormat, openAIReadableStreamAdapter } from "@openuidev/react-headless";
import { FullScreen } from "@openuidev/react-ui";
import { openuiLibrary } from "@openuidev/react-ui/genui-lib";
import { useRef, useState, useEffect } from "react";

// Vite proxy rewrites /api → http://localhost:8000
const API_BASE = "/api";

export default function App() {
  const sessionIdRef = useRef<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  useEffect(() => {
    console.log("⚡ OpenUI API Tester initialized");
  }, []);

  const handleNewChat = async () => {
    console.log("🆕 Starting new chat...");
    if (sessionIdRef.current) {
      await fetch(`${API_BASE}/sessions/${sessionIdRef.current}`, {
        method: "DELETE",
      }).catch(() => {});
    }
    sessionIdRef.current = null;
    setSessionId(null);
    window.location.reload();
  };

  return (
    <div style={{ height: "100vh", width: "100vw", overflow: "hidden", display: "flex", flexDirection: "column" }}>
      {/* Top bar */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "8px 16px",
        background: "#0f0f0f",
        borderBottom: "1px solid #2a2a2a",
        flexShrink: 0,
        fontFamily: "system-ui, sans-serif",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ color: "#fff", fontWeight: 700, fontSize: 14 }}>⚡ OpenUI API Tester</span>
          {sessionId && (
            <span style={{
              color: "#888",
              fontSize: 11,
              background: "#1a1a1a",
              border: "1px solid #333",
              borderRadius: 4,
              padding: "2px 7px",
              fontFamily: "monospace",
            }}>
              session: {sessionId.slice(0, 8)}…
            </span>
          )}
        </div>
        <button
          onClick={handleNewChat}
          style={{
            background: "transparent",
            border: "1px solid #333",
            borderRadius: 6,
            color: "#aaa",
            cursor: "pointer",
            fontSize: 12,
            padding: "4px 12px",
            transition: "all 0.15s",
          }}
        >
          + New Chat
        </button>
      </div>

      {/* OpenUI chat + renderer */}
      <div style={{ flex: 1, overflow: "hidden" }}>
        <FullScreen
          processMessage={async ({ messages, abortController }) => {
            console.log("📤 Sending message to backend...");
            
            const apiMessages = openAIMessageFormat.toApi(messages);
            const lastUser = [...apiMessages].reverse().find((m: any) => m.role === "user");
            const userMessage = typeof lastUser?.content === "string"
              ? lastUser.content
              : lastUser?.content?.[0]?.text ?? "";

            try {
              const response = await fetch(`${API_BASE}/generate/stream/compat`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  message: userMessage,
                  session_id: sessionIdRef.current ?? undefined,
                }),
                signal: abortController.signal,
              });

              if (!response.ok) {
                const errorText = await response.text();
                console.error("❌ Backend error:", errorText);
                throw new Error(`Backend returned ${response.status}: ${errorText}`);
              }

              console.log("📥 Stream started");

              // Capture session ID from the response header
              const newSessionId = response.headers.get("X-Session-Id");
              if (newSessionId && newSessionId !== sessionIdRef.current) {
                console.log("🔑 New Session ID:", newSessionId);
                sessionIdRef.current = newSessionId;
                setSessionId(newSessionId);
              }

              return response;
            } catch (err) {
              console.error("❌ Fetch error:", err);
              throw err;
            }
          }}
          streamProtocol={openAIReadableStreamAdapter()}
          componentLibrary={openuiLibrary}
          agentName="OpenUI API Tester"
        />
      </div>
    </div>
  );
}
