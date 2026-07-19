# 文生語音 APP（TTS 配音）

一個本機運行的「主題 → 口語腳本 → 中文 TTS 語音」一條龍應用，專為台灣老師、教學者、Podcast 創作者設計。

支援單人解說、雙人 Podcast 對話、PDF 教材轉口播、YouTube 影片重新配音，以及上傳參考音檔做**音色複製**。

---

## 主要功能

- **多模式輸出**：單人解說 / 雙人 Podcast（小艾＋大維）/ 短影音
- **多種輸入來源**：直接給主題 / PDF 檔案 / YouTube 連結 / SRT 字幕
- **多家 LLM 支援**：
  - 本地：Ollama、LMStudio（OpenAI 相容）
  - 雲端：OpenAI、Anthropic、**Google Gemini 2.5**（flash / flash-lite / pro）
- **PDF 智慧解析**：雙欄偵測、頁首頁尾清理、Tesseract OCR fallback、品質報告
- **PDF 預覽編輯**：解析後可在前端編輯確認再生成（避免 LLM 亂講）
- **Gemini 直讀 PDF**：可選擇讓 Gemini 直接讀 PDF（多模態），429 配額用完自動降級到本地解析 + 本地 LLM
- **TTS 引擎可切換**：GPT-SoVITS v4（本地預設）/ **IndexTTS2**（本地中文情緒強化）/ **Qwen-CosyVoice**（雲端高品質與指令情緒）
- **6 種預設音色**：台灣女聲、台灣男聲、活潑女聲、沉穩男聲、溫暖男聲、元氣女聲
- **音色複製**：上傳一段參考音檔（5~10 秒）即可即時複製出自訂音色
- **YouTube 轉錄**：用 Faster-Whisper 自動把影片內容轉為文字

---

## 系統需求

- **作業系統**：Windows 10/11（PowerShell 5.1 以上）
- **Python**：自動由 uv 安裝（不需要您預先裝）
- **GPU**（強烈推薦）：NVIDIA + **≥ 6 GB VRAM**（v4 推論需求）
- **磁碟**：約 **15 GB**（含 5.3 GB GPT-SoVITS 權重 + 其他模型）
- **記憶體**：建議 ≥ 16 GB

---

## 安裝與啟動

### 第一步：安裝 GPT-SoVITS（一次性）

GPT-SoVITS 程式碼與權重不入 git，請執行專用安裝腳本：

```powershell
# 在專案根目錄
.\setup_gptsovits.ps1
```

這個腳本會：
1. `git clone` GPT-SoVITS 原始碼
2. 下載 **pretrained_models.zip（5.3 GB）** + **G2PWModel.zip（1 GB）**
3. 解壓到 `GPT-SoVITS/GPT_SoVITS/pretrained_models/`
4. 建立獨立 venv `runtime/gptsovits_venv/`，安裝 PyTorch 2.5.1（NVIDIA 自動裝 cu121）+ GPT-SoVITS 依賴
5. 起 api_v2.py smoke test，確認 9880 可連線

腳本可重複執行，已完成步驟自動跳過。

### 第二步：啟動主應用

```powershell
.\start.bat
```

第一次執行會自動：
1. 下載 uv（Python 套件管理器）
2. 安裝 Python 3.10 與主後端套件（含 Qwen/CosyVoice 需要的 `dashscope`）
3. 自動執行 GPT-SoVITS 安裝腳本，clone 官方 repo、下載 v4 pretrained/G2PW 權重、建立獨立 venv
4. 建立 IndexTTS2 獨立 venv、clone 官方 repo，並下載 `IndexTeam/IndexTTS-2` checkpoints（放在 `%LOCALAPPDATA%\TTSVoiceoverApp`，避開 Windows 中文路徑編碼問題）
5. 將 IndexTTS2 Python / checkpoints / config 路徑寫入 TTS 設定
6. 啟動後端 FastAPI 服務（port 8765）並自動開啟瀏覽器到 `http://localhost:8765`

GPT-SoVITS 與 IndexTTS2 首次安裝都需要下載大型模型，可能花較久。若暫時只想略過其中一個本地引擎，可先設定：

