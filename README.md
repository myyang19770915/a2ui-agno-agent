# a2ui-agno-agent

> **A2UI Demo** — 以 agno + LiteLLM + FastAPI + React 實現「對話中彈出互動 UI」的完整範例，支援 SSE 流式輸出。

## 專案概述

**A2UI (Agent-to-User Interface)** 協議的核心概念：

```
使用者對話 → Agent LLM 回覆（SSE streaming）+ 可選 A2UI JSON
→ 前端渲染互動表單 → 使用者操作
→ 表單資料透過 action callback 回傳 → 結果注入對話上下文
→ 繼續對答交互
```

### 技術棧

| 層 | 技術 |
|---|---|
| LLM | agno v2.5.17 + LiteLLMOpenAI（可接任何 OpenAI-compatible 後端） |
| Backend | FastAPI + uvicorn，port 8008 |
| Streaming | SSE（Server-Sent Events），sync generator → Starlette iterate_in_threadpool |
| Database | PostgreSQL（psycopg3），保存對話歷史 |
| Frontend | React 18 + Vite，port 3004 |
| Markdown | react-markdown + remark-gfm |

---

## 專案結構

```
a2ui-demo/
├── backend/
│   ├── pyproject.toml      # uv 專案定義
│   ├── main.py             # FastAPI server + SSE streaming 端點
│   ├── agent.py            # agno Agent 對話邏輯 + streaming generator
│   └── a2ui_builder.py     # A2UI JSON component builder
│
├── frontend/
│   ├── package.json
│   ├── vite.config.js      # Vite config + API proxy → localhost:8008
│   ├── index.html
│   └── src/
│       ├── App.jsx         # 主 Chat UI + SSE ReadableStream 消費
│       ├── A2UIRenderer.jsx# A2UI JSON → React 元件渲染引擎
│       ├── main.jsx
│       └── styles.css      # streaming cursor 動畫 + Markdown 樣式
│
└── README.md
```

---

## 安裝與啟動

### 前置需求

