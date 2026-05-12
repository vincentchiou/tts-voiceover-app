"""
video_handler.py — YouTube 下載 + 語音轉錄 + SRT 解析
使用 yt-dlp 下載音訊，faster-whisper 做本地 ASR 轉錄
"""

import re
import subprocess
import sys
from pathlib import Path

import config


def download_audio(url: str, output_dir: Path) -> Path:
    """下載 YouTube（或其他平台）音訊，回傳 WAV 檔路徑"""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "audio.%(ext)s")

    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp 未安裝，請先完成環境安裝")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
            "preferredquality": "192",
        }],
        "ffmpeg_location": str(config.ffmpeg_exe().parent),
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # 找到輸出的 WAV 檔
    wav_files = list(output_dir.glob("audio.wav"))
    if not wav_files:
        raise RuntimeError("音訊下載失敗，找不到輸出檔案")
    return wav_files[0]


def transcribe(audio_path: Path) -> str:
    """使用 faster-whisper 將音訊轉錄成文字"""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("faster-whisper 未安裝，請先完成環境安裝")

    # 選擇裝置
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    model_path = str(config.WHISPER_DIR)
    if not config.WHISPER_DIR.exists():
        # 使用線上模型（首次自動下載到 HF 快取）
        model_path = "medium"

    model = WhisperModel(model_path, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        str(audio_path),
        language="zh",
        beam_size=5,
        vad_filter=True,
    )

    lines = [seg.text.strip() for seg in segments if seg.text.strip()]
    return "\n".join(lines)


def parse_srt(srt_content: str) -> str:
    """解析 SRT 格式字幕，回傳純文字"""
    # 移除時間碼和序號
    text = re.sub(r"\d+\n\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}\n", "", srt_content)
    # 移除 HTML 標籤（如 <i>, <b>）
    text = re.sub(r"<[^>]+>", "", text)
    # 整理空行
    text = re.sub(r"\n{3,}", "\n", text)
    return text.strip()
