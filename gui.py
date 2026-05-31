import os
import json
import customtkinter as ctk
from tkinter import filedialog
import pyaudio
from sheets_client import SheetsClient
from voice_agent import VoiceAgent
CONFIG_FILE = "config.json"
DEFAULT_PROMPT = """你是一個專業的醫院藥局語音盤點助理。
你的任務是主導盤點流程，協助藥師有效率地完成工作。請嚴格遵守以下流程與規則：

【盤點流程】
1. 啟動：請直接從清單中「尚未盤點」的第一筆藥品開始，清楚讀出「藥品名稱」。若有藥師特別指示從哪裡開始，則聽從指示。
2. 等待：讀出藥名後，請立即停止說話並保持安靜，等待藥師回報數量。
3. 紀錄：聽到藥師親自回報數量後，簡短複誦確認，並**立刻呼叫 `update_drug_quantity` 工具**。
4. 下一筆：工具呼叫完畢後，請主動讀出下一個「尚未盤點」的藥品名稱。

【嚴格禁止事項 (非常重要！)】
- 絕對不可代替藥師回答！發問後必須停止說話，等待真實的語音輸入。
- 一次只能盤點一個藥品。在沒有收到真實藥師回報的數量前，嚴禁自行虛構數量、嚴禁自行呼叫更新工具、嚴禁擅自跳到下一個藥品。
- 絕對不要扮演藥師說話。
- 嚴禁加上任何醫療免責聲明 (例如：「藥物資訊僅供參考...」)。因為你現在是醫院內部盤點系統，不是在給病患醫療建議。

【例外狀況處理】
- 指定跳轉：如果藥師指示「跳過」或「盤點某某藥」，請直接從清單中找到該藥品繼續。
- 查詢資訊：如果藥師詢問儲位或單位含量，請直接從清單資訊中回答。
- 更新單位含量：如果藥師指示更新/修改該藥品的單位含量（例如「這盒是100顆裝的」、「更新單位含量為每片10顆」），請確認後立刻呼叫 `update_drug_quantity` 工具將其寫入。可同時或單獨更新數量與單位含量。
- 帳外藥品：如果藥師指示「新增藥品...」，請依序詢問藥師該藥品的：「藥品代碼(批價碼)」、「儲位」、「單位含量(每盒/罐/束幾顆)」、「單位含量(每片幾顆)」。若藥師回答不知道或沒有，請將該欄位留空(空字串)，絕對不要自己預設任何字詞(如 NEW 或 未列帳)。確認完畢後，呼叫 `append_new_drug`。
- 口誤更正：若藥師口誤或要求更正數量，請確認最終數量後再呼叫工具。呼叫工具時，**所有數量與含量參數必須嚴格使用「純阿拉伯數字」**(例如 7，絕對不可使用國字如「七」或「空」)。"""

class InventoryVoiceAssistantApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("盤點語音助理 (Inventory Voice Assistant)")
        self.geometry("800x650")
        
        # Load configs
        self.config_data = self.load_config()

        # Grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Main Tabview
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.tabview._segmented_button.configure(font=ctk.CTkFont(size=24, weight="bold"))
        
        self.tab_main = self.tabview.add("盤點作業")
        self.tab_settings = self.tabview.add("系統設定")

        self.setup_main_tab()
        self.setup_settings_tab()
        
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading config: {e}")
        return {
            "api_key": "",
            "system_prompt": DEFAULT_PROMPT,
            "sa_json_path": "",
            "spreadsheet_url": "",
            "worksheet_name": ""
        }

    def save_config(self):
        self.config_data["api_key"] = self.entry_api_key.get()
        self.config_data["system_prompt"] = self.textbox_prompt.get("1.0", "end-1c")
        self.config_data["sa_json_path"] = self.entry_sa_path.get()
        self.config_data["spreadsheet_url"] = self.entry_sheet_url.get()
        self.config_data["worksheet_name"] = self.combo_worksheet.get()
        
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, ensure_ascii=False, indent=4)
            self.log_message("系統設定已儲存。")
            self.tabview.set("盤點作業")
        except Exception as e:
            self.log_message(f"儲存設定失敗: {e}")
            self.tabview.set("盤點作業")

    def setup_settings_tab(self):
        # Settings Layout
        self.tab_settings.grid_columnconfigure(1, weight=1)
        self.tab_settings.grid_rowconfigure(4, weight=1)  # 讓 System Prompt 可以垂直延展

        # API Key
        ctk.CTkLabel(self.tab_settings, text="Gemini API Key:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.entry_api_key = ctk.CTkEntry(self.tab_settings, show="*")
        self.entry_api_key.grid(row=0, column=1, columnspan=2, padx=10, pady=10, sticky="ew")
        self.entry_api_key.insert(0, self.config_data.get("api_key", ""))

        # Service Account JSON
        ctk.CTkLabel(self.tab_settings, text="Service Account JSON:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.entry_sa_path = ctk.CTkEntry(self.tab_settings)
        self.entry_sa_path.grid(row=1, column=1, padx=10, pady=10, sticky="ew")
        self.entry_sa_path.insert(0, self.config_data.get("sa_json_path", ""))
        self.btn_browse_sa = ctk.CTkButton(
            self.tab_settings, 
            text="瀏覽...", 
            font=ctk.CTkFont(size=16),
            width=100,
            height=40,
            command=self.browse_sa_json
        )
        self.btn_browse_sa.grid(row=1, column=2, padx=10, pady=10)

        # Spreadsheet URL
        ctk.CTkLabel(self.tab_settings, text="Google 試算表網址/ID:").grid(row=2, column=0, padx=10, pady=10, sticky="w")
        self.entry_sheet_url = ctk.CTkEntry(self.tab_settings)
        self.entry_sheet_url.grid(row=2, column=1, columnspan=2, padx=10, pady=10, sticky="ew")
        self.entry_sheet_url.insert(0, self.config_data.get("spreadsheet_url", ""))

        # Worksheet Selection
        ctk.CTkLabel(self.tab_settings, text="指定工作表:").grid(row=3, column=0, padx=10, pady=10, sticky="w")
        ws_name = self.config_data.get("worksheet_name", "")
        self.combo_worksheet = ctk.CTkComboBox(self.tab_settings, values=[ws_name] if ws_name else [])
        self.combo_worksheet.grid(row=3, column=1, padx=10, pady=10, sticky="ew")
        self.combo_worksheet.set(ws_name)
        self.btn_fetch_ws = ctk.CTkButton(
            self.tab_settings, 
            text="取得工作表清單", 
            width=100,
            command=self.fetch_worksheets
        )
        self.btn_fetch_ws.grid(row=3, column=2, padx=10, pady=10)

        # System Prompt
        ctk.CTkLabel(self.tab_settings, text="System Prompt:").grid(row=4, column=0, padx=10, pady=10, sticky="nw")
        self.textbox_prompt = ctk.CTkTextbox(self.tab_settings)
        self.textbox_prompt.grid(row=4, column=1, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.textbox_prompt.insert("1.0", self.config_data.get("system_prompt", DEFAULT_PROMPT))

        # Save Button
        self.btn_save = ctk.CTkButton(
            self.tab_settings, 
            text="儲存設定", 
            font=ctk.CTkFont(size=20, weight="bold"),
            width=200,
            height=50,
            command=self.save_config
        )
        self.btn_save.grid(row=5, column=0, columnspan=3, pady=20)

    def browse_sa_json(self):
        filename = filedialog.askopenfilename(
            title="選擇 Service Account JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if filename:
            self.entry_sa_path.delete(0, "end")
            self.entry_sa_path.insert(0, filename)

    def fetch_worksheets(self):
        sa_path = self.entry_sa_path.get()
        url = self.entry_sheet_url.get()
        if not sa_path or not url:
            self.log_message("錯誤: 請先填寫 Service Account JSON 與試算表網址")
            return
        
        self.log_message("正在取得工作表清單...")
        try:
            names = SheetsClient.get_worksheet_names(sa_path, url)
            self.combo_worksheet.configure(values=names)
            if names:
                self.combo_worksheet.set(names[0])
            self.log_message(f"成功取得 {len(names)} 個工作表。")
        except Exception as e:
            self.log_message(f"取得工作表失敗: {e}")

    def setup_main_tab(self):
        self.tab_main.grid_columnconfigure(0, weight=1)
        self.tab_main.grid_rowconfigure(2, weight=1)

        # Top Control Frame
        self.frame_controls = ctk.CTkFrame(self.tab_main)
        self.frame_controls.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.frame_controls.grid_columnconfigure(1, weight=1)

        # Microphone Selection
        ctk.CTkLabel(self.frame_controls, text="麥克風:").grid(row=0, column=0, padx=10, pady=5, sticky="e")
        self.combo_mic = ctk.CTkComboBox(self.frame_controls, values=self.get_audio_device_list(input_device=True), width=300)
        self.combo_mic.grid(row=0, column=1, padx=10, pady=5, sticky="w")

        # Speaker/Headphone Selection
        ctk.CTkLabel(self.frame_controls, text="喇叭/耳機:").grid(row=1, column=0, padx=10, pady=5, sticky="e")
        self.combo_speaker = ctk.CTkComboBox(self.frame_controls, values=self.get_audio_device_list(input_device=False), width=300)
        self.combo_speaker.grid(row=1, column=1, padx=10, pady=5, sticky="w")

        # Start/Stop Button
        self.is_running = False
        self.btn_toggle = ctk.CTkButton(
            self.frame_controls, 
            text="▶ 開始連線", 
            font=ctk.CTkFont(size=28, weight="bold"), 
            width=220, 
            height=80, 
            fg_color="green", 
            hover_color="darkgreen", 
            command=self.toggle_connection
        )
        self.btn_toggle.grid(row=0, column=2, rowspan=3, padx=20, pady=10)

        # Half Duplex Checkbox
        self.var_half_duplex = ctk.BooleanVar(value=True)
        self.chk_half_duplex = ctk.CTkCheckBox(
            self.frame_controls, 
            text="防喇叭回音 (半雙工)", 
            variable=self.var_half_duplex,
            font=ctk.CTkFont(size=14)
        )
        self.chk_half_duplex.grid(row=0, column=3, rowspan=3, padx=10, pady=10)

        # Speaker Volume Slider
        ctk.CTkLabel(self.frame_controls, text="助理音量:").grid(row=2, column=0, padx=10, pady=5, sticky="e")
        self.frame_volume = ctk.CTkFrame(self.frame_controls, fg_color="transparent")
        self.frame_volume.grid(row=2, column=1, padx=10, pady=5, sticky="ew")
        self.frame_volume.grid_columnconfigure(0, weight=1)

        self.slider_volume = ctk.CTkSlider(self.frame_volume, from_=0.0, to=2.0, number_of_steps=20, command=self.update_volume_label)
        self.slider_volume.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="ew")
        self.slider_volume.set(1.0)

        self.lbl_volume = ctk.CTkLabel(self.frame_volume, text="1.0x", width=40)
        self.lbl_volume.grid(row=0, column=1, padx=0, pady=0, sticky="w")

        # Status Label
        self.lbl_status = ctk.CTkLabel(self.tab_main, text="狀態: 尚未連線", font=ctk.CTkFont(weight="bold"))
        self.lbl_status.grid(row=1, column=0, padx=10, pady=5, sticky="w")

        # Log Textbox
        self.textbox_log = ctk.CTkTextbox(self.tab_main, state="disabled")
        self.textbox_log.grid(row=2, column=0, padx=10, pady=10, sticky="nsew")

    def get_audio_device_list(self, input_device=True):
        devices = []
        try:
            p = pyaudio.PyAudio()
            info = p.get_host_api_info_by_index(0)
            numdevices = info.get('deviceCount')
            for i in range(0, numdevices):
                device_info = p.get_device_info_by_host_api_device_index(0, i)
                is_target_device = False
                
                if input_device and device_info.get('maxInputChannels') > 0:
                    is_target_device = True
                elif not input_device and device_info.get('maxOutputChannels') > 0:
                    is_target_device = True
                    
                if is_target_device:
                    name = device_info.get('name')
                    # Encode/decode to handle some garbled characters in Windows
                    try:
                        name = name.encode('cp1252').decode('utf-8')
                    except:
                        pass
                    devices.append(f"[{i}] {name}")
            p.terminate()
        except Exception as e:
            print(f"Error getting devices: {e}")
            devices = ["預設裝置"]
        
        return devices if devices else ["無可用裝置"]

    def update_volume_label(self, val):
        self.lbl_volume.configure(text=f"{val:.1f}x")
        if hasattr(self, "voice_agent") and self.voice_agent:
            self.voice_agent.set_volume(val)

    def toggle_connection(self):
        if not self.is_running:
            self.log_message("載入設定...")
            api_key = self.config_data.get("api_key")
            sa_json_path = self.config_data.get("sa_json_path")
            spreadsheet_url = self.config_data.get("spreadsheet_url")
            
            if not api_key or not sa_json_path or not spreadsheet_url:
                self.log_message("錯誤: 請至「系統設定」頁籤填寫 API Key、Service Account JSON 路徑與試算表網址！")
                return

            self.log_message("正在初始化 Google Sheets 連線...")
            try:
                ws_name = self.config_data.get("worksheet_name")
                self.sheets_client = SheetsClient(sa_json_path, spreadsheet_url, worksheet_name=ws_name)
                
                # Check if it loaded anything
                if ws_name:
                    self.log_message(f"已成功連接至工作表: {ws_name}")
            except Exception as e:
                self.log_message(f"試算表初始化失敗: {e}")
                return

            self.log_message("正在啟動 Gemini 語音助理...")
            try:
                mic_val = self.combo_mic.get()
                speaker_val = self.combo_speaker.get()
                
                self.voice_agent = VoiceAgent(
                    api_key=api_key,
                    config_data=self.config_data,
                    sheets_client=self.sheets_client,
                    log_callback=self.log_message,
                    mic_index=mic_val,
                    speaker_index=speaker_val,
                    half_duplex=self.var_half_duplex.get(),
                    volume=self.slider_volume.get()
                )
            except Exception as e:
                self.log_message(f"語音助理初始化失敗: {e}")
                return

            # Start
            self.is_running = True
            self.btn_toggle.configure(text="⏹ 結束連線", fg_color="red", hover_color="darkred")
            self.lbl_status.configure(text="狀態: 連線中...", text_color="green")
            
            self.voice_agent.start()
        else:
            # Stop
            self.is_running = False
            self.btn_toggle.configure(text="▶ 開始連線", fg_color="green", hover_color="darkgreen")
            self.lbl_status.configure(text="狀態: 已斷線", text_color="gray")
            
            if hasattr(self, "voice_agent") and self.voice_agent:
                self.voice_agent.stop()
                self.log_message("系統：語音助理已停止連線。")

    def log_message(self, message):
        self.textbox_log.configure(state="normal")
        self.textbox_log.insert("end", message + "\n")
        self.textbox_log.see("end")
        self.textbox_log.configure(state="disabled")
