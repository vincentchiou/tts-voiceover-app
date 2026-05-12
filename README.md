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
- **TTS 引擎**：CosyVoice2-0.5B（中文表情豐富，使用 `inference_instruct2`）
- **6 種預設音色**：台灣女聲、台灣男聲、活潑女聲、沉穩男聲、溫暖男聲、元氣女聲
- **音色複製**：上傳一段參考音檔即可複製出自訂音色
- **YouTube 轉錄**：用 Faster-Whisper 自動把影片內容轉為文字

---

## 系統需求

- **作業系統**：Windows 10/11
- **Python**：自動由 uv 安裝（不需要您預先裝）
- **GPU**（推薦）：NVIDIA + ≥ 4GB VRAM；無 GPU 也可跑（CPU 模式較慢）
- **磁碟**：約 6 GB（含模型）
- **記憶體**：建議 ≥ 8 GB

---

## 安裝與啟動

```powershell
# 1. 雙擊 start.bat（或於 PowerShell 執行）
.\start.bat
```

首次執行會自動：
1. 下載 uv（Python 套件管理器）
2. 安裝 Python 3.10 與所需套件
3. 啟動後端 FastAPI 服務（port 8765）
4. 自動開啟瀏覽器到 `http://localhost:8765`

第一次使用，請接著在介面內：
1. 選擇 **LLM 來源**（Ollama / LMStudio / OpenAI / Anthropic）
2. 下載 **CosyVoice2-0.5B** 模型（≈ 1.5 GB）
3. 若需要 YouTube 轉錄，再下載 **Faster-Whisper-Medium**

---

## 專案結構

```
專案-TTS配音/
├── start.bat              # Windows 入口
├── start.ps1              # PowerShell 啟動腳本
├── backend/               # FastAPI 後端
│   ├── app.py             # REST API 主程式
│   ├── audio.py           # CosyVoice2 合成與音檔處理
│   ├── content.py         # LLM 腳本生成（含各家 provider）
│   ├── jobs.py            # 工作排程、腳本解析
│   ├── system_probe.py    # 硬體偵測（GPU/RAM/Ollama）
│   ├── runtime_manager.py # 模型 / 環境安裝管理
│   ├── pdf_handler.py     # PDF 文字擷取
│   ├── video_handler.py   # YouTube / SRT 處理
│   └── requirements.txt
├── frontend/              # 純靜態前端（HTML + JS）
│   ├── index.html
│   ├── app.js
│   └── styles.css
└── manifests/
    └── models.json        # 模型清單 + 預設音色 instruct
```

執行階段才會建立的目錄（已加入 `.gitignore`）：
```
%LOCALAPPDATA%\TTS_App\
├── runtime/   # Python venv + CosyVoice repo
├── models/    # 下載的模型
├── jobs/      # 工作產出（腳本、segments、output.mp3）
├── uploads/   # 使用者上傳檔
└── voices/    # 複製音色
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

---

## 雙人 Podcast 角色設定

| 角色 | 名稱 | 個性 |
|------|------|------|
| 主持 A | 小艾 | 好奇的學生視角，問出真正的疑惑 |
| 主持 B | 大維 | 知識豐富的達人，用比喻和故事解釋 |

LLM 會輪流輸出 `主持A：...` / `主持B：...`，後端解析後分別套用兩種音色合成。

---

## 已知限制

- CosyVoice2 沒有 SFT 預設音色，所有音色都透過 `inference_instruct2` + 參考音檔模擬，**語氣會受參考音檔影響**
- LLM 對「字數 = N 分鐘」的指令遵循度有限，實際長度可能與目標相差 2~3 倍（與所用模型強度有關）
- YouTube 模式需網路連線下載音訊，耗時較長

---

## ⚠️ 套件版本相容性注意

CosyVoice2 對 PyTorch / transformers / torchvision 的版本組合**很敏感**，
本專案已驗證可運作的版本組合如下：

| 套件         | 版本         | 備註                                   |
|--------------|--------------|----------------------------------------|
| torch        | 2.5.1+cu121  | NVIDIA：搭配 CUDA 12.1 wheel           |
| torchaudio   | 2.5.1+cu121  | 必須與 torch 同版本                     |
| torchvision  | 0.20.1+cu121 | 必須與 torch 同版本（否則 `nms` 報錯）  |
| transformers | 4.46.3       | **5.x 會破壞** CosyVoice2 的 Qwen2 引用 |

升級任何一個元件前，請先確認其餘三者仍能搭配。常見踩雷情境：

- `transformers >= 5.0`：CosyVoice2 內部以舊式路徑載入 `Qwen2ForCausalLM`，會出現 `Could not import module 'Qwen2ForCausalLM'`。
- `torch` 與 `torchvision` 大版本不同步：載入時報 `operator torchvision::nms does not exist`。
- 用 CPU 版 torch（`+cpu`）跑 NVIDIA 機器：`torch.cuda.is_available()` 為 False，雖能跑但極慢，且 `transformers` 可能拒絕載入。

若將來 CosyVoice 官方升級到支援新版 transformers，請同步調整 [runtime_manager.py](backend/runtime_manager.py) 中的版本鎖定。

---

## 授權

本專案為個人作品，原始碼以 MIT 授權釋出。

依賴元件各自的授權請參見：
- [CosyVoice2](https://github.com/FunAudioLLM/CosyVoice) — Apache-2.0
- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) — MIT
- [FastAPI](https://github.com/fastapi/fastapi) — MIT