- Python 3.11+
- Node.js 18+
- [uv](https://docs.astral.sh/uv/)（Python 套件管理器）
- PostgreSQL（可選，停用則不保存歷史）
- LiteLLM Proxy 或任何 OpenAI-compatible API（預設 `http://localhost:4001/v1`）

### 步驟 1：設定 Backend

```bash
cd backend

# 建立虛擬環境並安裝依賴（uv 自動讀取 pyproject.toml）
uv venv
uv pip install -e .
```

**編輯 `backend/agent.py` 設定 LLM 與資料庫：**

```python
# 依實際環境修改
model = LiteLLMOpenAI(
    id="your-model-id",           # 例如 "qwen35-27b"
    api_key="sk-1234",
    base_url="http://localhost:4001/v1",  # LiteLLM Proxy 位址
    max_tokens=512,
)

# PostgreSQL 連線（必須用 127.0.0.1，不能用 localhost）
db = PostgresDb(
    db_url="postgresql+psycopg://user:pass@127.0.0.1:5432/postgres"
)
# 若不需要保存歷史，可停用資料庫：
# db = None
# USE_DATABASE = False
```

### 步驟 2：啟動 Backend

```bash
# Windows (PowerShell)
cd d:\code\a2ui-demo\backend
.venv\Scripts\Activate.ps1
python main.py

# macOS / Linux
cd backend
source .venv/bin/activate
python main.py
```

看到 `🚀 A2UI Demo Backend running on http://localhost:8008` 即成功。

### 步驟 3：啟動 Frontend

```bash
cd frontend
npm install
npm run dev
```

### 步驟 4：開始使用

瀏覽器打開 **http://localhost:3004**，試試：

- 輸入 `你好` → 看到 LLM streaming 逐字輸出
- 輸入 `訂位` → 彈出餐廳訂位互動表單
- 填寫表單 → 點「確認訂位」→ 確認結果回到對話中
- 輸入 `意見回饋` → 彈出滿意度調查表單

---

## 解決的關鍵問題

### 問題一：SSE Streaming 在前端沒有逐字效果

**症狀**：httpx 測試後端 streaming 正常（token 間隔 ~30ms），但瀏覽器中文字仍一次性全部顯示。

**根本原因**：`event_gen()` 使用 `async def`（async generator）+ 阻塞式 `for` 迴圈。在 Windows `ProactorEventLoop` 中，sync `for` 阻塞了 event loop，所有 `transport.write()` 呼叫堆積在 IOCP 佇列，等 generator 結束才一次性 flush。

**解法**：將 `event_gen()` 改為 **sync generator**（`def` 而非 `async def`）。Starlette 的 `StreamingResponse` 偵測到 sync generator 後，自動透過 `iterate_in_threadpool()` 在 thread pool 中執行 `next()`，讓 event loop 在每個 token 之間都能處理 I/O flush。

```python
# ❌ 錯誤：async generator + sync for 阻塞 event loop（Windows 上全部堆積）
async def event_gen():
    for evt_type, evt_data in sync_generator():
        yield f"data: ...\n\n"

# ✅ 正確：sync generator，Starlette 自動用 iterate_in_threadpool
def event_gen():
    for evt_type, evt_data in sync_generator():
        yield f"data: ...\n\n"
```

### 問題二：agno streaming 使用 asyncio.Queue + Thread 導致 token 批次堆積

**症狀**：streaming 視覺效果時好時壞，token 有時一次送出多個。

**根本原因**：Queue + Thread 模式讓 token 產生（LLM 速率）與傳輸（ASGI send）解耦，多個 token 可能在同一個 event loop turn 中堆積進 Queue，一起被送出。

**解法**：改用 **sync generator** 直接迭代 `agent.run(stream=True)`。sync `for` 會在每個 token 處阻塞（等 LLM 下一個 token），確保一次只 yield 一個 token。

```python
# ❌ 錯誤：Queue + Thread 解耦造成批次堆積
async def _stream_llm(prompt, sid):
    queue = asyncio.Queue()
    def run_sync():
        for chunk in self.agent.run(stream=True):
            asyncio.run_coroutine_threadsafe(queue.put(("token", chunk.content)), loop)
    threading.Thread(target=run_sync).start()
    while True:
        evt_type, data = await queue.get()
        yield data

# ✅ 正確：sync generator 直接迭代，天然一次一 token
def stream_message(self, sid, content):
    for chunk in self.agent.run(content, session_id=sid, stream=True):
        if chunk.content:
            yield ("token", chunk.content)
    yield ("done", ui)
```

### 問題三：PostgreSQL 連線用 `localhost` 失敗

**原因**：Windows 上 `localhost` 預設走 IPv6 (`::1`)，PostgreSQL 只監聽 IPv4 `127.0.0.1`。

**解法**：db_url 一律使用 `127.0.0.1`：

```python
# ❌ 錯誤
db_url="postgresql+psycopg://user:pass@localhost:5432/postgres"

# ✅ 正確
db_url="postgresql+psycopg://user:pass@127.0.0.1:5432/postgres"
```

### 問題四：首次請求非常慢（135 秒+）

**原因**：agno 在首次寫入時自動建立資料庫 table（含 index、外鍵），DDL 操作耗時。

**解法**：先執行初始化腳本（只需一次），或停用資料庫：

```bash
# 選項 A：提前初始化 table（推薦，只需執行一次）
cd backend
python init_database.py

# 選項 B：停用資料庫（無歷史保存，啟動最快）
# 在 agent.py 設定：
# USE_DATABASE = False
```

---

## 核心架構

### SSE Streaming 流程

```
Frontend (React)                Backend (FastAPI + Starlette)
      │                               │
      │── POST /api/chat/stream ──────▶│
      │                               │
      │                    def event_gen():  ← sync generator
      │                        for token in agent.run(stream=True):
      │                            yield f"data: {token}\n\n"
      │                               │
      │                    StreamingResponse(event_gen())
      │                    → iterate_in_threadpool()
      │                    → 每個 next() 在 thread 中執行
      │                    → event loop 可在每個 token 間 flush
      │                               │
      │◀── data: {"type":"token"} ────│  token 1 (~30ms)
      │◀── data: {"type":"token"} ────│  token 2 (~30ms)
      │◀── data: {"type":"done"}  ────│  結束
      │                               │
  ReadableStream reader
  每個 chunk 觸發 setMessages() 追加文字
  → 瀏覽器逐字渲染 streaming 效果
```

### A2UI Component Blueprint

後端不傳 HTML，傳 JSON 描述元件，前端 renderer 映射到原生 React 元件：

```json
{
  "id": "name_input",
  "component": {
    "type": "TextField",
    "label": "您的姓名",
    "binding": "/booking/name",
    "required": true
  }
}
```

---

## 擴展

### 加入新的互動場景

1. 在 `a2ui_builder.py` 新增 `build_xxx_form()` 方法
2. 在 `agent.py` system prompt 加入新場景描述
3. 在 `stream_action()` 加入新 action 路由
4. 前端 `A2UIRenderer.jsx` **不需要修改**（元件類型已內建）

### 更換 LLM

修改 `agent.py` 中的 model 設定，支援任何 OpenAI-compatible API：

```python
model = LiteLLMOpenAI(
    id="gpt-4o",
    api_key="sk-...",
    base_url="https://api.openai.com/v1",
)
```
