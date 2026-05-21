# 盤點語音助理 (Inventory Voice Assistant) 實作計畫

這是一個專為藥師設計的語音盤點桌面應用程式，透過語音與 Gemini Live API 互動，並自動更新 Google 試算表上的盤點資料。

## 系統架構與技術選型

### 1. 核心環境與介面
- **環境**：Python 3.10+ (由於醫院電腦可安裝，直接使用標準 Python 環境及套件)。
- **GUI 介面**：使用 `customtkinter` 提供桌面視窗。為提供最大的彈性，畫面上將包含以下設定欄位，讓使用者可以自行輸入與儲存設定：
  - **Gemini API Key** (讓使用者自備 Key 付費)。
  - **System Prompt** (系統提示詞，讓使用者自訂助理的行為與規則)。
  - **Google Service Account JSON 路徑**。
  - **Google 試算表網址 / ID**。

### 2. 語音與 AI (Gemini Live API)
- **連線架構**：採用 **Client-to-server** 架構，由本地 Python 程式作為 Client，直接透過 WebSocket (`google-genai` SDK) 與 Gemini Server 建立低延遲雙向語音通道。
- **模型選擇與非同步工具呼叫 (Async Function Calling)**：為避免在寫入試算表時中斷與藥師的對話（Blocking），我們將採用支援 **非同步工具呼叫 (Asynchronous Function Calling)** 的模型（例如 `gemini-2.5-flash`，因官方文件註明 `gemini-3.1-flash-live-preview` 尚未支援此功能）。我們會在工具定義中加上 `"behavior": "NON_BLOCKING"`，讓助理在背後執行寫入時，藥師仍可繼續與其互動。
- **藍牙耳機與噪音處理**：
  - 使用藍牙耳機可提高機動性，雖有微小藍牙傳輸延遲，但 Live API 串流的特性可以很好地彌補。
  - **噪音對策**：Gemini 本身具備一定的語音降噪能力。若醫院環境噪音仍過大，我們會引入基礎的 VAD (Voice Activity Detection) 或是 `pyaudio` 的收音門檻 (Noise Gate) 設定，避免持續傳送背景噪音消耗 Token。
- **長時段盤點 (Session Management)**：
  - 盤點通常超過 15 分鐘，為避免 Token 耗盡 (Context Window 塞滿) 或連線逾時，系統會實作 **自動重新連線與狀態繼承 (Session Resume)**。
  - 當偵測到連線即將中斷或發生中斷時，系統會自動擷取「目前盤點到哪一列、哪個藥品」的狀態，並將此狀態注入到新 Session 的 System Prompt 中，讓助理能無縫接軌繼續盤點 (Context window compression 的概念)。

### 3. Google Sheets 資料存取
- **權限架構**：使用 Service Account。**不需要為每一組藥師申請不同的 Service Account**。多組藥師可以共用同一個 Service Account，只要大家將各自的試算表共用 (Share) 給該 Service Account 的 Email 即可。Google Sheets API 可以處理多重併發寫入，只要各組盤點不同的列或不同的表就不會衝突。
- **試算表結構**：為符合您的需求，試算表建議包含以下欄位：
  1. `藥品代碼`
  2. `藥品名稱`
  3. `藥品儲位`
  4. `數量(盒/罐/束)`
  5. `數量(片)`
  6. `數量(顆)`
  7. `單位含量(每盒幾顆)`
  8. `單位含量(每片幾顆)`
  9. `總顆數` (可於試算表中直接設定公式：`=D2*G2 + E2*H2 + F2`)

## 語音盤點流程設計 (System-Led Workflow)

有別於以往由人員主動報藥名，目前的流程設計為 **「助理主導 (System-Led)」**：

1. **啟動**：助理讀取試算表，從第一列（或上次中斷的列數）開始。
2. **報藥**：助理透過語音讀出該列的**藥品名稱**。
3. **清點**：藥師找到藥品後，清點數量並用語音回答（例如：「兩盒又三顆」）。
4. **確認與紀錄**：助理複誦確認數量，同時透過 Function Calling 將資料寫入 Google 試算表對應欄位。
5. **下一筆**：助理自動讀出下一列的藥品名稱。

**例外狀況處理 (Exception Handling)**：
- **找不到藥品**：若藥師找不到助理報的藥品，可用語音詢問：「這放在哪裡？」。助理會讀取該列的「藥品儲位」並語音告知。
- **多出的未列帳藥品**：若藥師發現手上有試算表沒列出的藥品，可主動說：「我要新增藥品，名稱是 OOO，數量是 X」。助理會呼叫 `append_new_drug` 工具，在試算表最下方新增一列並填入數量。

## 實作步驟 (Proposed Changes)

### Phase 1: 基礎建設與 UI 介面
- [NEW] `requirements.txt`: 包含 `google-genai`, `gspread`, `google-auth`, `pyaudio`, `customtkinter` 等。
- [NEW] `gui.py`: 實作設定畫面 (API Key, Prompt, Service Account JSON 路徑, Sheets ID) 及盤點主畫面 (Log、連線控制、麥克風選擇)。

### Phase 2: Google Sheets 模組 (`sheets_client.py`)
- [NEW] `sheets_client.py`:
  - `load_sheet_data`: 載入整個試算表的藥品資料（作為初始 Context）。
  - `update_drug_quantity(row_index, quantities)`: 更新指定列的數量。
  - `append_new_drug(name, quantities)`: 在表尾新增藥品與數量。
  - `get_drug_location(row_index)`: 取得指定藥品位置。

### Phase 3: Gemini Live API 模組 (`voice_agent.py`)
- [NEW] `voice_agent.py`:
  - 處理 WebSocket 連線 (`google-genai` SDK)。
  - 處理 Session Management (時間/Token 上限自動重連機制)。
  - 註冊 Function Calling 工具，綁定 `sheets_client.py` 的方法。
  - 實作「主動報藥」邏輯（維護一個 `current_row_index` 狀態）。

### Phase 4: 整合與測試
- [NEW] `main.py`: 將 GUI、Sheets Client 與 Voice Agent 整合。

## User Review Required

> [!IMPORTANT]  
> 1. **主導權變更確認**：流程改為「系統主導 (助理主動報藥)」的方式，我認為這是很好的改進，因為這能讓助理明確知道現在要填寫哪一列，減少辨識錯誤。請確認這符合您的預期。
> 2. **開發起點**：若上述計畫沒問題，我們將進入 Phase 1，開始撰寫 `requirements.txt` 及設計 UI (`gui.py`)。請給予核准！