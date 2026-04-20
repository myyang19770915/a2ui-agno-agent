實作計畫是專為 Code Agent（如 Agno、GitHub Copilot 或 AutoGen）設計的指令集。它採用模組化結構，並嚴格遵循 A2UI 的五大核心概念。

您可以直接將以下內容貼給您的 Code Agent。

🚀 A2UI 動態歷史趨勢圖實作計畫
1. 目標 (Objective)
建立一個可動態切換時間範圍（7天/30天）的歷史良率趨勢看板。當使用者更換範圍時，後端需呼叫現有數據 API 並透過 dataModelUpdate 訊息即時更新畫面。

2. 數據模型設計 (Data Model Schema)
定義基礎狀態結構，確保組件與資料路徑正確綁定。

$.ui.selected_range: 存儲目前的選單值（預設 7d）。

$.ui.is_loading: 布林值，控制圖表載入遮罩。

$.data.yield_trend: 存儲圖表所需的陣列數據。

3. UI 佈局配置 (Surface & Components JSON)
請 Agent 生成以下介面定義：

JSON
{
  "surface": "Yield_Dashboard",
  "components": [
    {
      "id": "selector_01",
      "type": "SelectField",
      "bind": "$.ui.selected_range",
      "options": [
        {"label": "最近 7 天", "value": "7d"},
        {"label": "最近 30 天", "value": "30d"}
      ],
      "on_change": { "message_type": "FETCH_HISTORICAL_TREND" }
    },
    {
      "id": "chart_01",
      "type": "LineChart",
      "bind": "$.data.yield_trend",
      "loading_bind": "$.ui.is_loading",
      "properties": {
        "x_key": "timestamp",
        "y_key": "value",
        "y_label": "良率 (%)"
      }
    }
  ]
}
4. 後端邏輯處理器 (Message Handler Implementation)
要求 Code Agent 撰寫 Python (FastAPI) 邏輯，需包含：

Step A: 處理 FETCH_HISTORICAL_TREND 訊息
行為 (Behavior): 接收訊息後，立即回傳一筆 dataModelUpdate 將 $.ui.is_loading 設為 true。

行為 (Behavior): 讀取 message.data_model['ui']['selected_range']。

Step B: 呼叫現有數據 API
API 串接邏輯: * Endpoint: https://api.txc.com/mes/yield

Params: range={selected_range}

數據轉換 (Scenario-Behavior-Solution): * 狀況: API 回傳格式為 { "code": 200, "results": [...] }。

行為: 提取 results 並映射至 A2UI Chart 組件要求的 [{timestamp: "...", value: ...}] 格式。

解決方案: 使用 Aggregate Node 邏輯確保數據點不超過 50 點（若點數過多則進行取樣），以維持渲染速度。

Step C: 回傳更新訊息
發送 dataModelUpdate 訊息：

更新 $.data.yield_trend 為新數據。

更新 $.ui.is_loading 為 false。

5. 異常處理與優化 (Edge Cases)
請 Code Agent 在實作中加入以下保護機制：

Empty State: 若 API 回傳空值，應將 $.data.yield_trend 設為 [] 並顯示「此範圍暫無數據」提示。

Error Handling: 若 API 逾時，發送 toastMessage 告知使用者「連線異常，請稍後再試」。

💡 給 Code Agent 的提示 (Prompt Tip)
"請根據上述計畫，使用 Python 實作一個處理 FETCH_HISTORICAL_TREND 訊息的非同步函數。請確保資料轉換邏輯具備強健性，能處理 API 回傳的 null 值，並採用 JSON 格式封裝 dataModelUpdate 回傳結果。"

這個計畫是否已經涵蓋了您目前所有的操作流程？如果有特定的 API 認證方式（如 Bearer Token），也可以再補充進去讓 Agent 處理。