```powershell
$env:TTS_SKIP_GPTSOVITS_INSTALL = "1"  # 可選：略過 GPT-SoVITS
$env:TTS_SKIP_INDEXTTS2_INSTALL = "1"   # 可選：略過 IndexTTS2
.\start.bat
```

第一次合成時，若 TTS provider 使用 GPT-SoVITS，主後端會自動拉起 GPT-SoVITS api_v2.py（port 9880）。

### TTS 引擎選擇

前端「輸出設定」可直接選擇三種 TTS provider：

| Provider | 類型 | 適合用途 | 備註 |
|----------|------|----------|------|
| GPT-SoVITS v4 | 本地 | 穩定、已整合、預設 fallback | 首次 `start.bat` 會自動執行 `setup_gptsovits.ps1` |
| IndexTTS2 | 本地 | 中文情緒、角色語氣、自然口播 | 首次 `start.bat` 會自動安裝獨立 venv 並下載 checkpoints |
| Qwen / CosyVoice | 雲端 | 高品質中文、多方言、指令式情緒控制 | 需 DashScope/Qwen API Key；`start.bat` 會安裝 dashscope |

TTS 設定會存到 `%LOCALAPPDATA%\TTS配音APP\tts_settings.json`；IndexTTS2 的獨立 venv 與 checkpoints 預設存到 `%LOCALAPPDATA%\TTSVoiceoverApp`。API Key 不會回傳到前端，只顯示是否已設定。

### 第三步：確認預設音色音檔

GPT-SoVITS 是 zero-shot 引擎，每個音色需要一段 ref 音檔 + 對應逐字稿。

`manifests/models.json` 已定義 6 個預設音色，repo 已附上對應參考音檔：

```
manifests/preset_voices/
├── taiwan_female_warm.wav
├── taiwan_male_clear.wav
├── taiwan_female_lively.wav
├── taiwan_male_steady.wav
├── taiwan_male_warm.wav
└── taiwan_female_energetic.wav
```

若想替換成自己的聲音，可自行錄製 5~10 秒、台灣腔且清晰的單一說話者語音，覆蓋同名檔案；也可以在介面上傳參考音檔建立 cloned voice。

若預設音色檔不存在，後端會自動 fallback 使用第一個已 clone 的音色。

---

## 專案結構

```
專案-TTS配音/
├── start.bat / start.ps1     # Windows 主應用入口
├── setup_gptsovits.ps1       # GPT-SoVITS 安裝腳本
├── GPT-SoVITS/               # （由 setup 腳本 clone，不入 git）
├── backend/                  # FastAPI 後端
│   ├── app.py                # REST API 主程式
│   ├── audio.py              # TTS 合成流程（呼叫 gptsovits_service）
│   ├── gptsovits_service.py  # GPT-SoVITS 子行程管理 + HTTP 客戶端
│   ├── content.py            # LLM 腳本生成（含各家 provider）
│   ├── jobs.py               # 工作排程、腳本解析
│   ├── system_probe.py       # 硬體偵測（GPU/RAM/Ollama）
│   ├── runtime_manager.py    # 主後端環境安裝管理
│   ├── pdf_handler.py        # PDF 文字擷取
│   ├── video_handler.py      # YouTube / SRT 處理
│   └── requirements.txt
├── frontend/                 # 純靜態前端（HTML + JS）
└── manifests/
    ├── models.json           # 預設音色設定（ref_audio + prompt_text）
    ├── runtime.windows.json  # 主後端安裝清單
    └── preset_voices/        # 預設音色 ref 音檔（請自行準備）
```

執行階段才會建立的目錄（已加入 `.gitignore`）：
```
%LOCALAPPDATA%\TTS配音APP\
├── runtime/
│   ├── venv/                # 主後端 venv
│   └── gptsovits_venv/      # GPT-SoVITS 獨立 venv
├── models/                  # Faster-Whisper 模型
├── jobs/                    # 工作產出
├── uploads/                 # 使用者上傳檔
├── voices/                  # 複製音色
└── runtime/*.log            # 啟動 / GPT-SoVITS / 前端診斷 log
```

---

## API 端點概覽

