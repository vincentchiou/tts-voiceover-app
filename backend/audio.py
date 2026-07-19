"""
audio.py — TTS 語音合成（GPT-SoVITS v4 後端）
- 預設音色：每個 preset 綁定一段 ref 音檔 + prompt_text
- 複製音色：使用者上傳 ref 音檔 + 對應逐字稿
- 透過 backend/gptsovits_service.py 呼叫 api_v2.py（port 9880）
- 長文自動分段（GPT-SoVITS text_split_method 也會分段）+ FFmpeg 串接
"""

import json
import logging
import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Callable, Optional

import config
import gptsovits_service
import tts_providers

logger = logging.getLogger(__name__)


# ── 音色設定載入 ─────────────────────────────────────────
def _load_preset_voices() -> dict:
    """讀取 manifests/models.json 中的 preset_voices"""
    models_json = config.MANIFESTS_DIR / "models.json"
    data = json.loads(models_json.read_text(encoding="utf-8"))
    return data.get("preset_voices", {})


def _resolve_preset_ref_audio(preset_cfg: dict) -> Optional[Path]:
    """
    將 preset_voices 中的 ref_audio 相對路徑解析為絕對路徑。
    優先順序：
      1) manifests/<ref_audio>
      2) 若不存在，回退到任何已 clone 的 voice（fallback）
    """
    rel = preset_cfg.get("ref_audio", "")
    if rel:
        candidate = config.MANIFESTS_DIR / rel
        if candidate.exists():
            return candidate
    # fallback：找到任一已上傳的 cloned voice
    if config.VOICES_DIR.exists():
        for d in config.VOICES_DIR.iterdir():
            ref = d / "reference.wav"
            if ref.exists():
                logger.warning(
                    f"預設音色 ref_audio 不存在（{rel}），退而使用 {ref}"
                )
                return ref
    return None


def _load_cloned_voice(voice_id: str) -> Optional[dict]:
    """讀取使用者上傳的複製音色 meta + 音檔路徑"""
    voice_dir = config.VOICES_DIR / voice_id
    meta_file = voice_dir / "meta.json"
    if not meta_file.exists():
        return None
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    audio_path = voice_dir / "reference.wav"
    if not audio_path.exists():
        return None
    meta["audio_path"] = str(audio_path)
    return meta


# ── 文字分段 ────────────────────────────────────────────
def _split_text(text: str, max_chars: int = 200) -> list[str]:
    """將長文拆成段；GPT-SoVITS 內部 text_split_method=cut5 也會再分句"""
    sentences = re.split(r"(?<=[。！？\.\!\?])", text)
    chunks: list[str] = []
    current = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(current) + len(sent) <= max_chars:
            current += sent
        else:
            if current:
                chunks.append(current)
            while len(sent) > max_chars:
                chunks.append(sent[:max_chars])
                sent = sent[max_chars:]
            current = sent
    if current:
        chunks.append(current)
    return [c for c in chunks if c.strip()]


# ── 串接與轉檔 ──────────────────────────────────────────
def _concat_wavs(wav_files: list[Path], output: Path):
    """用 FFmpeg 串接多段 WAV"""
    ffmpeg = str(config.ffmpeg_exe())
    if not Path(ffmpeg).exists():
        raise RuntimeError("找不到 FFmpeg，請先完成環境安裝")

    if not wav_files:
        raise RuntimeError("沒有可串接的音訊段落")

    if len(wav_files) == 1:
        shutil.copy(wav_files[0], output)
        return

    concat_list = output.parent / "concat_list.txt"
    with concat_list.open("w", encoding="utf-8") as f:
        for wav in wav_files:
            f.write(f"file '{str(wav).replace(chr(92), '/')}'\n")

    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy", str(output),
    ], check=True)
    concat_list.unlink(missing_ok=True)


def _wav_to_mp3(wav_path: Path, mp3_path: Path):
    ffmpeg = str(config.ffmpeg_exe())
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(wav_path),
        "-codec:a", "libmp3lame", "-b:a", "192k",
        str(mp3_path),
    ], check=True)


