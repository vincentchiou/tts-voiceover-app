"""
audio.py — TTS 語音合成
使用 CosyVoice2-0.5B 合成語音，支援：
- 預設音色（透過 instruct2 + 預設參考音檔模擬）
- Zero-shot 聲音複製（上傳參考音檔）
- 情緒/語氣指令
- 長文自動分段 + FFmpeg 串接

注意：CosyVoice2-0.5B 無 SFT 預設音色，
      所有合成均使用 inference_instruct2 + 參考音檔。
"""

import os
import re
import sys
import wave
import json
import shutil
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Callable, Optional

import config

logger = logging.getLogger(__name__)


# CosyVoice2 模型單例（避免重複載入）
_cosyvoice_model = None
_cosyvoice_lock = __import__("threading").Lock()


def _get_model():
    """載入 CosyVoice2 模型（延遲初始化）"""
    global _cosyvoice_model
    with _cosyvoice_lock:
        if _cosyvoice_model is not None:
            return _cosyvoice_model

        if not config.COSYVOICE_REPO.exists():
            raise RuntimeError("CosyVoice2 程式碼未安裝，請先完成環境安裝")
        if not config.COSYVOICE_DIR.exists():
            raise RuntimeError("CosyVoice2-0.5B 模型未下載，請先下載模型")

        # 將 CosyVoice 及 third_party/Matcha-TTS 加入 Python path
        cosyvoice_path = str(config.COSYVOICE_REPO)
        matcha_path    = str(config.COSYVOICE_REPO / "third_party" / "Matcha-TTS")
        for p in (matcha_path, cosyvoice_path):
            if p not in sys.path:
                sys.path.insert(0, p)

        # ── Monkey-patch：新版 torchaudio.load() 走 torchcodec（需 FFmpeg DLL）
        # 必須在 import CosyVoice2 之前 patch，因為 frontend.py 用
        # "from cosyvoice.utils.file_utils import load_wav" 綁定名稱
        import numpy as _np
        import soundfile as _sf
        import torch as _torch

        def _patched_load_wav(wav, target_sr, min_sr=16000):
            if isinstance(wav, _torch.Tensor):
                # 已是 tensor（我們傳入的 ref_audio 已重採樣到 16kHz）
                speech = wav if wav.ndim == 2 else wav.unsqueeze(0)
                if target_sr != 16000:
                    from scipy.signal import resample as _resample
                    arr = speech.squeeze(0).numpy()
                    arr = _resample(arr, int(len(arr) * target_sr / 16000)).astype(_np.float32)
                    speech = _torch.from_numpy(arr).unsqueeze(0)
                return speech
            # 檔案路徑：用 soundfile 載入（避開 torchaudio/torchcodec）
            data, sample_rate = _sf.read(str(wav), dtype='float32')
            if data.ndim > 1:
                data = data.mean(axis=1)
            if sample_rate != target_sr:
                assert sample_rate >= min_sr, \
                    f'wav sample rate {sample_rate} must be >= {min_sr}'
                from scipy.signal import resample as _resample
                data = _resample(data, int(len(data) * target_sr / sample_rate)).astype(_np.float32)
            return _torch.from_numpy(data).unsqueeze(0)

        # Step 1：在 import CosyVoice2 之前 patch file_utils（讓 frontend.py 綁到新版本）
        try:
            import cosyvoice.utils.file_utils as _fu
            _fu.load_wav = _patched_load_wav
        except Exception:
            pass  # 第一次 import 若失敗，第二步 patch 會補救

        try:
            from cosyvoice.cli.cosyvoice import CosyVoice2
        except ImportError as e:
            config.MARKER_COSYVOICE.unlink(missing_ok=True)
            raise RuntimeError(
                f"CosyVoice2 依賴套件不完整（{e}）。\n"
                "請展開「系統資訊」，點選「安裝語音引擎 CosyVoice2」重新安裝。"
            ) from e

        # Step 2：確保 frontend 模組的 load_wav binding 也被替換
        try:
            import cosyvoice.cli.frontend as _frontend
            import cosyvoice.utils.file_utils as _fu2
            _fu2.load_wav = _patched_load_wav
            _frontend.load_wav = _patched_load_wav
            logger.info("已套用 load_wav patch（soundfile 替代 torchaudio/torchcodec）")
        except Exception as _pe:
            logger.warning(f"load_wav patch 步驟 2 失敗：{_pe}")

        logger.info("正在載入 CosyVoice2-0.5B 模型...")
        _cosyvoice_model = CosyVoice2(
            str(config.COSYVOICE_DIR),
            load_jit=False,
            load_trt=False,
        )
        logger.info(f"CosyVoice2 載入完成，sample_rate={_cosyvoice_model.sample_rate}")

        # CPU 上模型可能為 BFloat16，與 Float32 輸入衝突 → 強制轉 float32
        import torch as _t
        if not _t.cuda.is_available():
            try:
                _cosyvoice_model.model.llm  = _cosyvoice_model.model.llm.float()
                _cosyvoice_model.model.flow = _cosyvoice_model.model.flow.float()
                _cosyvoice_model.model.hift = _cosyvoice_model.model.hift.float()
                logger.info("已將模型轉換為 float32（CPU 模式）")
            except Exception as _fe:
                logger.warning(f"float32 轉換失敗（繼續嘗試）：{_fe}")

        return _cosyvoice_model