| Method | Path | 用途 |
|--------|------|------|
| GET    | `/health` | 健康檢查 |
| GET    | `/system/check` | 硬體 + 已安裝元件偵測 |
| GET    | `/settings/llm` | 取得 LLM 設定 |
| POST   | `/settings/llm` | 更新 LLM 設定 |
| GET    | `/settings/llm/lmstudio/models` | 列出 LMStudio 已載入的模型 |
| POST   | `/settings/llm/test` | 測試 LLM 連線 |
| GET    | `/voices` | 列出所有可用音色 |
| POST   | `/voices/clone` | 上傳參考音檔，建立複製音色 |
| POST   | `/client-log` | 前端診斷事件 log（本機排查用） |
| POST   | `/jobs` | 建立配音工作 |
| GET    | `/jobs/{id}` | 查詢工作狀態 |
| GET    | `/jobs/{id}/events` | SSE 進度串流 |
| PUT    | `/jobs/{id}/script` | 修改腳本後重新合成 |
| POST   | `/jobs/{id}/approve` | 確認腳本，開始 TTS |
| GET    | `/jobs/{id}/download` | 下載 MP3 |
| POST   | `/upload` | 上傳 PDF / SRT / TXT |
| POST   | `/extract-pdf` | 解析 PDF 並回傳文字 + 品質報告（含 OCR fallback） |

GPT-SoVITS（內部使用，主後端自動呼叫）：

| Method | Path | 用途 |
|--------|------|------|
| POST   | `127.0.0.1:9880/tts` | 文字 + ref 音檔 → 語音 |
| GET    | `127.0.0.1:9880/set_gpt_weights` | 切換 GPT 模型 |
| GET    | `127.0.0.1:9880/set_sovits_weights` | 切換 SoVITS 模型 |

---

## 雙人 Podcast 角色設定

| 角色 | 名稱 | 個性 |
|------|------|------|
| 主持 A | 小艾 | 好奇的學生視角，問出真正的疑惑 |
| 主持 B | 大維 | 知識豐富的達人，用比喻和故事解釋 |

LLM 會輪流輸出 `主持A：...` / `主持B：...`，後端解析後分別套用兩種音色合成。

---

## 驗證與測試

本專案目前包含一組標準庫 `unittest`，用來驗證安全邊界與腳本合成前檢查：

```powershell
# 使用主應用 venv
& "$env:LOCALAPPDATA\TTS配音APP\runtime\venv\Scripts\python.exe" -m unittest tests.test_safety -v

# 快速語法檢查
python -m py_compile backend/app.py backend/audio.py backend/config.py backend/content.py backend/gptsovits_service.py backend/jobs.py backend/pdf_handler.py backend/runtime_manager.py backend/system_probe.py backend/video_handler.py tests/test_safety.py
```

---

## 已知限制

- GPT-SoVITS 為 zero-shot，**最終音色取決於 ref 音檔**；若預設 ref 音檔品質普通，產生的語音也會普通
- LLM 對「字數 = N 分鐘」的指令遵循度有限，實際長度可能與目標相差 2~3 倍（與所用模型強度有關）
- YouTube 模式需網路連線下載音訊，耗時較長
- v4 需 ≥ 6 GB VRAM；不足時請改用 v2（4 GB 即可，在 `GPT_SoVITS/configs/tts_infer.yaml` 切換）

---

## 目前進度與排查記憶

截至 v1.2.7（2026-07-19）：

- 三種 TTS provider 已整合：GPT-SoVITS v4、IndexTTS2、Qwen/CosyVoice。
- `start.bat` 首次啟動會準備主後端、GPT-SoVITS、IndexTTS2；Qwen/CosyVoice 只需額外填 API Key。
- 本機已驗證 GPT-SoVITS、IndexTTS2、主後端 smoke test 可啟動。
- 聲音複製問題目前定位：後端 `/voices/clone` 用程式直打可成功；使用者在 Chrome UI 上傳 `chiounew.wav` 時，前端 log 顯示 request 在進入 FastAPI 前就 `Failed to fetch`。
- v1.2.5 已把聲音複製上傳從 `fetch(FormData)` 改為 `File.arrayBuffer()` + `XMLHttpRequest(FormData)`，並保留更細 log。
- v1.2.7 已將 Google Gemini 預設模型升級為 `gemini-flash-latest`，並修正 `google_model` 空白或舊 `gemini-2.x/2.5` 預設值覆蓋新版預設的問題。
- Google API 目前已驗證：API Key 存在、模型可列出；`gemini-flash-latest` 可生成且實際指向 `gemini-3.5-flash`，`gemini-3.5-flash`、`gemini-3.1-flash-lite`、`gemini-3-flash-preview` 也可生成；`gemini-pro-latest` 會回 quota/billing 429。
- LMStudio 已驗證：/v1/models 與短測試可回應；若正式生成仍慢或失敗，優先檢查模型是否只輸出推理內容、是否需要更長生成時間。

