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
import re
import time
import uuid
from datetime import date, datetime, timedelta

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.litellm import LiteLLMOpenAI
import psycopg
from psycopg import sql

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
    f"{os.getenv('DB_USER', 'webui')}:"
    f"{os.getenv('DB_PASSWORD', 'webui')}"
    f"@{os.getenv('DB_HOST', 'postgresql.database.svc.cluster.local')}"
    f":{os.getenv('DB_PORT', '5432')}"
    f"/{os.getenv('DB_NAME', 'meeting_records')}"
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


class UsageAnalyticsService:
    """查詢 agent_sessions_QA1 並彙整 user_id 使用次數。"""

    def __init__(
        self,
        db_url: str,
        schema_name: str = "ai",
        table_name: str = "agent_sessions_QA1",
    ):
        self.db_url = db_url
        self.schema_name = schema_name
        self.table_name = table_name

    @property
    def psycopg_db_url(self) -> str:
        return self.db_url.replace("+psycopg", "")

    @staticmethod
    def normalize_date(value: str | None, fallback: date) -> date:
        if not value:
            return fallback
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return fallback

    @staticmethod
    def normalize_limit(value: str | int | None, fallback: int = 10) -> int:
        try:
            return max(1, min(int(value or fallback), 50))
        except (TypeError, ValueError):
            return fallback

    def fetch_user_usage_counts(
        self,
        start_date: date,
        end_date: date,
        limit: int = 10,
    ) -> tuple[list[dict], int, int]:
        query = sql.SQL("""
            WITH normalized AS (
                SELECT
                    COALESCE(NULLIF(user_id::text, ''), '(unknown)') AS user_id_text,
                    CASE
                        WHEN created_at IS NULL THEN NULL
                        WHEN created_at::text ~ '^\\d{{13}}$'
                            THEN to_timestamp((created_at::bigint / 1000.0))
                        WHEN created_at::text ~ '^\\d{{10}}$'
                            THEN to_timestamp(created_at::bigint)
                        ELSE created_at::text::timestamp
                    END AS created_at_ts
                FROM {}.{}
            ),
            filtered AS (
                SELECT user_id_text
                FROM normalized
                WHERE created_at_ts >= %(start_ts)s
                  AND created_at_ts < %(end_ts)s
            ),
            grouped AS (
                SELECT
                    user_id_text AS user_id,
                    COUNT(*)::int AS usage_count
                FROM filtered
                GROUP BY user_id_text
            )
            SELECT
                user_id,
                usage_count,
                SUM(usage_count) OVER ()::int AS total_sessions,
                COUNT(*) OVER ()::int AS unique_users
            FROM grouped
            ORDER BY usage_count DESC, user_id ASC
            LIMIT %(limit)s
        """).format(
            sql.Identifier(self.schema_name),
            sql.Identifier(self.table_name),
        )

        params = {
            "start_ts": datetime.combine(start_date, datetime.min.time()),
            "end_ts": datetime.combine(end_date + timedelta(days=1), datetime.min.time()),
            "limit": self.normalize_limit(limit, fallback=10),
        }

        with psycopg.connect(self.psycopg_db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                records = cur.fetchall()

        rows = [{"user_id": row[0], "usage_count": row[1]} for row in records]
        total_sessions = records[0][2] if records else 0
        unique_users = records[0][3] if records else 0
        return rows, total_sessions, unique_users

    def fetch_daily_stacked_usage(
        self,
        start_date: date,
        end_date: date,
        top_n: int = 5,
    ) -> tuple[list[dict], list[str]]:
        top_users_query = sql.SQL("""
            WITH normalized AS (
                SELECT
                    COALESCE(NULLIF(user_id::text, ''), '(unknown)') AS user_id_text,
                    CASE
                        WHEN created_at IS NULL THEN NULL
                        WHEN created_at::text ~ '^\\d{{13}}$'
                            THEN to_timestamp((created_at::bigint / 1000.0))
                        WHEN created_at::text ~ '^\\d{{10}}$'
                            THEN to_timestamp(created_at::bigint)
                        ELSE created_at::text::timestamp
                    END AS created_at_ts
                FROM {}.{}
            )
            SELECT user_id_text
            FROM normalized
            WHERE created_at_ts >= %(start_ts)s
              AND created_at_ts < %(end_ts)s
            GROUP BY user_id_text
            ORDER BY COUNT(*) DESC, user_id_text ASC
            LIMIT %(top_n)s
        """).format(
            sql.Identifier(self.schema_name),
            sql.Identifier(self.table_name),
        )

        query = sql.SQL("""
            WITH normalized AS (
                SELECT
                    COALESCE(NULLIF(user_id::text, ''), '(unknown)') AS user_id_text,
                    CASE
                        WHEN created_at IS NULL THEN NULL
                        WHEN created_at::text ~ '^\\d{{13}}$'
                            THEN to_timestamp((created_at::bigint / 1000.0))
                        WHEN created_at::text ~ '^\\d{{10}}$'
                            THEN to_timestamp(created_at::bigint)
                        ELSE created_at::text::timestamp
                    END AS created_at_ts
                FROM {}.{}
            ),
            filtered AS (
                SELECT
                    user_id_text,
                    DATE(created_at_ts) AS usage_date
                FROM normalized
                WHERE created_at_ts >= %(start_ts)s
                  AND created_at_ts < %(end_ts)s
            ),
            top_users AS (
                SELECT user_id_text
                FROM filtered
                GROUP BY user_id_text
                ORDER BY COUNT(*) DESC, user_id_text ASC
                LIMIT %(top_n)s
            ),
            grouped AS (
                SELECT
                    usage_date,
                    CASE
                        WHEN user_id_text IN (SELECT user_id_text FROM top_users) THEN user_id_text
                        ELSE '其他'
                    END AS series_name,
                    COUNT(*)::int AS usage_count
                FROM filtered
                GROUP BY usage_date, series_name
            )
            SELECT usage_date, series_name, usage_count
            FROM grouped
            ORDER BY usage_date ASC, usage_count DESC, series_name ASC
        """).format(
            sql.Identifier(self.schema_name),
            sql.Identifier(self.table_name),
        )

        params = {
            "start_ts": datetime.combine(start_date, datetime.min.time()),
            "end_ts": datetime.combine(end_date + timedelta(days=1), datetime.min.time()),
            "top_n": max(1, min(top_n, 8)),
        }

        with psycopg.connect(self.psycopg_db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(top_users_query, params)
                top_users = [row[0] for row in cur.fetchall()]
                cur.execute(query, params)
                records = cur.fetchall()

        daily_map: dict[str, dict[str, int | str]] = {}
        series_order: list[str] = list(top_users)
        has_other = False

        for usage_date, series_name, usage_count in records:
            date_key = usage_date.isoformat()
            if date_key not in daily_map:
                daily_map[date_key] = {"date": date_key}
            daily_map[date_key][series_name] = usage_count
            if series_name == "其他":
                has_other = True
            elif series_name not in series_order:
                series_order.append(series_name)

        if has_other:
            series_order.append("其他")

        rows = list(daily_map.values())
        return rows, series_order


class DemoAgent:
    def __init__(self):
        self.sessions: dict[str, list[dict]] = {}
        self.builder = A2UIBuilder()
        self.analytics = UsageAnalyticsService(DB_URL)
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

        def show_usage_analytics_form() -> str:
            """顯示使用次數分析查詢表單給使用者。
            當使用者想查詢 user_id 使用次數、查看 agent_sessions_QA1 統計、產生圖表時，請呼叫此工具。
            """
            self._pending_ui = self.builder.build_usage_analytics_form()
            return "使用次數分析表單已顯示，請選擇日期區間後產生圖表。"

        # ── 建立 agno Agent（sync PostgresDb + LLM）─────────

        model = LiteLLMOpenAI(
            id=os.getenv("MODEL_ID", "TXC-LLM"),
            api_key=os.getenv("LITELLM_API_KEY", "AI.7u8i(O)P"),
            base_url=os.getenv("LITELLM_BASE_URL", "http://192.168.37.71:32290"),
            max_tokens=4096,
            extra_body={'chat_template_kwargs': {'enable_thinking': False}}
        )

        db = PostgresDb(
            db_url=DB_URL,
            session_table="a2ui_agent_sessions",
        )

        self.agent = Agent(
            model=model,
            db=db,
            tools=[show_booking_form, show_feedback_form, show_usage_analytics_form],
            instructions=[
                "你是 A2UI Demo Agent，一個友善的對話助理。",
                "你可以在對話中彈出互動表單，使用者操作完後結果會回到對話裡繼續交流。",
                "當使用者想要訂位、預約餐廳時，請呼叫 show_booking_form 工具。",
                "當使用者想要給予意見回饋、填寫問卷時，請呼叫 show_feedback_form 工具。",
                "當使用者想查詢 user_id 使用次數、agent_sessions_QA1 趨勢、分析圖表、直方圖或報表時，請呼叫 show_usage_analytics_form 工具。",
                "對於一般對話，直接用自然語言回覆即可，不需要呼叫任何工具。",
                "回覆請使用繁體中文。請盡量簡潔有力，避免冗長。",
            ],
            add_history_to_context=True,
            num_history_runs=5,
            markdown=True,
        )

        self.intent_agent = Agent(
            model=model,
            instructions=[
                "你是意圖分類器，不是聊天助理。",
                "請根據使用者最後一句話，判斷最適合的意圖。",
                "只允許輸出以下其中一個 label，不能輸出其他文字：",
                "booking_form",
                "feedback_form",
                "usage_analytics_form",
                "general",
                "當使用者想訂位、預約、訂桌、安排用餐時，輸出 booking_form。",
                "當使用者想填意見、回饋、評價、問卷時，輸出 feedback_form。",
                "當使用者想看使用次數、使用統計、user_id 次數、session 報表、agent_sessions_QA1 圖表、登入或操作使用趨勢時，輸出 usage_analytics_form。",
                "其餘一律輸出 general。",
            ],
            markdown=False,
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

    def classify_intent_sync(self, content: str) -> str:
        """使用 LLM 將使用者訊息分類為固定意圖 label。"""
        prompt = f"請只輸出意圖 label。\n使用者訊息：{content.strip()}"
        try:
            response = self.intent_agent.run(prompt)
            raw_label = (response.content or "").strip().lower()
        except Exception:
            log.exception("Intent classification failed")
            return "general"

        allowed = {
            "booking_form",
            "feedback_form",
            "usage_analytics_form",
            "general",
        }
        if raw_label in allowed:
            log.info("Intent classified: %s -> %s", content, raw_label)
            return raw_label

        # Allow slightly noisy model outputs such as:
        # "意圖：usage_analytics_form" or "The label is usage_analytics_form"
        for label in allowed:
            if re.search(rf"\\b{re.escape(label)}\\b", raw_label):
                log.info("Intent classified with fuzzy parse: %s -> %s (%s)", content, label, raw_label)
                return label

        log.info("Intent classified fallback to general: %s -> %s", content, raw_label)
        return "general"

    async def classify_intent(self, content: str) -> str:
        return await asyncio.to_thread(self.classify_intent_sync, content)

    def open_form(self, sid: str, intent: str) -> dict:
        """直接回傳指定表單，不經主對話 LLM 判斷。"""
        timer = PipelineTimer(f"open_form[{intent}] sid={sid[:8]}")
        form_map = {
            "booking_form": (
                self.builder.build_booking_form,
                "已為您開啟餐廳訂位表單，請填寫資訊後送出。",
            ),
            "feedback_form": (
                self.builder.build_feedback_form,
                "已為您開啟意見回饋表單，請填寫後送出。",
            ),
            "usage_analytics_form": (
                self.builder.build_usage_analytics_form,
                "已為您開啟使用次數分析表單，請選擇日期區間後產生圖表。",
            ),
        }
        builder, reply = form_map[intent]
        self._pending_ui = builder()
        ui = self._pending_ui
        self._add(sid, "agent", reply, ui=ui)
        timer.mark(f"build_{intent}")
        timer.report()
        return {"reply": reply, "ui": ui}

    def stream_open_form(self, sid: str, intent: str):
        """Streaming 版本的表單開啟。"""
        timer = PipelineTimer(f"stream_open_form[{intent}] sid={sid[:8]}")
        form_map = {
            "booking_form": (
                self.builder.build_booking_form,
                "已為您開啟餐廳訂位表單，請填寫資訊後送出。",
            ),
            "feedback_form": (
                self.builder.build_feedback_form,
                "已為您開啟意見回饋表單，請填寫後送出。",
            ),
            "usage_analytics_form": (
                self.builder.build_usage_analytics_form,
                "已為您開啟使用次數分析表單，請選擇日期區間後產生圖表。",
            ),
        }
        builder, reply = form_map[intent]
        self._pending_ui = builder()
        ui = self._pending_ui
        yield ("token", reply)
        self._add(sid, "agent", reply, ui=ui)
        timer.mark(f"build_{intent}")
        timer.report()
        yield ("done", ui)

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
        elif action_name == "show_usage_analytics":
            return await self._handle_usage_analytics(sid, data)

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

    async def _handle_usage_analytics(self, sid: str, data: dict) -> dict:
        start_date = self.analytics.normalize_date(
            data.get("start_date"),
            datetime.now().date() - timedelta(days=6),
        )
        end_date = self.analytics.normalize_date(
            data.get("end_date"),
            datetime.now().date(),
        )
        limit = self.analytics.normalize_limit(data.get("limit"), fallback=10)

        if end_date < start_date:
            start_date, end_date = end_date, start_date

        user_summary = (
            f"[📊 分析查詢]\n"
            f"開始日期: {start_date.isoformat()} / 結束日期: {end_date.isoformat()} / "
            f"顯示筆數: {limit}"
        )
        self._add(sid, "user", user_summary)

        timer = PipelineTimer(f"_handle_usage_analytics sid={sid[:8]}")
        try:
            rows, total_sessions, unique_users = await asyncio.to_thread(
                self.analytics.fetch_user_usage_counts,
                start_date,
                end_date,
                limit,
            )
            daily_rows, daily_series = await asyncio.to_thread(
                self.analytics.fetch_daily_stacked_usage,
                start_date,
                end_date,
                min(limit, 5),
            )
            timer.mark("db_usage_analytics_query")
        except Exception as e:
            log.exception("Usage analytics query failed")
            reply = (
                "目前無法產生使用次數圖表。"
                "請確認資料庫連線正常，且 agent_sessions_QA1 具有 user_id 與 created_at 欄位。"
            )
            ui = self.builder.build_usage_analytics_error(
                start_date.isoformat(),
                end_date.isoformat(),
                str(e),
            )
            self._add(sid, "agent", reply, ui=ui)
            timer.mark("db_usage_analytics_failed")
            timer.report()
            return {"reply": reply, "ui": ui}

        reply = (
            f"已完成 {start_date.isoformat()} 到 {end_date.isoformat()} 的使用次數分析。"
            f"共 {total_sessions} 次使用、{unique_users} 位 user_id。"
        )
        ui = self.builder.build_usage_analytics_result(
            start_date.isoformat(),
            end_date.isoformat(),
            total_sessions,
            unique_users,
            rows,
            daily_rows,
            daily_series,
        )
        self._add(sid, "agent", reply, ui=ui)
        timer.mark("session_add_agent")
        timer.report()
        return {"reply": reply, "ui": ui}

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
        elif action_name == "show_usage_analytics":
            yield from self._stream_usage_analytics(sid, data)
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

    def _stream_usage_analytics(self, sid: str, data: dict):
        start_date = self.analytics.normalize_date(
            data.get("start_date"),
            datetime.now().date() - timedelta(days=6),
        )
        end_date = self.analytics.normalize_date(
            data.get("end_date"),
            datetime.now().date(),
        )
        limit = self.analytics.normalize_limit(data.get("limit"), fallback=10)

        if end_date < start_date:
            start_date, end_date = end_date, start_date

        user_summary = (
            f"[📊 分析查詢]\n"
            f"開始日期: {start_date.isoformat()} / 結束日期: {end_date.isoformat()} / "
            f"顯示筆數: {limit}"
        )
        self._add(sid, "user", user_summary)

        timer = PipelineTimer(f"stream_usage_analytics sid={sid[:8]}")
        try:
            rows, total_sessions, unique_users = self.analytics.fetch_user_usage_counts(
                start_date,
                end_date,
                limit,
            )
            daily_rows, daily_series = self.analytics.fetch_daily_stacked_usage(
                start_date,
                end_date,
                min(limit, 5),
            )
            timer.mark("db_usage_analytics_query")
            reply = (
                f"已完成 {start_date.isoformat()} 到 {end_date.isoformat()} 的使用次數分析。"
                f"共 {total_sessions} 次使用、{unique_users} 位 user_id。"
            )
            ui = self.builder.build_usage_analytics_result(
                start_date.isoformat(),
                end_date.isoformat(),
                total_sessions,
                unique_users,
                rows,
                daily_rows,
                daily_series,
            )
        except Exception as e:
            log.exception("Streaming usage analytics query failed")
            reply = (
                "目前無法產生使用次數圖表。"
                "請確認資料庫連線正常，且 agent_sessions_QA1 具有 user_id 與 created_at 欄位。"
            )
            ui = self.builder.build_usage_analytics_error(
                start_date.isoformat(),
                end_date.isoformat(),
                str(e),
            )
            timer.mark("db_usage_analytics_failed")

        yield ("token", reply)
        self._add(sid, "agent", reply, ui=ui)
        timer.mark("session_add_agent")
        timer.report()
        yield ("done", ui)
