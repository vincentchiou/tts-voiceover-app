"""
產生 6 個預設音色 ref 音檔（GPT-SoVITS v4 用）

使用 Microsoft Edge TTS（zh-TW 神經網路語音，免費）合成，再用 ffmpeg
轉成 16kHz mono WAV。輸出到 manifests/preset_voices/。

注意：zh-TW 在 Edge TTS 只有 3 個說話者，這 6 個 preset 是同 3 人用
不同語速/音調做出 6 種風格，邱老師之後可以用自己的錄音覆蓋同檔名。
"""
from __future__ import annotations
import asyncio
import subprocess
import sys
from pathlib import Path

import edge_tts

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "manifests" / "preset_voices"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 每個 preset：檔名、voice、rate（語速）、pitch（音調）、實際逐字稿
PRESETS = [
    # 女聲 × 3 風格
    {
        "filename": "taiwan_female_warm.wav",
        "voice": "zh-TW-HsiaoChenNeural",
        "rate": "+0%", "pitch": "+0Hz",
        "text": "今天天氣真好，我們一起出去走走吧，順便聊聊最近發生的有趣事情。",
    },
    {
        "filename": "taiwan_female_lively.wav",
        "voice": "zh-TW-HsiaoYuNeural",
        "rate": "+10%", "pitch": "+3Hz",
        "text": "嗨嗨大家好，我們今天要來學一個超有趣的東西喔，準備好了嗎？",
    },
    {
        "filename": "taiwan_female_energetic.wav",
        "voice": "zh-TW-HsiaoYuNeural",
        "rate": "+20%", "pitch": "+5Hz",
        "text": "哇！這真的太厲害了，我們一起來看看吧，絕對會讓你大開眼界！",
    },
    # 男聲 × 3 風格（同說話者，rate/pitch 變化）
    {
        "filename": "taiwan_male_clear.wav",
        "voice": "zh-TW-YunJheNeural",
        "rate": "+0%", "pitch": "+0Hz",
        "text": "歡迎收聽今天的內容，讓我們一起來深入了解這個有趣的主題。",
    },
    {
        "filename": "taiwan_male_steady.wav",
        "voice": "zh-TW-YunJheNeural",
        "rate": "-10%", "pitch": "-2Hz",
        "text": "本次課程的核心目標，是讓大家理解這個概念的本質與運作原理。",
    },
    {
        "filename": "taiwan_male_warm.wav",
        "voice": "zh-TW-YunJheNeural",
        "rate": "-5%", "pitch": "+0Hz",
        "text": "從前從前，有一個小村莊，住著一位很特別的老師，他教會大家許多道理。",
    },
]


async def gen_one(preset: dict) -> tuple[str, Path, str]:
    name = preset["filename"]
    mp3_path = OUT_DIR / (name + ".tmp.mp3")
    wav_path = OUT_DIR / name

    print(f"[GEN] {name} ← {preset['voice']} rate={preset['rate']} pitch={preset['pitch']}")
    communicate = edge_tts.Communicate(
        preset["text"],
        preset["voice"],
        rate=preset["rate"],
        pitch=preset["pitch"],
    )
    await communicate.save(str(mp3_path))

    # 用 ffmpeg 轉 16kHz mono WAV（GPT-SoVITS ref 規格）
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(mp3_path),
        "-ac", "1", "-ar", "16000",
        str(wav_path),
    ]
    subprocess.run(cmd, check=True)
    mp3_path.unlink()
    return name, wav_path, preset["text"]


async def main() -> None:
    results = []
    for p in PRESETS:
        results.append(await gen_one(p))

    print("\n[ OK ] 6 個預設音色已生成：")
    for name, path, text in results:
        size_kb = path.stat().st_size // 1024
        print(f"  {name} ({size_kb} KB)  '{text}'")
    print(f"\n輸出目錄：{OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