聲音複製排查 log：

```text
%LOCALAPPDATA%\TTS配音APP\runtime\client_events.log
%LOCALAPPDATA%\TTS配音APP\runtime\voice_clone.log
```

若 UI 仍顯示「音色複製失敗：Failed to fetch」，先查看 `client_events.log` 末尾：

- `clone_click`：按鈕有觸發，會記錄檔名、大小、MIME type。
- `clone_file_read_success` / `clone_file_read_error`：瀏覽器是否讀得到本機音檔。
- `clone_xhr_start`：已改用 XHR 開始上傳。
- `clone_upload_error`：XHR 層中斷、timeout 或網路錯誤。

再查看 `voice_clone.log`：

- 有 `clone_request` 代表後端已收到，後續看 FFmpeg 或格式錯誤。
- 沒有 `clone_request` 代表瀏覽器/本機連線在進 FastAPI 前中斷。

---

## ⚠️ 套件版本相容性注意

主後端與 GPT-SoVITS 各自 venv 隔離，互不干擾。已驗證組合：

### 主後端 venv（runtime/venv）

| 套件     | 版本     | 備註            |
|----------|----------|-----------------|
| fastapi  | latest   |                 |
| uvicorn  | latest   | `[standard]` 變體 |
| httpx    | latest   | 呼叫 GPT-SoVITS 用 |

### GPT-SoVITS venv（runtime/gptsovits_venv）

| 套件          | 版本         | 備註                              |
|---------------|--------------|-----------------------------------|
| torch         | 2.8.0+cu128 / 2.5.1+cu121 | RTX 50 系列使用 cu128；其他 NVIDIA fallback cu121 |
| torchaudio    | 與 torch 同版本 | RTX 50 系列使用 2.8.0+cu128 |
| 其餘 GPT-SoVITS 依賴 | 由其 `requirements.txt` 決定 | setup 腳本會自動安裝              |

升級任何一個元件前，請先確認其餘元件仍能搭配。

---

## 變更紀錄

- **v1.2.7（2026-07-19）**：
  - **Google 模型預設再升級**：Google AI 預設改為 `gemini-flash-latest`，目前驗證會指向 `gemini-3.5-flash`
  - **舊模型自動升級**：`gemini-2.0/2.5` 舊預設值會自動回到 latest alias，避免 UI 或舊設定把模型降回 2.5
  - **Google 空回應診斷**：Gemini 回空正文時會顯示 `finishReason`，可辨識 `MAX_TOKENS` 等 token 不足情境
- **v1.2.6（2026-07-19）**：
  - **Gemini 預設模型升級**：Google AI 預設由 gemini-2.5-flash 升級為 gemini-3.5-flash，前端預設同步更新
  - **LLM 設定防呆**：google_model 等模型欄位若被舊設定或 UI 存成空字串，會自動回復預設，避免空 model 造成 Google 404
  - **Google API 排查記憶**：本機 key 可列模型；Flash 系列可生成，gemini-pro-latest 目前會回 quota/billing 429
- **v1.2.5（2026-07-19）**：
  - **聲音複製上傳改用 XHR**：前端先 `File.arrayBuffer()` 讀取本機音檔，再用 `XMLHttpRequest` 上傳 FormData，避開 Chrome 本機 File multipart fetch 中斷
  - **更細前端 log**：新增 `clone_file_read_*`、`clone_xhr_start`、`clone_upload_error`，方便定位 Failed to fetch 發生層級
