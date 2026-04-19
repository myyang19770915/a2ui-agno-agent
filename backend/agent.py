"""
Demo Agent — 對話引擎 + A2UI 元件生成（agno + LiteLLM）
=========================================================
使用 agno 架構搭配 LiteLLM 進行 LLM 推理：
  1. LLM 理解使用者意圖
  2. 需要互動時，透過 tool call 生成 A2UI component JSON
  3. 處理 action callback（使用者提交的表單資料）
  4. 將結果寫回對話上下文，讓對話可以繼續

⚠️ 重要：DB URL 必須使用 127.0.0.1 而非 localhost，
   否則 Windows DNS 解析會造成 135 秒+ 延遲。
   首次啟動需執行 init_database.py 預建表結構。
"""

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.litellm import LiteLLMOpenAI

from a2ui_builder import A2UIBuilder

log = logging.getLogger("a2ui.agent")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

# ── PostgreSQL 連線設定 ─────────────────────────────
# ⚠️ 必須使用 127.0.0.1，不要用 localhost（Windows DNS 解析延遲 135s+）
DB_URL = (
    f"postgresql+psycopg://"
    f"{os.getenv('DB_USER', 'postgres')}:"
    f"{os.getenv('DB_PASSWORD', 'myyang')}"
    f"@{os.getenv('DB_HOST', '127.0.0.1')}"
    f":{os.getenv('DB_PORT', '5433')}"
    f"/{os.getenv('DB_NAME', 'postgres')}"
)


# ── 計時工具 ───────────────────────────────────
class PipelineTimer:
    """追蹤各階段耗時，最後統一輸出。"""

    def __init__(self, label: str):
        self.label = label
        self._stages: list[tuple[str, float]] = []
        self._t0 = time.perf_counter()
        self._last = self._t0

    def mark(self, stage: str):
        now = time.perf_counter()
        self._stages.append((stage, now - self._last))
        self._last = now

    def report(self):
        total = time.perf_counter() - self._t0
        lines = [f"\n{chr(9472)*52}"]
        lines.append(f"  Pipeline: {self.label}")
        lines.append(f"{chr(9472)*52}")
        for name, dt in self._stages:
            bar = chr(9608) * min(int(dt * 10), 30)
            lines.append(f"  {name:<28} {dt*1000:>7.1f} ms  {bar}")
        lines.append(f"{chr(9472)*52}")
        lines.append(f"  {'TOTAL':<28} {total*1000:>7.1f} ms")
        lines.append(f"{chr(9472)*52}")
        log.info("\n".join(lines))


