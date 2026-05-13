# 文生語音 APP（TTS 配音）

一個本機運行的「主題 → 口語腳本 → 中文 TTS 語音」一條龍應用，專為台灣老師、教學者、Podcast 創作者設計。

支援單人解說、雙人 Podcast 對話、PDF 教材轉口播、YouTube 影片重新配音，以及上傳參考音檔做**音色複製**。

---

## 主要功能

- **多模式輸出**：單人解說 / 雙人 Podcast（小艾＋大維）/ 短影音
- **多種輸入來源**：直接給主題 / PDF 檔案 / YouTube 連結 / SRT 字幕
- **多家 LLM 支援**：
  - 本地：Ollama、LMStudio（OpenAI 相容）
  - 雲端：OpenAI、Anthropic
- **TTS 引擎**：**GPT-SoVITS v4**（48kHz 高品質中文 TTS + zero-shot 聲音複製）
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
2. 安裝 Python 3.10 與主後端套件
3. 啟動後端 FastAPI 服務（port 8765）
4. 自動開啟瀏覽器到 `http://localhost:8765`

第一次合成時，主後端會自動拉起 GPT-SoVITS api_v2.py（port 9880）。

### 第三步：準備預設音色音檔（可選）

GPT-SoVITS 是 zero-shot 引擎，每個音色需要一段 ref 音檔 + 對應逐字稿。

`manifests/models.json` 已定義 6 個預設音色，對應檔案放在：

```
manifests/preset_voices/
├── taiwan_female_warm.wav
├── taiwan_male_clear.wav
├── taiwan_female_lively.wav
├── taiwan_male_steady.wav
├── taiwan_male_warm.wav
└── taiwan_female_energetic.wav
```

**目前尚未附上**，建議方式：
- 自己錄 6 段 5~10 秒、台灣腔的清晰語音，照上面檔名放好
- 或在介面上傳一段做「音色複製」，建立的 cloned voice 即可使用
- 或從 HF Common Voice / 公開語料抓台灣腔片段（每段 5~10 秒、單一說話者）

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
└── voices/                  # 複製音色
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
| POST   | `/jobs` | 建立配音工作 |
| GET    | `/jobs/{id}` | 查詢工作狀態 |
| GET    | `/jobs/{id}/events` | SSE 進度串流 |
| PUT    | `/jobs/{id}/script` | 修改腳本後重新合成 |
| POST   | `/jobs/{id}/approve` | 確認腳本，開始 TTS |
| GET    | `/jobs/{id}/download` | 下載 MP3 |
| POST   | `/upload` | 上傳 PDF / SRT / TXT |

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

## 已知限制

- GPT-SoVITS 為 zero-shot，**最終音色取決於 ref 音檔**；若預設 ref 音檔品質普通，產生的語音也會普通
- LLM 對「字數 = N 分鐘」的指令遵循度有限，實際長度可能與目標相差 2~3 倍（與所用模型強度有關）
- YouTube 模式需網路連線下載音訊，耗時較長
- v4 需 ≥ 6 GB VRAM；不足時請改用 v2（4 GB 即可，在 `GPT_SoVITS/configs/tts_infer.yaml` 切換）

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
| torch         | 2.5.1+cu121  | NVIDIA：搭配 CUDA 12.1 wheel       |
| torchaudio    | 2.5.1+cu121  | 必須與 torch 同版本                 |
| 其餘 GPT-SoVITS 依賴 | 由其 `requirements.txt` 決定 | setup 腳本會自動安裝              |

升級任何一個元件前，請先確認其餘元件仍能搭配。

---

## 變更紀錄

- **2026-05-13**：TTS 引擎由 CosyVoice2-0.5B 換為 **GPT-SoVITS v4**（48 kHz、品質更好、原生 zero-shot）。新增 `setup_gptsovits.ps1` 一鍵安裝腳本。

---

## 授權

本專案為個人作品，原始碼以 MIT 授權釋出。

依賴元件各自的授權請參見：
- [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) — MIT
- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) — MIT
- [FastAPI](https://github.com/fastapi/fastapi) — MIT
