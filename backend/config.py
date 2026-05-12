"""
config.py — 路徑管理與全域設定
所有路徑都從 APP_HOME 衍生，確保可攜性
"""

import os
from pathlib import Path


def _get_app_home() -> Path:
    """取得 APP_HOME 路徑，優先使用環境變數覆蓋"""
    custom = os.environ.get("TTS_APP_HOME")
    if custom:
        return Path(custom)
    # Windows 預設：%LOCALAPPDATA%\TTS配音APP
    local_app_data = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return Path(local_app_data) / "TTS配音APP"


def _get_repo_dir() -> Path:
    """取得專案根目錄（程式碼所在位置）"""
    custom = os.environ.get("TTS_REPO_DIR")
    if custom:
        return Path(custom)
    # 預設：此檔案往上兩層
    return Path(__file__).parent.parent


# ── 主要路徑 ──────────────────────────────────────────────

APP_HOME   = _get_app_home()
REPO_DIR   = _get_repo_dir()

# 執行環境（Python + 模型都放這裡）
RUNTIME_DIR   = APP_HOME / "runtime"
UV_EXE        = RUNTIME_DIR / "uv" / "uv.exe"
PYTHON_DIR    = RUNTIME_DIR / "python"
VENV_DIR      = RUNTIME_DIR / "venv"
FFMPEG_DIR    = RUNTIME_DIR / "ffmpeg"
FFMPEG_EXE    = FFMPEG_DIR / "bin" / "ffmpeg.exe"

# 模型存放
MODELS_DIR        = APP_HOME / "models"
COSYVOICE_DIR     = MODELS_DIR / "CosyVoice2-0.5B"
WHISPER_DIR       = MODELS_DIR / "faster-whisper-medium"
COSYVOICE_REPO    = RUNTIME_DIR / "CosyVoice"  # git clone 位置

# 工作輸出
JOBS_DIR    = APP_HOME / "jobs"
UPLOADS_DIR = APP_HOME / "uploads"    # 上傳的 PDF、SRT、參考音檔
VOICES_DIR  = APP_HOME / "voices"     # 複製音色存放

# 暫存下載
DOWNLOADS_DIR = APP_HOME / "downloads"

# Manifests（隨程式碼發佈）
MANIFESTS_DIR = REPO_DIR / "manifests"

# 前端靜態檔
FRONTEND_DIR = REPO_DIR / "frontend"

# ── 安裝標記檔 ────────────────────────────────────────────
MARKER_FFMPEG       = RUNTIME_DIR / ".ffmpeg-installed"
MARKER_COSYVOICE    = RUNTIME_DIR / ".cosyvoice-installed"
MARKER_WHISPER      = RUNTIME_DIR / ".whisper-installed"
MARKER_YTDLP        = RUNTIME_DIR / ".ytdlp-installed"

# ── 伺服器設定 ────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = int(os.environ.get("TTS_PORT", "8765"))


LLM_SETTINGS_FILE = APP_HOME / "llm_settings.json"

def ensure_dirs():
    """確保所有必要資料夾存在"""
    for d in [APP_HOME, RUNTIME_DIR, MODELS_DIR, JOBS_DIR,
              UPLOADS_DIR, VOICES_DIR, DOWNLOADS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def ffmpeg_exe() -> Path:
    """取得 FFmpeg 執行檔路徑（先找內建，再找系統 PATH）"""
    if FFMPEG_EXE.exists():
        return FFMPEG_EXE
    # 嘗試系統 PATH
    import shutil
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return Path(sys_ffmpeg)
    return FFMPEG_EXE  # 即使不存在也回傳，讓呼叫端處理錯誤