def _create_silence_wav(path: Path, duration_ms: int = 400, sample_rate: int = 48000):
    """v4 取樣率 48kHz，使用相同 sr 才能 -c copy 串接"""
    import struct
    num_samples = int(sample_rate * duration_ms / 1000)
    with wave.open(str(path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack(f"<{num_samples}h", *([0] * num_samples)))


# ── 主合成流程 ──────────────────────────────────────────
def synthesize(job, job_dir: Path, progress_cb: Callable) -> Path:
    """
    完整合成流程
    job: jobs.Job
    job_dir: 工作輸出資料夾
    progress_cb: (percent, message) → None
    回傳 MP3 路徑
    """
    _speakable_segments(job)
    settings = tts_providers.load_tts_settings()
    provider = settings.get("provider", "gptsovits")
    if provider == "indextts2":
        return _synthesize_indextts2(job, job_dir, progress_cb, settings)
    if provider == "qwen":
        return _synthesize_qwen(job, job_dir, progress_cb, settings)
    return _synthesize_gptsovits(job, job_dir, progress_cb)


def _speakable_segments(job) -> list[dict]:
    segments = [seg for seg in job.segments if (seg.get("text") or "").strip()]
    if not segments:
        raise RuntimeError("腳本沒有可合成的內容，請先補上要朗讀的文字。")
    return segments


def _voice_config(voice_name: str, custom_voice_id: str) -> dict:
    """回傳該音色的合成參數：{ ref_audio_path, prompt_text, prompt_lang }"""
    preset_voices = _load_preset_voices()
    # 1) 使用者複製音色優先
    if custom_voice_id:
        cloned = _load_cloned_voice(custom_voice_id)
        if cloned:
            return {
                "ref_audio_path": cloned["audio_path"],
                "prompt_text": cloned.get("reference_text", "")
                               or "這是一段示範語音。",
                "prompt_lang": cloned.get("prompt_lang", "zh"),
            }
    # 2) 預設音色
    cfg = preset_voices.get(voice_name, preset_voices.get("台灣女聲", {}))
    ref_audio = _resolve_preset_ref_audio(cfg)
    if not ref_audio:
        raise RuntimeError(
            f"音色「{voice_name}」缺少參考音檔。\n"
            "請先在「音色管理」上傳一個參考音檔，或將檔案放在 "
            f"manifests/{cfg.get('ref_audio', 'preset_voices/...')}。"
        )
    return {
        "ref_audio_path": str(ref_audio),
        "prompt_text": cfg.get("prompt_text", "這是一段示範語音。"),
        "prompt_lang": cfg.get("prompt_lang", "zh"),
    }


def _prepare_segments(job, job_dir: Path, progress_cb: Callable, label: str) -> tuple[list[dict], Path, int, list[Path]]:
    segments = _speakable_segments(job)
    total = len(segments)
    wav_files: list[Path] = []
    temp_dir = job_dir / "segments"
    temp_dir.mkdir(exist_ok=True)
    progress_cb(75, f"{label}（共 {total} 段）...")
    return segments, temp_dir, total, wav_files


def _finish_audio(job_dir: Path, temp_dir: Path, wav_files: list[Path], progress_cb: Callable) -> Path:
    progress_cb(96, "串接音訊檔案...")
    combined_wav = job_dir / "output.wav"
    _concat_wavs(wav_files, combined_wav)

    progress_cb(98, "轉換為 MP3...")
    mp3_path = job_dir / "output.mp3"
    _wav_to_mp3(combined_wav, mp3_path)

    shutil.rmtree(temp_dir, ignore_errors=True)
    combined_wav.unlink(missing_ok=True)
    return mp3_path


def _synthesize_gptsovits(job, job_dir: Path, progress_cb: Callable) -> Path:
    progress_cb(72, "確認 GPT-SoVITS 服務狀態...")
    gptsovits_service.ensure_v4_weights()

    voice_a_cfg = _voice_config(job.voice_a, job.custom_voice_a)
    voice_b_cfg = _voice_config(job.voice_b, job.custom_voice_b)

    segments, temp_dir, total, wav_files = _prepare_segments(job, job_dir, progress_cb, "GPT-SoVITS 合成語音中")

    for i, seg in enumerate(segments):
        speaker = seg.get("speaker", "旁白")
        text = seg.get("text", "").strip()
        if not text:
            continue

        cfg = voice_b_cfg if (job.output_mode == "duo" and speaker == "主持B") else voice_a_cfg

        sub_chunks = _split_text(text, max_chars=200)
        for ci, chunk in enumerate(sub_chunks):
            wav_out = temp_dir / f"seg_{i:04d}_{ci:02d}.wav"
            try:
                gptsovits_service.synthesize(
                    text=chunk,
                    ref_audio_path=cfg["ref_audio_path"],
                    prompt_text=cfg["prompt_text"],
                    prompt_lang=cfg["prompt_lang"],
                    out_path=wav_out,
                )
            except Exception as e:
                logger.error(f"段落 {i}-{ci} 合成失敗：{e}")
                raise
            wav_files.append(wav_out)

        # duo 模式換人時加靜音
        if job.output_mode == "duo" and i < total - 1:
            next_speaker = segments[i + 1].get("speaker", "旁白")
            if next_speaker != speaker:
                silence_path = temp_dir / f"silence_{i:04d}.wav"
                _create_silence_wav(silence_path, duration_ms=400)
                wav_files.append(silence_path)

        pct = 75 + int((i + 1) / total * 20)
        progress_cb(pct, f"合成中 {i+1}/{total}...")

    return _finish_audio(job_dir, temp_dir, wav_files, progress_cb)


# ── 複製音色 ────────────────────────────────────────────
def clone_voice(audio_path: Path, voice_id: str, reference_text: str = "") -> dict:
    """
    建立使用者複製音色
    audio_path: 上傳的參考音檔
    voice_id: 識別 ID
    reference_text: 參考音檔的逐字稿（GPT-SoVITS 必填，空白時用通用句帶過）
    """
    voice_dir = config.VOICES_DIR / voice_id
    voice_dir.mkdir(parents=True, exist_ok=True)

    # GPT-SoVITS 推薦 16kHz mono；v4 推論時內部會自動處理
    ref_wav = voice_dir / "reference.wav"
    ffmpeg = str(config.ffmpeg_exe())
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(audio_path),
        "-ar", "16000", "-ac", "1",
        str(ref_wav),
    ], check=True)

    meta = {
        "id": voice_id,
        "label": voice_id,
        "reference_text": reference_text or "這是一段示範語音。",
        "prompt_lang": "zh",
        "is_cloned": True,
    }
    (voice_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta




def _synthesize_indextts2(job, job_dir: Path, progress_cb: Callable, settings: dict) -> Path:
    progress_cb(72, "準備 IndexTTS2 引擎...")
    voice_a_cfg = _voice_config(job.voice_a, job.custom_voice_a)
    voice_b_cfg = _voice_config(job.voice_b, job.custom_voice_b)
    segments, temp_dir, total, wav_files = _prepare_segments(job, job_dir, progress_cb, "IndexTTS2 合成語音中")

    for i, seg in enumerate(segments):
        speaker = seg.get("speaker", "旁白")
        text = seg.get("text", "").strip()
        cfg = voice_b_cfg if (job.output_mode == "duo" and speaker == "主持B") else voice_a_cfg
        for ci, chunk in enumerate(_split_text(text, max_chars=120)):
            wav_out = temp_dir / f"seg_{i:04d}_{ci:02d}.wav"
            tts_providers.synthesize_indextts2(
                text=chunk,
                ref_audio_path=cfg["ref_audio_path"],
                out_path=wav_out,
                settings=settings,
            )
            wav_files.append(wav_out)
        if job.output_mode == "duo" and i < total - 1:
            next_speaker = segments[i + 1].get("speaker", "旁白")
            if next_speaker != speaker:
                silence_path = temp_dir / f"silence_{i:04d}.wav"
                _create_silence_wav(silence_path, duration_ms=350)
                wav_files.append(silence_path)
        pct = 75 + int((i + 1) / total * 20)
        progress_cb(pct, f"IndexTTS2 合成中 {i+1}/{total}...")

    return _finish_audio(job_dir, temp_dir, wav_files, progress_cb)


def _synthesize_qwen(job, job_dir: Path, progress_cb: Callable, settings: dict) -> Path:
    progress_cb(72, "準備 Qwen/CosyVoice 雲端語音...")
    voice_a = settings.get("qwen_voice_a", "Cherry")
    voice_b = settings.get("qwen_voice_b", "Ethan")
    segments, temp_dir, total, wav_files = _prepare_segments(job, job_dir, progress_cb, "Qwen/CosyVoice 合成語音中")

    for i, seg in enumerate(segments):
        speaker = seg.get("speaker", "旁白")
        text = seg.get("text", "").strip()
        voice = voice_b if (job.output_mode == "duo" and speaker == "主持B") else voice_a
        for ci, chunk in enumerate(_split_text(text, max_chars=800)):
            mp3_out = temp_dir / f"seg_{i:04d}_{ci:02d}.mp3"
            wav_out = temp_dir / f"seg_{i:04d}_{ci:02d}.wav"
            tts_providers.synthesize_qwen(
                text=chunk,
                voice=voice,
                out_path=mp3_out,
                settings=settings,
            )
            ffmpeg = str(config.ffmpeg_exe())
            subprocess.run([
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(mp3_out), "-ar", "48000", "-ac", "1", str(wav_out),
            ], check=True)
            wav_files.append(wav_out)
        if job.output_mode == "duo" and i < total - 1:
            next_speaker = segments[i + 1].get("speaker", "旁白")
            if next_speaker != speaker:
                silence_path = temp_dir / f"silence_{i:04d}.wav"
                _create_silence_wav(silence_path, duration_ms=350)
                wav_files.append(silence_path)
        pct = 75 + int((i + 1) / total * 20)
        progress_cb(pct, f"Qwen/CosyVoice 合成中 {i+1}/{total}...")

    return _finish_audio(job_dir, temp_dir, wav_files, progress_cb)


def list_cloned_voices() -> list[dict]:
    voices = []
    if not config.VOICES_DIR.exists():
        return voices
    for d in config.VOICES_DIR.iterdir():
        if d.is_dir():
            meta_file = d / "meta.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                voices.append(meta)
    return voices
