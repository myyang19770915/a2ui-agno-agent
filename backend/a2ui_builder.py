"""
A2UI JSON Builder
=================
生成符合 A2UI v0.8 精神的 component JSON blueprint。

結構說明：
{
  "surfaceId": "表面 ID（一個互動面板一個 ID）",
  "components": [
    {
      "id": "元件唯一 ID",
      "component": {
        "type": "元件類型 (Text / TextField / Select / Button ...)",
        "label": "顯示標籤",
        "binding": "/dataModel/path",  ← 雙向資料綁定路徑
        "action": { ... }              ← Button 的 callback 定義
      }
    }
  ],
  "dataModel": { ... }  ← 表單初始資料
}

前端 renderer 會根據這份 JSON 渲染原生元件，
使用者操作後透過 binding 收集資料，
Button click 時將 context 中指定的 binding 值送回後端。
"""

from datetime import datetime, timedelta


class A2UIBuilder:

    def build_booking_form(self) -> dict:
        """餐廳訂位表單"""
        return {
            "surfaceId": "booking_form",
            "components": [
                {
                    "id": "title",
                    "component": {
                        "type": "Text",
                        "text": "🍽️ 餐廳訂位",
                        "variant": "h2",
                    },
                },
                {
                    "id": "name_input",
                    "component": {
                        "type": "TextField",
                        "label": "您的姓名",
                        "placeholder": "請輸入姓名",
                        "binding": "/booking/name",
                        "required": True,
                    },
                },
                {
                    "id": "date_input",
                    "component": {
                        "type": "DateInput",
                        "label": "訂位日期",
                        "binding": "/booking/date",
                        "required": True,
                    },
                },
                {
                    "id": "time_input",
                    "component": {
                        "type": "Select",
                        "label": "用餐時間",
                        "binding": "/booking/time",
                        "options": [
                            {"label": "11:30", "value": "11:30"},
                            {"label": "12:00", "value": "12:00"},
                            {"label": "12:30", "value": "12:30"},
                            {"label": "18:00", "value": "18:00"},
                            {"label": "18:30", "value": "18:30"},
                            {"label": "19:00", "value": "19:00"},
                            {"label": "19:30", "value": "19:30"},
                        ],
                        "required": True,
                    },
                },
                {
                    "id": "guests_input",
                    "component": {
                        "type": "Select",
                        "label": "用餐人數",
                        "binding": "/booking/guests",
                        "options": [
                            {"label": "1 位", "value": "1"},
                            {"label": "2 位", "value": "2"},
                            {"label": "3 位", "value": "3"},
                            {"label": "4 位", "value": "4"},
                            {"label": "5 位", "value": "5"},
                            {"label": "6 位以上", "value": "6+"},
                        ],
                        "defaultValue": "2",
                    },
                },
                {
                    "id": "special_input",
                    "component": {
                        "type": "TextArea",
                        "label": "特殊需求",
                        "placeholder": "例如：靠窗座位、兒童椅、過敏食物…",
                        "binding": "/booking/special_requests",
                    },
                },
                {
                    "id": "submit_btn",
                    "component": {
                        "type": "Button",
                        "label": "確認訂位",
                        "variant": "primary",
                        "action": {
                            "name": "confirm_booking",
                            "context": [
                                {"key": "name", "binding": "/booking/name"},
                                {"key": "date", "binding": "/booking/date"},
                                {"key": "time", "binding": "/booking/time"},
                                {"key": "guests", "binding": "/booking/guests"},
                                {"key": "special_requests", "binding": "/booking/special_requests"},
                            ],
                        },
                    },
                },
            ],
            "dataModel": {
                "booking": {
                    "name": "",
                    "date": "",
                    "time": "",
                    "guests": "2",
                    "special_requests": "",
                }
            },
        }

    def build_booking_confirmation(
        self, name, date, time, guests, special, confirmation_id
    ) -> dict:
        """訂位確認卡片（唯讀展示）"""
        return {
            "surfaceId": "booking_confirmation",
            "components": [
                {
                    "id": "conf_title",
                    "component": {
                        "type": "Text",
                        "text": "✅ 訂位確認",
                        "variant": "h2",
                    },
                },
                {
                    "id": "conf_id",
                    "component": {
                        "type": "Text",
                        "text": f"確認編號：{confirmation_id}",
                        "variant": "subtitle",
                    },
                },
                {
                    "id": "conf_card",
                    "component": {
                        "type": "Card",
                        "children": [
                            {"type": "Text", "text": f"👤 姓名：{name}"},
                            {"type": "Text", "text": f"📅 日期：{date}"},
                            {"type": "Text", "text": f"🕐 時間：{time}"},
                            {"type": "Text", "text": f"👥 人數：{guests} 位"},
                            {"type": "Text", "text": f"📝 備註：{special}"},
                        ],
                    },
                },
            ],
        }

    def build_feedback_form(self) -> dict:
        """意見回饋問卷"""
        return {
            "surfaceId": "feedback_form",
            "components": [
                {
                    "id": "fb_title",
                    "component": {
                        "type": "Text",
                        "text": "📝 意見回饋",
                        "variant": "h2",
                    },
                },
                {
                    "id": "rating_input",
                    "component": {
                        "type": "Rating",
                        "label": "整體滿意度",
                        "maxStars": 5,
                        "binding": "/feedback/rating",
                        "required": True,
                    },
                },
                {
                    "id": "category_input",
                    "component": {
                        "type": "Select",
                        "label": "回饋類別",
                        "binding": "/feedback/category",
                        "options": [
                            {"label": "服務品質", "value": "服務品質"},
                            {"label": "餐點口味", "value": "餐點口味"},
                            {"label": "環境氛圍", "value": "環境氛圍"},
                            {"label": "價格合理性", "value": "價格合理性"},
                            {"label": "其他", "value": "其他"},
                        ],
                    },
                },
                {
                    "id": "comment_input",
                    "component": {
                        "type": "TextArea",
                        "label": "詳細意見",
                        "placeholder": "請告訴我們您的想法…",
                        "binding": "/feedback/comment",
                        "rows": 4,
                    },
                },
                {
                    "id": "fb_submit_btn",
                    "component": {
                        "type": "Button",
                        "label": "送出回饋",
                        "variant": "primary",
                        "action": {
                            "name": "submit_feedback",
                            "context": [
                                {"key": "rating", "binding": "/feedback/rating"},
                                {"key": "category", "binding": "/feedback/category"},
                                {"key": "comment", "binding": "/feedback/comment"},
                            ],
                        },
                    },
                },
            ],
            "dataModel": {
                "feedback": {
                    "rating": "5",
                    "category": "",
                    "comment": "",
                }
            },
        }

    def build_usage_analytics_form(self) -> dict:
        """使用次數分析查詢表單"""
        today = datetime.now().date()
        start = today - timedelta(days=6)
        return {
            "surfaceId": "usage_analytics_form",
            "subtitle": "依 created_at 篩選日期區間，統計各 user_id 的使用次數",
            "components": [
                {
                    "id": "analytics_title",
                    "component": {
                        "type": "Text",
                        "text": "📊 使用次數分析",
                        "variant": "h2",
                    },
                },
                {
                    "id": "analytics_hint",
                    "component": {
                        "type": "Text",
                        "text": "created_at 可為 Unix Timestamp 或日期時間，系統會自動轉成日期後再做區間查詢。",
                    },
                },
                {
                    "id": "analytics_start_date",
                    "component": {
                        "type": "DateInput",
                        "label": "開始日期",
                        "binding": "/analytics/start_date",
                        "required": True,
                    },
                },
                {
                    "id": "analytics_end_date",
                    "component": {
                        "type": "DateInput",
                        "label": "結束日期",
                        "binding": "/analytics/end_date",
                        "required": True,
                    },
                },
                {
                    "id": "analytics_limit",
                    "component": {
                        "type": "Select",
                        "label": "顯示前幾名 user_id",
                        "binding": "/analytics/limit",
                        "options": [
                            {"label": "前 5 名", "value": "5"},
                            {"label": "前 10 名", "value": "10"},
                            {"label": "前 15 名", "value": "15"},
                            {"label": "前 20 名", "value": "20"},
                        ],
                        "defaultValue": "10",
                    },
                },
                {
                    "id": "analytics_submit",
                    "component": {
                        "type": "Button",
                        "label": "產生圖表",
                        "variant": "primary",
                        "action": {
                            "name": "show_usage_analytics",
                            "context": [
                                {"key": "start_date", "binding": "/analytics/start_date"},
                                {"key": "end_date", "binding": "/analytics/end_date"},
                                {"key": "limit", "binding": "/analytics/limit"},
                            ],
                        },
                    },
                },
            ],
            "dataModel": {
                "analytics": {
                    "start_date": start.isoformat(),
                    "end_date": today.isoformat(),
                    "limit": "10",
                }
            },
        }

    def build_usage_analytics_result(
        self,
        start_date: str,
        end_date: str,
        total_sessions: int,
        unique_users: int,
        rows: list[dict],
        daily_rows: list[dict],
        daily_series: list[str],
    ) -> dict:
        """使用次數分析結果面板"""
        top_user = rows[0]["user_id"] if rows else "無資料"
        top_count = rows[0]["usage_count"] if rows else 0
        return {
            "surfaceId": "usage_analytics_result",
            "subtitle": f"查詢區間：{start_date} 至 {end_date}",
            "components": [
                {
                    "id": "analytics_result_title",
                    "component": {
                        "type": "Text",
                        "text": "📈 使用次數圖表",
                        "variant": "h2",
                    },
                },
                {
                    "id": "analytics_summary",
                    "component": {
                        "type": "Card",
                        "children": [
                            {"type": "Text", "text": f"查詢區間：{start_date} ~ {end_date}"},
                            {"type": "Text", "text": f"總使用次數：{total_sessions}"},
                            {"type": "Text", "text": f"不同 user_id 數：{unique_users}"},
                            {"type": "Text", "text": f"最高使用者：{top_user} ({top_count} 次)"},
                        ],
                    },
                },
                {
                    "id": "analytics_chart",
                    "component": {
                        "type": "PieChart",
                        "title": "各 user_id 使用次數",
                        "description": "依 user_id 統計使用次數，顯示各使用者在總使用量中的占比",
                        "labelKey": "user_id",
                        "valueKey": "usage_count",
                        "data": rows,
                        "emptyText": "此日期區間查無資料",
                    },
                },
                {
                    "id": "analytics_daily_stacked_chart",
                    "component": {
                        "type": "StackedBarChart",
                        "title": "每日趨勢堆疊圖",
                        "description": "以日期為 X 軸，顯示每日使用次數，並將主要 user_id 以堆疊方式呈現；其餘使用者合併為「其他」。",
                        "xKey": "date",
                        "series": daily_series,
                        "data": daily_rows,
                        "emptyText": "此日期區間沒有可顯示的每日趨勢資料",
                    },
                },
            ],
        }

    def build_usage_analytics_error(
        self,
        start_date: str,
        end_date: str,
        error_message: str,
    ) -> dict:
        """分析查詢錯誤面板"""
        return {
            "surfaceId": "usage_analytics_error",
            "subtitle": f"查詢區間：{start_date} 至 {end_date}",
            "components": [
                {
                    "id": "analytics_error_title",
                    "component": {
                        "type": "Text",
                        "text": "⚠️ 使用次數分析失敗",
                        "variant": "h2",
                    },
                },
                {
                    "id": "analytics_error_card",
                    "component": {
                        "type": "Card",
                        "children": [
                            {"type": "Text", "text": f"查詢區間：{start_date} ~ {end_date}"},
                            {"type": "Text", "text": f"錯誤訊息：{error_message}"},
                            {"type": "Text", "text": "請確認資料庫可連線，且表 agent_sessions_QA1 內含 user_id 與 created_at 欄位。"},
                        ],
                    },
                },
            ],
        }
