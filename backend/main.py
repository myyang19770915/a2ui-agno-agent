"""
A2UI Demo Backend Server (port 8008)
====================================
展示 A2UI (Agent-to-User Interface) 協議的完整對話迴圈：

  使用者對話 → Agent 回傳 A2UI JSON → 前端渲染互動元件
  → 使用者操作表單 → Action callback 回傳 → 結果注入對話上下文
  → 繼續對答

API:
  POST /api/chat  - 發送訊息或 action callback
  GET  /api/sessions/{id} - 取得對話歷史
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Any
import json
import logging
import time
import uvicorn

from agent import DemoAgent

log = logging.getLogger("a2ui.api")

app = FastAPI(title="A2UI Demo Agent", version="0.1.0")

@app.middleware("http")
async def log_request_time(request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    dt = (time.perf_counter() - t0) * 1000
    log.info("[API] %-6s %-25s  → %d  (%.1f ms)",
             request.method, request.url.path, response.status_code, dt)
    return response

# 允許前端 dev server 跨域（localhost 任意 port）
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = DemoAgent()


# ── Request / Response Models ──────────────────────────────

class ChatRequest(BaseModel):
    session_id: str
    type: str                              # "message" | "action"
    content: Optional[str] = None          # 使用者文字訊息
    action_name: Optional[str] = None      # UI button action name
    action_data: Optional[dict[str, Any]] = None  # 表單綁定資料

class ChatResponse(BaseModel):
    session_id: str
    reply: str                             # Agent 文字回覆
    ui: Optional[dict[str, Any]] = None    # A2UI component JSON (可為 null)
    conversation: list[dict[str, Any]]     # 完整對話歷史


# ── Routes ─────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """
    核心端點：處理兩種請求
    1. type="message" → 使用者送出文字，Agent 判斷是否回傳 UI
    2. type="action"  → 使用者提交表單，Agent 處理並回覆結果
    """
    if req.type == "action" and req.action_name:
        result = await agent.handle_action(req.session_id, req.action_name, req.action_data or {})
    else:
        result = await agent.handle_message(req.session_id, req.content or "")

    return ChatResponse(
        session_id=req.session_id,
        reply=result["reply"],
        ui=result.get("ui"),
        conversation=agent.get_conversation(req.session_id),
    )


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE streaming 端點 — LLM token 逐筆輸出給前端。"""

    # 使用 sync generator（非 async）：Starlette 會自動透過
    # iterate_in_threadpool() 在 thread pool 中執行 next()，
    # 讓 event loop 在每個 token 之間都能 flush I/O，
    # 避免 Windows ProactorEventLoop 上 write 堆積的問題。
    def event_gen():
        try:
            if req.type == "action" and req.action_name:
                gen = agent.stream_action(
                    req.session_id, req.action_name, req.action_data or {}
                )
            else:
                gen = agent.stream_message(req.session_id, req.content or "")

            for evt_type, evt_data in gen:
                if evt_type == "token":
                    yield f"data: {json.dumps({'type': 'token', 'content': evt_data}, ensure_ascii=False)}\n\n"
                elif evt_type == "done":
                    yield f"data: {json.dumps({'type': 'done', 'ui': evt_data}, ensure_ascii=False)}\n\n"
                elif evt_type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': evt_data}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """取得完整對話歷史（前端重新載入時使用）"""
    return {"conversation": agent.get_conversation(session_id)}


# ── Entry Point ────────────────────────────────────────────

if __name__ == "__main__":
    print("🚀 A2UI Demo Backend running on http://localhost:8008")
    uvicorn.run(app, host="0.0.0.0", port=8008)