def _load_preset_voices() -> dict:
    """讀取預設音色設定"""
    models_json = config.MANIFESTS_DIR / "models.json"
    data = json.loads(models_json.read_text(encoding="utf-8"))
    return data.get("preset_voices", {})


def _load_cloned_voice(voice_id: str) -> Optional[dict]:
    """載入複製音色的參考音檔資訊"""
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


def _load_audio_as_tensor(audio_path: str):
    """
    載入音訊並轉換為 16kHz float32 torch tensor（CosyVoice2 需要）。
    使用 soundfile + scipy 取代 torchaudio（避免 Windows DLL 問題）。
    """
    import torch
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(audio_path, dtype="float32")

    # 多聲道 → 單聲道
    if data.ndim > 1:
        data = data.mean(axis=1)

    # 重新取樣到 16kHz
    if sr != 16000:
        try:
            from scipy.signal import resample as scipy_resample
            data = scipy_resample(data, int(len(data) * 16000 / sr)).astype(np.float32)
        except ImportError:
            # scipy 未安裝時的簡易線性插值
            new_len = int(len(data) * 16000 / sr)
            indices = np.linspace(0, len(data) - 1, new_len)
            data = np.interp(indices, np.arange(len(data)), data).astype(np.float32)

    return torch.from_numpy(data)


def _get_default_ref_audio() -> Optional[str]:
    """取得 CosyVoice2 內建的預設參考音檔路徑"""
    # CosyVoice repo 內附的 zero-shot 示範音檔
    candidates = [
        config.COSYVOICE_REPO / "asset" / "zero_shot_prompt.wav",
        config.COSYVOICE_REPO / "asset" / "prompt.wav",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    logger.warning("找不到預設參考音檔，語音合成可能失敗")
    return None


def _split_text(text: str, max_chars: int = 150) -> list[str]:
    """將長文拆成小段（每段不超過 max_chars 字）"""
    # 先依句尾標點分割
    sentences = re.split(r"(?<=[。！？\.\!\?])", text)
    chunks = []
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
            # 若單句超過 max_chars，強制切割
            while len(sent) > max_chars:
                chunks.append(sent[:max_chars])
                sent = sent[max_chars:]
            current = sent

    if current:
        chunks.append(current)

    return [c for c in chunks if c.strip()]


def _synthesize_segment(model, text: str, voice_config: dict, out_path: Path):
    """
    合成單一文字段落，儲存為 WAV。
    CosyVoice2-0.5B 不支援 SFT 音色，
    一律使用 inference_instruct2 + 參考音檔。
    """
    import numpy as np
    import soundfile as sf

    instruct = voice_config.get("instruct", "用自然的語氣說")

    # 決定參考音檔路徑
    ref_audio_path = voice_config.get("audio_path")  # 使用者上傳的複製音色
    if not ref_audio_path:
        ref_audio_path = _get_default_ref_audio()  # 預設參考音檔

    if not ref_audio_path:
        raise RuntimeError("找不到任何參考音檔，無法進行語音合成")

    logger.info(f"合成文字（{len(text)} 字）：使用參考音檔 {ref_audio_path}，指令：{instruct}")

    # 載入參考音檔（CosyVoice2 需要 shape [1, T] 的 batch tensor）
    ref_audio_1d = _load_audio_as_tensor(ref_audio_path)
    ref_audio = ref_audio_1d.unsqueeze(0)  # [T] → [1, T]

    # inference_instruct2：tts_text + instruct_text + prompt_wav
    result = model.inference_instruct2(
        tts_text=text,
        instruct_text=instruct,
        prompt_wav=ref_audio,
        stream=False,
    )

    # 取得音訊資料（CosyVoice2 回傳 generator，tensor shape 為 [1, T] 或 [T]）
    for output in result:
        audio_tensor = output["tts_speech"]
        # 確保是一維陣列（squeeze batch dim）
        audio_data = audio_tensor.squeeze().numpy()
        sr = model.sample_rate  # 24000
        sf.write(str(out_path), audio_data, samplerate=sr)
        logger.info(f"已儲存音訊：{out_path}（{len(audio_data)} samples @ {sr}Hz）")
        return

    raise RuntimeError("CosyVoice2 未回傳音訊資料")


def _concat_wavs(wav_files: list[Path], output: Path, silence_ms: int = 200):
    """用 FFmpeg 串接多個 WAV 檔，中間插入靜音"""
    ffmpeg = str(config.ffmpeg_exe())

    if not Path(ffmpeg).exists():
        raise RuntimeError("找不到 FFmpeg，請先完成環境安裝")

    if len(wav_files) == 1:
        shutil.copy(wav_files[0], output)
        return

    # 建立 concat list
    concat_list = output.parent / "concat_list.txt"
    with concat_list.open("w", encoding="utf-8") as f:
        for wav in wav_files:
            # 路徑中的反斜線需轉為正斜線
            f.write(f"file '{str(wav).replace(chr(92), '/')}'\n")

    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy", str(output),
    ], check=True)

    concat_list.unlink(missing_ok=True)


