/**
 * App.jsx — 主要 Chat 介面
 *
 * 對話迴圈：
 *  1. 使用者輸入文字 → POST /api/chat {type:"message"}
 *  2. Agent 回覆文字 + 可能附帶 A2UI JSON
 *  3. 若有 A2UI JSON → 渲染 <A2UISurface> 互動表單
 *  4. 使用者操作表單 → 按 Button → POST /api/chat {type:"action"}
 *  5. Agent 回覆結果 → 回注對話上下文 → 繼續對答
 */

import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import A2UISurface from "./A2UIRenderer.jsx";

const SESSION_ID = "demo-" + Math.random().toString(36).slice(2, 10);

const WELCOME = {
  id: "welcome",
  role: "agent",
  content:
    "您好，我是 A2UI Demo Agent。\n\n" +
    "本系統示範在對話中動態彈出互動表單，操作完成後結果會回到對話上下文，持續進行交互。\n\n" +
    "可用指令：\n" +
    "  ・「訂位」— 餐廳訂位表單\n" +
    "  ・「意見回饋」— 滿意度調查\n" +
    "  ・「使用次數分析」— agent_sessions_QA1 圖表查詢\n" +
    "  ・「help」— 功能說明",
};

export default function App() {
  const [messages, setMessages] = useState([WELCOME]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  // 自動捲到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // ── API 呼叫（SSE streaming）────────────────────────────

  const sendChat = useCallback(async (payload) => {
    setLoading(true);
    const msgId = `${Date.now()}-agent`;

    // 立即新增佔位訊息（顯示 loading dots）
    setMessages((prev) => [
      ...prev,
      { id: msgId, role: "agent", content: "", ui: null, streaming: true },
    ]);

    try {
      // 走 Vite proxy（同源），避免跨域 streaming 瀏覽器限制
      const resp = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: SESSION_ID, ...payload }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          if (!part.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(part.slice(6));
            if (event.type === "token") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === msgId ? { ...m, content: m.content + event.content } : m
                )
              );
            } else if (event.type === "done") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === msgId
                    ? { ...m, ui: event.ui ?? null, streaming: false }
                    : m
                )
              );
            } else if (event.type === "error") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === msgId
                    ? { ...m, content: `錯誤：${event.message}`, streaming: false }
                    : m
                )
              );
            }
          } catch { /* ignore malformed JSON */ }
        }
      }

      // 確保 streaming 狀態結束
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId && m.streaming ? { ...m, streaming: false } : m
        )
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId
            ? {
                ...m,
                content: `連線失敗：${err.message}\n請確認後端是否在 port 8008 運行。`,
                streaming: false,
              }
            : m
        )
      );
    } finally {
      setLoading(false);
    }
  }, []);

  // ── 表單送出 ──────────────────────────────────────────

  const handleSubmit = (e) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    // 先把使用者訊息加入對話
    setMessages((prev) => [
      ...prev,
      { id: Date.now() + "-user", role: "user", content: text },
    ]);
    sendChat({ type: "message", content: text });
  };

  // ── A2UI Action Callback ──────────────────────────────
  // 使用者在 A2UI 表單按下 Button 後呼叫此函式

  const handleAction = useCallback(
    (actionName, actionData) => {
      // 先把表單摘要記入對話（讓使用者看到自己的輸入）
      const summary = Object.entries(actionData)
        .map(([k, v]) => `${k}: ${v}`)
        .join(" / ");
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + "-action",
          role: "user",
          content: `[表單提交] ${summary}`,
        },
      ]);
      sendChat({ type: "action", action_name: actionName, action_data: actionData });
    },
    [sendChat]
  );

  // ── 渲染 ──────────────────────────────────────────────

  return (
    <div className="app-shell">
      {/* Header */}
      <header className="app-header">
        <div className="app-header-logo">A2</div>
        <div className="app-header-text">
          <h1>A2UI Demo Agent</h1>
          <p>對話中彈出互動介面 · 操作結果回注上下文 · 持續交互</p>
        </div>
      </header>

      {/* Messages */}
      <div className="messages">
        {messages.map((msg) => (
          <MessageRow key={msg.id} msg={msg} onAction={handleAction} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form className="input-bar" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder='試試：「訂位」「意見回饋」「使用次數分析」'
          disabled={loading}
          autoComplete="off"
        />
        <button type="submit" disabled={loading || !input.trim()}>
          送出
        </button>
      </form>
    </div>
  );
}

// ── 訊息列 ───────────────────────────────────────────────

function MessageRow({ msg, onAction }) {
  const isStreaming = msg.streaming;
  const hasContent = msg.content?.length > 0;

  return (
    <div className={`msg-row ${msg.role}`}>
      <span className="msg-sender">{msg.role === "user" ? "You" : "Agent"}</span>
      {isStreaming && !hasContent ? (
        // 等待第一個 token：顯示 loading dots
        <div className="msg-loading">
          <span className="dot" />
          <span className="dot" />
          <span className="dot" />
        </div>
      ) : (
        <div className={`msg-bubble${isStreaming ? " streaming" : ""}`}>
          {msg.role === "agent" ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
          ) : (
            msg.content
          )}
        </div>
      )}
      {/* 若此訊息附帶 A2UI JSON，渲染互動表單 */}
      {msg.ui && <A2UISurface spec={msg.ui} onAction={onAction} />}
    </div>
  );
}

function LoadingRow() {
  return (
    <div className="msg-row agent">
      <span className="msg-sender">Agent</span>
      <div className="msg-loading">
        <span className="dot" />
        <span className="dot" />
        <span className="dot" />
      </div>
    </div>
  );
}
