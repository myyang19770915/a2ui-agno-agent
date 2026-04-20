"""
初始化資料庫表結構（一次性執行）
================================
agno 首次建立 agent_sessions / agent_runs 等表結構較慢（1-2 分鐘），
執行此腳本預先完成，後續啟動即可秒開。

⚠️ 必須使用 127.0.0.1，不要用 localhost（Windows DNS 解析延遲 135s+）

用法：
    cd backend
    .venv\\Scripts\\activate
    python init_database.py
"""

import os
import time

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.litellm import LiteLLMOpenAI

DB_URL = (
    f"postgresql+psycopg://"
    f"{os.getenv('DB_USER', 'webui')}:"
    f"{os.getenv('DB_PASSWORD', 'webui')}"
    f"@{os.getenv('DB_HOST', 'postgresql.database.svc.cluster.local')}"
    f":{os.getenv('DB_PORT', '5432')}"
    f"/{os.getenv('DB_NAME', 'meeting_records')}"
)


def main():
    print(f"DB URL: {DB_URL}")
    print("正在初始化資料庫表結構，首次執行可能需要 1-2 分鐘...")

    t0 = time.perf_counter()

    db = PostgresDb(
        db_url=DB_URL,
        session_table="a2ui_agent_sessions",
    )

    model = LiteLLMOpenAI(
        id=os.getenv("MODEL_ID", "TXC-LLM"),
        api_key=os.getenv("LITELLM_API_KEY", "AI.7u8i(O)P"),
        base_url=os.getenv("LITELLM_BASE_URL", "http://192.168.37.71:32290"),
        max_tokens=4096,
        extra_body={'chat_template_kwargs': {'enable_thinking': False}}
    )

    agent = Agent(model=model, db=db, markdown=True)

    # 執行一次 run 觸發表建立
    print("執行測試 run 以觸發表建立...")
    agent.run(input="hello", session_id="init_session")

    elapsed = time.perf_counter() - t0
    print(f"\n✅ 資料庫初始化完成！耗時 {elapsed:.1f} 秒")
    print("現在可以啟動 server：python main.py")


if __name__ == "__main__":
    main()