class DemoAgent:
    def __init__(self):
        self.sessions: dict[str, list[dict]] = {}
        self.builder = A2UIBuilder()
        self._pending_ui: dict | None = None

        # ── 定義 agno tools（閉包捕獲 self）─────────────────

        def show_booking_form() -> str:
            """顯示餐廳訂位表單給使用者。
            當使用者想要訂位、預約餐廳、訂桌時，請呼叫此工具。
            """
            self._pending_ui = self.builder.build_booking_form()
            return "餐廳訂位表單已顯示給使用者，請引導使用者填寫表單，完成後點擊「確認訂位」。"

        def show_feedback_form() -> str:
            """顯示意見回饋問卷表單給使用者。
            當使用者想要給予回饋、填寫問卷、評價服務時，請呼叫此工具。
            """
            self._pending_ui = self.builder.build_feedback_form()
            return "意見回饋表單已顯示給使用者，請引導使用者填寫表單。"

        # ── 建立 agno Agent（sync PostgresDb + LLM）─────────

        model = LiteLLMOpenAI(
            id=os.getenv("MODEL_ID", "qwen35-27b"),
            api_key=os.getenv("LITELLM_API_KEY", "sk-1234"),
            base_url=os.getenv("LITELLM_BASE_URL", "http://localhost:4001/v1"),
            max_tokens=512,
        )

        db = PostgresDb(
            db_url=DB_URL,
            session_table="a2ui_agent_sessions",
        )

        self.agent = Agent(
            model=model,
            db=db,
            tools=[show_booking_form, show_feedback_form],
            instructions=[
                "你是 A2UI Demo Agent，一個友善的對話助理。",
                "你可以在對話中彈出互動表單，使用者操作完後結果會回到對話裡繼續交流。",
                "當使用者想要訂位、預約餐廳時，請呼叫 show_booking_form 工具。",
                "當使用者想要給予意見回饋、填寫問卷時，請呼叫 show_feedback_form 工具。",
                "對於一般對話，直接用自然語言回覆即可，不需要呼叫任何工具。",
                "回覆請使用繁體中文。請盡量簡潔有力，避免冗長。",
            ],
            add_history_to_context=True,
            num_history_runs=5,
            markdown=True,
        )

    # ── Session 管理 ───────────────────────────────

    def _ensure_session(self, sid: str):
        if sid not in self.sessions:
            self.sessions[sid] = []

    def _add(self, sid: str, role: str, content: str, ui=None):
        self._ensure_session(sid)
        entry = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if ui:
            entry["ui"] = ui
        self.sessions[sid].append(entry)

    def get_conversation(self, sid: str) -> list[dict]:
        self._ensure_session(sid)
        return self.sessions[sid]

    # ── 處理文字訊息（非 streaming，保留做 fallback）──────────

    async def handle_message(self, sid: str, content: str) -> dict:
        timer = PipelineTimer(f"handle_message sid={sid[:8]}")

        self._add(sid, "user", content)
        self._pending_ui = None
        timer.mark("1. session_add_user")

        response = await asyncio.to_thread(
            self.agent.run, content, session_id=sid
        )
        timer.mark("2. llm_inference (+ tool calls)")

        reply = response.content or ""
        ui = self._pending_ui
        self._add(sid, "agent", reply, ui=ui)
        timer.mark("3. session_add_agent")

        timer.report()

        result: dict = {"reply": reply}
        if ui:
            result["ui"] = ui
        return result

    # ── 處理 Action Callback（非 streaming，保留做 fallback）─

    async def handle_action(self, sid: str, action_name: str, data: dict) -> dict:
        if action_name == "confirm_booking":
            return await self._handle_booking(sid, data)
        elif action_name == "submit_feedback":
            return await self._handle_feedback(sid, data)

        self._add(sid, "user", f"[動作] {action_name}: {data}")
        reply = f"收到操作 \'{action_name}\'\uff0c但我不確定如何處理。請試試其他功能。"
        self._add(sid, "agent", reply)
        return {"reply": reply}

    async def _handle_booking(self, sid: str, data: dict) -> dict:
        name = data.get("name", "匿名")
        date = data.get("date", "未指定")
        time_slot = data.get("time", "未指定")
        guests = data.get("guests", "2")
        special = data.get("special_requests", "無")
        conf_id = f"BK-{uuid.uuid4().hex[:8].upper()}"

        user_summary = (
            f"[📋 表單提交 — 訂位]\n"
            f"姓名: {name} / 日期: {date} / 時間: {time_slot}\n"
            f"人數: {guests} / 特殊需求: {special}"
        )
        self._add(sid, "user", user_summary)

        timer = PipelineTimer(f"_handle_booking sid={sid[:8]}")
        prompt = (
            f"使用者剛完成餐廳訂位，請用親切的語氣確認以下訂位資訊：\n"
            f"確認編號：{conf_id}\n"
            f"姓名：{name}，日期：{date}，時間：{time_slot}，"
            f"人數：{guests} 位，特殊需求：{special}\n"
            f"請確認訂位成功並詢問是否還需要其他服務。"
        )
        response = await asyncio.to_thread(
            self.agent.run, prompt, session_id=sid
        )
        timer.mark("llm_booking_confirm")
        reply = response.content or f"✅ 訂位成功！確認編號：{conf_id}"

        ui = self.builder.build_booking_confirmation(
            name=name, date=date, time=time_slot,
            guests=guests, special=special, confirmation_id=conf_id,
        )
        timer.mark("session_add_agent")
        timer.report()
        self._add(sid, "agent", reply, ui=ui)
        return {"reply": reply, "ui": ui}

    async def _handle_feedback(self, sid: str, data: dict) -> dict:
        rating = data.get("rating", "5")
        category = data.get("category", "一般")
        comment = data.get("comment", "（無）")

        user_summary = (
            f"[📋 表單提交 — 意見回饋]\n"
            f"評分: {rating}/5 / 類別: {category}\n"
            f"內容: {comment}"
        )
        self._add(sid, "user", user_summary)

        timer = PipelineTimer(f"_handle_feedback sid={sid[:8]}")
        prompt = (
            f"使用者剛提交了意見回饋：\n"
            f"評分：{rating}/5，類別：{category}，內容：{comment}\n"
            f"請用親切的語氣感謝使用者的回饋，並表示會持續改善。"
        )
        response = await asyncio.to_thread(
            self.agent.run, prompt, session_id=sid
        )
        timer.mark("llm_feedback_reply")
        reply = response.content or "🙏 感謝您的回饋！"

        timer.mark("session_add_agent")
        timer.report()
        self._add(sid, "agent", reply)
        return {"reply": reply}

    # ── Streaming 方法（sync generator，與 reference 一致）──────

    def stream_message(self, sid: str, content: str):
        """Sync generator：yield ("token"|"done"|"error", data)。"""
        timer = PipelineTimer(f"stream_message sid={sid[:8]}")
        self._add(sid, "user", content)
        self._pending_ui = None
        timer.mark("1. session_add_user")

        chunks: list[str] = []
        try:
            for chunk in self.agent.run(content, session_id=sid, stream=True):
                if chunk.content:
                    chunks.append(chunk.content)
                    yield ("token", chunk.content)
        except Exception as e:
            yield ("error", str(e))
            return

        timer.mark("2. llm_streaming_done")
        ui = self._pending_ui
        reply_text = "".join(chunks)
        self._add(sid, "agent", reply_text, ui=ui)
        timer.mark("3. session_add_agent")
        timer.report()
        yield ("done", ui)

    def stream_action(self, sid: str, action_name: str, data: dict):
        """路由 action 到對應的 streaming handler。"""
        if action_name == "confirm_booking":
            yield from self._stream_booking(sid, data)
        elif action_name == "submit_feedback":
            yield from self._stream_feedback(sid, data)
        else:
            self._add(sid, "user", f"[動作] {action_name}: {data}")
            reply = f"收到操作 '{action_name}'，但我不確定如何處理。請試試其他功能。"
            self._add(sid, "agent", reply)
            yield ("token", reply)
            yield ("done", None)

    def _stream_booking(self, sid: str, data: dict):
        name = data.get("name", "匿名")
        date = data.get("date", "未指定")
        time_slot = data.get("time", "未指定")
        guests = data.get("guests", "2")
        special = data.get("special_requests", "無")
        conf_id = f"BK-{uuid.uuid4().hex[:8].upper()}"

        user_summary = (
            f"[📋 表單提交 — 訂位]\n"
            f"姓名: {name} / 日期: {date} / 時間: {time_slot}\n"
            f"人數: {guests} / 特殊需求: {special}"
        )
        self._add(sid, "user", user_summary)

        timer = PipelineTimer(f"stream_booking sid={sid[:8]}")
        prompt = (
            f"使用者剛完成餐廳訂位，請用親切的語氣確認以下訂位資訊：\n"
            f"確認編號：{conf_id}\n"
            f"姓名：{name}，日期：{date}，時間：{time_slot}，"
            f"人數：{guests} 位，特殊需求：{special}\n"
            f"請確認訂位成功並詢問是否還需要其他服務。"
        )

        chunks: list[str] = []
        try:
            for chunk in self.agent.run(prompt, session_id=sid, stream=True):
                if chunk.content:
                    chunks.append(chunk.content)
                    yield ("token", chunk.content)
        except Exception as e:
            yield ("error", str(e))
            return

        timer.mark("llm_streaming_done")
        reply_text = "".join(chunks)
        ui = self.builder.build_booking_confirmation(
            name=name, date=date, time=time_slot,
            guests=guests, special=special, confirmation_id=conf_id,
        )
        self._add(sid, "agent", reply_text, ui=ui)
        timer.mark("session_add_agent")
        timer.report()
        yield ("done", ui)

    def _stream_feedback(self, sid: str, data: dict):
        rating = data.get("rating", "5")
        category = data.get("category", "一般")
        comment = data.get("comment", "（無）")

        user_summary = (
            f"[📋 表單提交 — 意見回饋]\n"
            f"評分: {rating}/5 / 類別: {category}\n"
            f"內容: {comment}"
        )
        self._add(sid, "user", user_summary)

        timer = PipelineTimer(f"stream_feedback sid={sid[:8]}")
        prompt = (
            f"使用者剛提交了意見回饋：\n"
            f"評分：{rating}/5，類別：{category}，內容：{comment}\n"
            f"請用親切的語氣感謝使用者的回饋，並表示會持續改善。"
        )

        chunks: list[str] = []
        try:
            for chunk in self.agent.run(prompt, session_id=sid, stream=True):
                if chunk.content:
                    chunks.append(chunk.content)
                    yield ("token", chunk.content)
        except Exception as e:
            yield ("error", str(e))
            return

        timer.mark("llm_streaming_done")
        reply_text = "".join(chunks)
        self._add(sid, "agent", reply_text)
        timer.mark("session_add_agent")
        timer.report()
        yield ("done", None)