- **v1.2.4（2026-07-19）**：
  - **聲音複製診斷 log**：新增 `/client-log`、`client_events.log`、`voice_clone.log`
  - **前端上傳保護**：API 改相對路徑，按鈕加 `type="button"` 與 `preventDefault()`，並提高靜態檔 cache-busting 版本
- **v1.2.3（2026-07-19）**：
  - **音檔格式支援擴充**：聲音複製支援 WAV / MP3 / M4A / AAC / OGG / FLAC / WEBM / MP4 與 `audio/*`
  - **錯誤透明化**：前端顯示後端 detail 或 HTTP status，後端記錄 clone failure
- **v1.2.2（2026-07-19）**：
  - **複製音色修正**：`/voices/clone` 改用安全唯一 voice_id，保留使用者輸入 label，避免中文名稱或重名覆蓋
  - **測試覆蓋**：新增中文音色名稱回歸測試
- **v1.1.1（2026-07-19）**：
  - **安全強化**：`/extract-pdf` 僅允許讀取上傳目錄內的 PDF，避免任意路徑讀取
  - **上傳防護**：PDF / SRT / TXT / 參考音檔改為分段寫入並加入大小上限，前端同步提示
  - **合成穩定性**：空腳本、空段落、空音訊串接會提早擋下並顯示可理解錯誤
  - **LLM 錯誤透明化**：OpenAI 相容、Anthropic、Google provider 不再吞掉 HTTP / 連線 / 回應格式錯誤
  - **安裝一致性**：前端自動安裝流程改用 `backend/requirements.txt`，避免只安裝部分依賴
  - **測試覆蓋**：新增 `tests/test_safety.py`，涵蓋路徑防護、上傳限制、段落解析與空合成防護
- **v1.2.1（2026-07-19）**：
  - **首次 start 完整安裝**：`start.bat` 現在會自動準備 GPT-SoVITS 與 IndexTTS2 本地環境，Qwen/CosyVoice SDK 也會隨主 requirements 安裝
  - **Windows 中文路徑修正**：IndexTTS2 改用 `%LOCALAPPDATA%\TTSVoiceoverApp` ASCII runtime，後端可讀取 PowerShell UTF-8 BOM 設定檔
  - **RTX 50 系列相容**：GPT-SoVITS 安裝會偵測 RTX 50 GPU 並改用 PyTorch `cu128`，避免 `no kernel image` 啟動錯誤
- **v1.2.0（2026-07-19）**：
  - **TTS provider 可切換**：新增 GPT-SoVITS / IndexTTS2 / Qwen-CosyVoice 三種語音引擎設定
  - **IndexTTS2 支援**：首次 `start.bat` 自動 clone 官方 repo、建立獨立 venv、下載 checkpoints，並使用情緒描述引導中文口播
  - **Qwen-CosyVoice 支援**：透過 DashScope/Qwen Cloud API 合成，支援模型、音色與語氣指令設定
- **v1.1.0（2026-05-20）**：
  - **LLM 防幻覺**：新增 strict mode（溫度 0.4、可做/不可做清單、關閉自動補寫），PDF 內容上限由 6000 → 30000 字
  - **PDF 智慧解析**：blocks + 雙欄偵測、頁首頁尾自動清理、Tesseract OCR fallback（掃描檔）、解析品質報告
  - **PDF 預覽編輯**：前端可在生成前看到解析結果並編輯，避免錯誤被一路帶下去
  - **Google Gemini 2.5 整合**：支援 flash / flash-lite / pro，可直讀 PDF（多模態），429 配額用完自動降級
  - **YouTube 自動安裝**：yt-dlp、faster-whisper 加入 `requirements.txt` 與 `system_probe` 偵測
- **2026-05-13**：TTS 引擎由 CosyVoice2-0.5B 換為 **GPT-SoVITS v4**（48 kHz、品質更好、原生 zero-shot）。新增 `setup_gptsovits.ps1` 一鍵安裝腳本。

---

## 授權

本專案為個人作品，原始碼以 MIT 授權釋出。

依賴元件各自的授權請參見：
- [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) — MIT
- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) — MIT
- [FastAPI](https://github.com/fastapi/fastapi) — MIT
