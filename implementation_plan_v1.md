# 盤點語音助理 (Inventory Voice Assistant) 實作計畫
這是一個專為藥師設計的語音盤點桌面應用程式，透過語音與 Gemini 互動，並自動更新 Google 試算表上的盤點資料。
## 背景與目標
取代原本需要兩人一組的盤點流程（一人清點、一人紀錄），現在只需一人清點並用語音說出數量，程式會透過 Gemini Live API 辨識語音、理解意圖，並自動更新雲端的 Google 試算表。
> [!IMPORTANT]
> ## 需使用者確認的開放性問題 (Open Questions)
> 1. **Python 執行環境**：您提到醫院電腦無法安裝 `.exe`，請問醫院電腦是否已經安裝了 Python？或者是我們需要準備一份「免安裝版 (Portable)」的 Python 環境，讓您可以直接用隨身碟或放在某個資料夾點擊 `bat` 檔執行？
> 2. **Google 試算表權限**：程式需要讀寫 Google 試算表，通常會使用「服務帳戶 (Service Account)」的金鑰 (JSON 檔案)。您是否已經熟悉如何去 Google Cloud Console 申請 Service Account 並將試算表共用給該 Service Account 的 Email？（若不熟悉，我後續可以提供詳細步驟）。
> 3. **語音輸入設備**：盤點時，藥師會配戴藍牙耳機麥克風還是使用筆電內建麥克風？環境噪音是否會很大？
> 4. **藥品搜尋邏輯**：用語音盤點時，藥師通常是唸「藥品代碼」、「藥品名稱」還是「儲位」？例如：「我要盤點 Panadol」或是「我要盤點代碼 12345」。
## 系統架構與技術選型
1. **核心語言與介面**
   - **Python 3.10+** 作為主要語言。
   - **GUI (圖形化介面)**：使用 `customtkinter` (基於 Tkinter 的現代化 UI) 或簡單的 `tkinter`，提供一個簡潔的畫面，包含「開始/停止盤點」按鈕、目前狀態顯示、以及系統對話文字紀錄。
2. **語音與 AI (Gemini Live API)**
   - 使用 Google 最新的 `google-genai` SDK，透過 **Multimodal Live API (WebSocket)** 建立即時雙向語音通道。
   - 使用 `pyaudio` 進行麥克風收音與喇叭/耳機播放。
   - **Function Calling (工具呼叫)**：提供工具函數給 Gemini，當 Gemini 聽懂藥師要更新某個藥品的數量時，自動呼叫該函數。
3. **資料儲存 (Google Sheets API)**
   - 使用 `gspread` 與 `google-auth` 套件。
   - 應用程式啟動時，先讀取試算表中的藥品清單（代碼、名稱、儲位、單位含量），作為 Gemini 的上下文資訊，幫助 Gemini 更精準地辨識藥品名稱。
   - 當 Gemini 觸發更新函數時，透過 `gspread` 寫入對應列的數量欄位。
## 試算表欄位結構規劃
為符合您的需求，試算表建議包含以下欄位：
1. `藥品代碼`
2. `藥品名稱`
3. `藥品儲位`
4. `數量(盒/罐/束)`
5. `數量(片)`
6. `數量(顆)`
7. `單位含量(每盒幾顆)`
8. `單位含量(每片幾顆)`
9. `總顆數` (可於試算表中直接設定公式：`=D2*G2 + E2*H2 + F2`)
## 實作步驟 (Proposed Changes)
### 1. Google Sheets 存取模組 (`sheets_client.py`)
- [NEW] `sheets_client.py`: 負責初始化 Google 認證，提供讀取所有藥品資料 (`get_all_drugs`) 與更新特定藥品數量 (`update_drug_quantity`) 的方法。
### 2. Gemini Live API 與語音模組 (`voice_agent.py`)
- [NEW] `voice_agent.py`: 處理 `google-genai` 的 Live API 連線。
- 負責麥克風收音 (Audio In) 串流發送給 Gemini，並接收 Gemini 的語音回應 (Audio Out) 播放給使用者。
- 註冊 `update_inventory(keyword, box, blister, pill)` 工具，讓 Gemini 可以呼叫。
### 3. 使用者介面 (`main.py` & `gui.py`)
- [NEW] `main.py`: 程式進入點。
- [NEW] `gui.py`: 提供簡單的桌面視窗，包含：
  - Google 試算表網址輸入框或載入設定按鈕。
  - 麥克風測試/選擇。
  - 「開始連線」與「結束連線」按鈕。
  - 即時日誌 (Log) 顯示更新狀態。
### 4. 設定檔與相依套件 (`requirements.txt` & `.env`)
- [NEW] `requirements.txt`: 包含 `google-genai`, `gspread`, `google-auth`, `pyaudio`, `customtkinter` 等。
- [NEW] `.env` (範例): 儲存 `GEMINI_API_KEY` 以及試算表 ID。
## 驗證計畫 (Verification Plan)
### 本地測試
1. 建立一個測試用的 Google 試算表，填入數筆假藥品資料。
2. 啟動 `main.py`，設定 API Key 與試算表授權。
3. 按下開始錄音，對著麥克風說：「我要盤點普拿疼，數量是 2盒、3片、4顆」。
4. 聆聽 Gemini 的語音回應是否正確確認，並檢查試算表上的資料是否即時更新。
### 模擬例外狀況測試
1. 語音辨識不清或藥品名稱不存在時，測試 Gemini 是否會反問藥師確認。
2. 只說「5顆」時，測試程式是否只更新「顆」的欄位，其他單位保持空白或0。