def _wav_to_mp3(wav_path: Path, mp3_path: Path):
    """將 WAV 轉換為 MP3"""
    ffmpeg = str(config.ffmpeg_exe())
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(wav_path),
        "-codec:a", "libmp3lame",
        "-b:a", "192k",
        str(mp3_path),
    ], check=True)


def synthesize(job, job_dir: Path, progress_cb: Callable) -> Path:
    """
    執行完整語音合成流程。
    job: jobs.Job 物件
    job_dir: 工作輸出資料夾
    progress_cb: (percent, message) → None
    回傳 MP3 檔路徑
    """
    progress_cb(72, "載入語音模型...")
    model = _get_model()

    # 讀取音色設定
    preset_voices = _load_preset_voices()

    def _get_voice_config(voice_name: str, custom_voice_id: str) -> dict:
        if custom_voice_id:
            cloned = _load_cloned_voice(custom_voice_id)
            if cloned:
                return cloned
        return preset_voices.get(voice_name, preset_voices.get("台灣女聲", {}))

    voice_a_cfg = _get_voice_config(job.voice_a, job.custom_voice_a)
    voice_b_cfg = _get_voice_config(job.voice_b, job.custom_voice_b)

    segments = job.segments
    total_segs = len(segments)
    wav_files = []

    temp_dir = job_dir / "segments"
    temp_dir.mkdir(exist_ok=True)

    progress_cb(75, f"合成語音中（共 {total_segs} 段）...")

    for i, seg in enumerate(segments):
        speaker = seg.get("speaker", "旁白")
        text = seg.get("text", "").strip()
        if not text:
            continue

        # 選擇音色（雙人模式按說話者切換）
        if job.output_mode == "duo" and speaker == "主持B":
            voice_cfg = voice_b_cfg
        else:
            voice_cfg = voice_a_cfg

        # 分割長文段
        sub_chunks = _split_text(text, max_chars=150)
        for ci, chunk in enumerate(sub_chunks):
            wav_out = temp_dir / f"seg_{i:04d}_{ci:02d}.wav"
            try:
                _synthesize_segment(model, chunk, voice_cfg, wav_out)
            except Exception as e:
                logger.error(f"段落 {i}-{ci} 合成失敗：{e}")
                raise
            wav_files.append(wav_out)

        # 雙人模式在換人時加靜音片段
        if job.output_mode == "duo" and i < total_segs - 1:
            next_speaker = segments[i + 1].get("speaker", "旁白")
            if next_speaker != speaker:
                silence_path = temp_dir / f"silence_{i:04d}.wav"
                _create_silence_wav(silence_path, duration_ms=400)
                wav_files.append(silence_path)

        pct = 75 + int((i + 1) / total_segs * 20)
        progress_cb(pct, f"合成中 {i+1}/{total_segs}...")

    # 串接所有 WAV
    progress_cb(96, "串接音訊檔案...")
    combined_wav = job_dir / "output.wav"
    _concat_wavs(wav_files, combined_wav)

    # 轉換為 MP3
    progress_cb(98, "轉換為 MP3...")
    mp3_path = job_dir / "output.mp3"
    _wav_to_mp3(combined_wav, mp3_path)

    # 清理暫存
    shutil.rmtree(temp_dir, ignore_errors=True)
    combined_wav.unlink(missing_ok=True)

    return mp3_path


def _create_silence_wav(path: Path, duration_ms: int = 400, sample_rate: int = 24000):
    """建立靜音 WAV 檔（與 CosyVoice2 相同取樣率）"""
    import struct
    num_samples = int(sample_rate * duration_ms / 1000)
    with wave.open(str(path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack(f"<{num_samples}h", *([0] * num_samples)))


def clone_voice(audio_path: Path, voice_id: str, reference_text: str = "") -> dict:
    """
    建立複製音色：儲存參考音檔和 meta 資訊
    audio_path: 上傳的參考音檔（WAV/MP3）
    voice_id: 自訂識別 ID
    reference_text: 參考音檔中說的內容（可空白）
    """
    voice_dir = config.VOICES_DIR / voice_id
    voice_dir.mkdir(parents=True, exist_ok=True)

    # 轉換為 16kHz WAV
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
        "reference_text": reference_text,
        "instruct": "用自然的語氣說",
        "is_cloned": True,
    }
    (voice_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def list_cloned_voices() -> list[dict]:
    """列出所有複製音色"""
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
