import asyncio
import threading
import pyaudio
import array
from google import genai
from google.genai import types

class VoiceAgent:
    def __init__(self, api_key, config_data, sheets_client, log_callback, mic_index=None, speaker_index=None, half_duplex=True, volume=1.0):
        self.api_key = api_key
        self.config_data = config_data
        self.sheets_client = sheets_client
        self.log_callback = log_callback
        
        self.mic_index = mic_index
        self.speaker_index = speaker_index
        self.half_duplex = half_duplex
        self.is_speaking = False
        self.volume = volume
        
        # Audio formats required by Gemini Live API
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.SEND_SAMPLE_RATE = 16000
        self.RECEIVE_SAMPLE_RATE = 24000
        self.CHUNK_SIZE = 1024
        
        self.pya = pyaudio.PyAudio()
        
        self.is_running = False
        self.is_tool_call_pending = False
        self.loop = None
        self.thread = None
        
        # 解析選單中 "[0] 裝置名稱" 的索引值
        if isinstance(self.mic_index, str) and "[" in self.mic_index:
            try:
                self.mic_index = int(self.mic_index.split("[")[1].split("]")[0])
            except:
                self.mic_index = None
                
        if isinstance(self.speaker_index, str) and "[" in self.speaker_index:
            try:
                self.speaker_index = int(self.speaker_index.split("[")[1].split("]")[0])
            except:
                self.speaker_index = None

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.is_running = False
        if self.loop:
            for task in asyncio.all_tasks(self.loop):
                task.cancel()
            self.loop.call_soon_threadsafe(self.loop.stop)

    def _run_async_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main_task())
        except asyncio.CancelledError:
            pass
        finally:
            self.pya.terminate()
            self.log_callback("系統：連線已安全關閉。")

    def _build_tools(self):
        return [{"function_declarations": [
            {
                "name": "update_drug_quantity",
                "description": "當藥師回報數量或修改包裝單位含量（每盒幾顆/每片幾顆）時，更新目前列(row_index)的數量或單位含量",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "row_index": {"type": "INTEGER", "description": "要更新的試算表列號(必須大於等於2)"},
                        "box": {"type": "INTEGER", "description": "數量(盒/罐/束)，必須是純數字"},
                        "blister": {"type": "INTEGER", "description": "數量(片)，必須是純數字"},
                        "pill": {"type": "INTEGER", "description": "數量(顆)，必須是純數字"},
                        "unit_box": {"type": "INTEGER", "description": "單位含量(每盒/罐/束幾顆)，必須是純數字"},
                        "unit_blister": {"type": "INTEGER", "description": "單位含量(每片幾顆)，必須是純數字"}
                    },
                    "required": ["row_index"]
                }
            },
            {
                "name": "append_new_drug",
                "description": "若藥師盤點到試算表上沒有的藥品，新增該藥品",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING", "description": "藥品名稱"},
                        "box": {"type": "INTEGER", "description": "數量(盒/罐/束)，必須是純數字"},
                        "blister": {"type": "INTEGER", "description": "數量(片)，必須是純數字"},
                        "pill": {"type": "INTEGER", "description": "數量(顆)，必須是純數字"},
                        "code": {"type": "STRING", "description": "藥品代碼/批價碼"},
                        "location": {"type": "STRING", "description": "儲位"},
                        "unit_box": {"type": "INTEGER", "description": "單位含量(每盒/罐/束幾顆)，必須是純數字"},
                        "unit_blister": {"type": "INTEGER", "description": "單位含量(每片幾顆)，必須是純數字"}
                    },
                    "required": ["name"]
                }
            }
        ]}]

    async def _main_task(self):
        client = genai.Client(api_key=self.api_key)
        model = "gemini-3.1-flash-live-preview"
        
        # 取得試算表 Context
        self.log_callback("系統：正在讀取試算表作為上下文...")
        try:
            drug_data = await asyncio.to_thread(self.sheets_client.load_sheet_data)
            context = "目前試算表上的藥品清單與資訊如下：\n"
            for d in drug_data:
                context += f"列號:{d['row_index']}, 代碼:{d['代碼']}, 藥名:{d['名稱']}, 狀態:{d['盤點狀態']}, 單位:{d['包裝單位']}, 儲位:{d['儲位']}\n"
        except Exception as e:
            self.log_callback(f"錯誤：讀取試算表失敗 {e}")
            return

        sys_prompt = self.config_data.get("system_prompt", "")
        full_instruction = sys_prompt + "\n\n" + context

        config = {
            "response_modalities": ["AUDIO"],
            "system_instruction": full_instruction,
            "tools": self._build_tools(),
            "output_audio_transcription": {},
            "input_audio_transcription": {},
        }

        self.audio_queue_output = asyncio.Queue()
        self.audio_queue_mic = asyncio.Queue(maxsize=5)
        
        self.log_callback("系統：正在連接 Gemini 伺服器...")
        try:
            async with client.aio.live.connect(model=model, config=config) as live_session:
                self.log_callback("系統：連線成功！開始盤點。")
                t1 = asyncio.create_task(self._listen_mic())
                t2 = asyncio.create_task(self._send_realtime(live_session))
                t3 = asyncio.create_task(self._receive_loop(live_session))
                t4 = asyncio.create_task(self._play_speaker())
                await asyncio.gather(t1, t2, t3, t4)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log_callback(f"錯誤：Gemini 連線失敗 {e}")

    async def _listen_mic(self):
        kwargs = {
            "format": self.FORMAT,
            "channels": self.CHANNELS,
            "rate": self.SEND_SAMPLE_RATE,
            "input": True,
            "frames_per_buffer": self.CHUNK_SIZE
        }
        if self.mic_index is not None:
            kwargs["input_device_index"] = self.mic_index
        else:
            mic_info = self.pya.get_default_input_device_info()
            kwargs["input_device_index"] = mic_info["index"]

        try:
            audio_stream = await asyncio.to_thread(self.pya.open, **kwargs)
        except Exception as e:
            self.log_callback(f"麥克風開啟失敗: {e}")
            return

        read_kwargs = {"exception_on_overflow": False} if __debug__ else {}
        try:
            while self.is_running:
                data = await asyncio.to_thread(audio_stream.read, self.CHUNK_SIZE, **read_kwargs)
                if not self.audio_queue_mic.full():
                    await self.audio_queue_mic.put({"data": data, "mime_type": "audio/pcm"})
        except asyncio.CancelledError:
            pass
        finally:
            audio_stream.close()

    async def _send_realtime(self, session):
        try:
            while self.is_running:
                msg = await self.audio_queue_mic.get()
                if self.half_duplex and getattr(self, "is_speaking", False):
                    continue
                if not getattr(self, "is_tool_call_pending", False):
                    await session.send_realtime_input(audio=msg)
        except asyncio.CancelledError:
            pass

    async def _play_speaker(self):
        kwargs = {
            "format": self.FORMAT,
            "channels": self.CHANNELS,
            "rate": self.RECEIVE_SAMPLE_RATE,
            "output": True,
        }
        if self.speaker_index is not None:
            kwargs["output_device_index"] = self.speaker_index

        try:
            stream = await asyncio.to_thread(self.pya.open, **kwargs)
        except Exception as e:
            self.log_callback(f"喇叭開啟失敗: {e}")
            return

        try:
            while self.is_running:
                bytestream = await self.audio_queue_output.get()
                if self.volume != 1.0:
                    bytestream = self._adjust_volume(bytestream, self.volume)
                    
                if self.half_duplex:
                    self.is_speaking = True
                    
                await asyncio.to_thread(stream.write, bytestream)
                
                if self.half_duplex and self.audio_queue_output.empty():
                    # 小幅延遲等待喇叭餘音消散
                    await asyncio.sleep(0.2)
                    self.is_speaking = False
        except asyncio.CancelledError:
            pass
        finally:
            stream.close()

    def set_volume(self, val):
        self.volume = val

    def _adjust_volume(self, data, volume):
        try:
            a = array.array('h', data)
            for i in range(len(a)):
                val = int(a[i] * volume)
                if val > 32767:
                    val = 32767
                elif val < -32768:
                    val = -32768
                a[i] = val
            return a.tobytes()
        except Exception as e:
            return data

    async def _receive_loop(self, session):
        assistant_buffer = ""
        user_buffer = ""
        last_was_input = False
        try:
            while self.is_running:
                turn = session.receive()
                async for response in turn:
                    if not self.is_running:
                        break
                        
                    # Handle Tool Calls
                    if response.tool_call:
                        self.is_tool_call_pending = True
                        try:
                            function_responses = []
                            for fc in response.tool_call.function_calls:
                                args = fc.args
                                name = fc.name
                                result_text = "ok"
                                
                                try:
                                    if name == "update_drug_quantity":
                                        self.log_callback(f"系統：助理正在更新第 {args.get('row_index')} 列的數量或單位含量...")
                                        success = await asyncio.to_thread(
                                            self.sheets_client.update_drug_quantity,
                                            row_index=args.get('row_index'),
                                            box=args.get('box'),
                                            blister=args.get('blister'),
                                            pill=args.get('pill'),
                                            unit_box=args.get('unit_box'),
                                            unit_blister=args.get('unit_blister')
                                        )
                                        result_text = "Success" if success else "Failed"
                                        
                                    elif name == "append_new_drug":
                                        self.log_callback(f"系統：助理正在新增未列帳藥品: {args.get('name')}")
                                        row_idx = await asyncio.to_thread(
                                            self.sheets_client.append_new_drug,
                                            name=args.get('name'),
                                            box=args.get('box'),
                                            blister=args.get('blister'),
                                            pill=args.get('pill'),
                                            code=args.get('code'),
                                            location=args.get('location'),
                                            unit_box=args.get('unit_box'),
                                            unit_blister=args.get('unit_blister')
                                        )
                                        result_text = f"Success. Row index is {row_idx}"
                                    else:
                                        self.log_callback(f"系統：警告！收到未知的工具呼叫名稱: {name}")
                                        result_text = "Error: Unknown tool"
                                except Exception as e:
                                    self.log_callback(f"系統：工具執行錯誤 ({name}): {e}")
                                    result_text = f"Error: {e}"
                                    
                                function_responses.append(types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response={"result": result_text}
                                ))
                                
                            if function_responses:
                                await session.send_tool_response(function_responses=function_responses)
                        finally:
                            self.is_tool_call_pending = False
                    
                    # Handle Audio and Text
                    sc = response.server_content
                    if not sc:
                        continue
                        
                    if sc.model_turn:
                        for part in sc.model_turn.parts:
                            if part.inline_data and isinstance(part.inline_data.data, bytes):
                                self.audio_queue_output.put_nowait(part.inline_data.data)
                                
                    if sc.output_transcription:
                        t = sc.output_transcription.text
                        if t.strip():
                            self.log_callback(f"助理: {t.strip()}")
                                
                    if sc.input_transcription:
                        t = sc.input_transcription.text
                        if t.strip():
                            self.log_callback(f"藥師: {t.strip()}")
                                
                # Clear queue on interruption
                while not self.audio_queue_output.empty():
                    self.audio_queue_output.get_nowait()
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log_callback(f"系統：接收資料時發生錯誤: {e}")
