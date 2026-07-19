"""
tts_providers.py — TTS provider settings and optional engines.

Providers:
- gptsovits: existing local GPT-SoVITS v4 path
- indextts2: local IndexTTS2 Python package/checkpoints, if installed
- qwen: Qwen/CosyVoice cloud TTS through DashScope/Qwen Cloud
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import config


DEFAULT_TTS_SETTINGS = {
    "provider": "gptsovits",
    "indextts2_python": "",
    "indextts2_model_dir": "",
    "indextts2_config_path": "",
    "indextts2_use_fp16": True,
    "indextts2_emotion": "自然、親切、像台灣老師在講課，語氣有溫度但不要誇張。",
    "qwen_api_key": "",
    "qwen_base_http_url": "https://dashscope-intl.aliyuncs.com/api/v1",
    "qwen_model": "qwen3-tts-instruct-flash",
    "qwen_voice_a": "Cherry",
    "qwen_voice_b": "Ethan",
    "qwen_instructions": "台灣繁體中文口吻，自然、清楚、有教學親和力；情緒有起伏但不要戲劇化。",
    "qwen_optimize_instructions": True,
}


def load_tts_settings() -> dict:
    f = config.TTS_SETTINGS_FILE
    if f.exists():
        try:
            saved = json.loads(f.read_text(encoding="utf-8-sig"))
            return {**DEFAULT_TTS_SETTINGS, **saved}
        except Exception:
            pass
    return dict(DEFAULT_TTS_SETTINGS)


def save_tts_settings(data: dict) -> dict:
    merged = {**DEFAULT_TTS_SETTINGS, **data}
    config.TTS_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.TTS_SETTINGS_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return merged


def public_tts_settings() -> dict:
    s = load_tts_settings()
    return {**s, "qwen_api_key": "***" if s.get("qwen_api_key") else ""}


def qwen_api_key(settings: Optional[dict] = None) -> str:
    s = settings or load_tts_settings()
    return s.get("qwen_api_key") or os.environ.get("DASHSCOPE_API_KEY", "")


def provider_status() -> dict:
    s = load_tts_settings()
    return {
        "provider": s.get("provider", "gptsovits"),
        "gptsovits": {
            "ready": config.MARKER_GPTSOVITS.exists()
                     and config.GPTSOVITS_REPO.exists()
                     and config.GPTSOVITS_PRETRAINED.exists(),
            "repo": str(config.GPTSOVITS_REPO),
        },
        "indextts2": {
            "python_ready": _indextts2_python_ready(s),
            "package_ready": _indextts2_package_ready(s),
            "model_dir_ready": bool(s.get("indextts2_model_dir")) and Path(s["indextts2_model_dir"]).exists(),
            "config_ready": bool(s.get("indextts2_config_path")) and Path(s["indextts2_config_path"]).exists(),
        },
        "qwen": {
            "package_ready": _module_available("dashscope"),
            "api_key_ready": bool(qwen_api_key(s)),
            "model": s.get("qwen_model", ""),
        },
    }


def _module_available(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False



def _indextts2_python(settings: dict) -> str:
    py = (settings.get("indextts2_python") or "").strip()
    return py or sys.executable


def _indextts2_python_ready(settings: dict) -> bool:
    return Path(_indextts2_python(settings)).exists()


def _indextts2_package_ready(settings: dict) -> bool:
    py = _indextts2_python(settings)
    if not Path(py).exists():
        return False
    try:
        r = subprocess.run(
            [py, "-c", "import indextts"],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False

def synthesize_indextts2(
    *,
    text: str,
    ref_audio_path: str,
    out_path: Path,
    settings: Optional[dict] = None,
) -> None:
    """Synthesize one WAV with a locally installed IndexTTS2 package."""
    s = settings or load_tts_settings()
    model_dir = s.get("indextts2_model_dir", "").strip()
    config_path = s.get("indextts2_config_path", "").strip()
    if not model_dir or not Path(model_dir).exists():
        raise RuntimeError("IndexTTS2 模型目錄尚未設定或不存在，請在 TTS 設定填入 checkpoints 目錄。")
    if not config_path or not Path(config_path).exists():
        raise RuntimeError("IndexTTS2 config.yaml 尚未設定或不存在，請在 TTS 設定填入 config.yaml 路徑。")

    script = f"""
from pathlib import Path
try:
    from indextts.infer_v2 import IndexTTS2
except Exception:
    try:
        from indextts.infer_indextts2 import IndexTTS2
    except Exception as e:
        raise RuntimeError('找不到 IndexTTS2 Python 套件，請先安裝 index-tts 專案依賴。' + str(e))

import inspect
params = inspect.signature(IndexTTS2).parameters
init_kwargs = dict(cfg_path={config_path!r}, model_dir={model_dir!r})
if 'use_fp16' in params:
    init_kwargs['use_fp16'] = {bool(s.get('indextts2_use_fp16', True))!r}
elif 'is_fp16' in params:
    init_kwargs['is_fp16'] = {bool(s.get('indextts2_use_fp16', True))!r}
if 'use_cuda_kernel' in params:
    init_kwargs['use_cuda_kernel'] = False
if 'use_deepspeed' in params:
    init_kwargs['use_deepspeed'] = False
tts = IndexTTS2(**init_kwargs)
kwargs = dict(
    spk_audio_prompt={ref_audio_path!r},
    text={text!r},
    output_path={str(out_path)!r},
    verbose=False,
)
emo_text = {s.get('indextts2_emotion', '')!r}
if emo_text:
    kwargs['use_emo_text'] = True
    kwargs['emo_text'] = emo_text
    kwargs['emo_alpha'] = 0.6
tts.infer(**kwargs)
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [_indextts2_python(s), "-c", script],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"IndexTTS2 合成失敗：{(proc.stderr or proc.stdout)[-1200:]}")
    if not out_path.exists():
        raise RuntimeError("IndexTTS2 合成完成但找不到輸出音檔")


def synthesize_qwen(
    *,
    text: str,
    voice: str,
    out_path: Path,
    settings: Optional[dict] = None,
) -> None:
    """Synthesize one audio file through Qwen/CosyVoice DashScope API."""
    s = settings or load_tts_settings()
    api_key = qwen_api_key(s)
    if not api_key:
        raise RuntimeError("Qwen/CosyVoice 需要 DASHSCOPE_API_KEY，請在 TTS 設定填入 API Key 或設定環境變數。")
    try:
        import dashscope
        from dashscope import MultiModalConversation
    except Exception as e:
        raise RuntimeError("Qwen/CosyVoice 需要 dashscope 套件，請重新執行 start.bat 同步 requirements.txt。" + str(e))

    dashscope.base_http_api_url = s.get("qwen_base_http_url", "https://dashscope-intl.aliyuncs.com/api/v1")
    kwargs = {
        "model": s.get("qwen_model", "qwen3-tts-instruct-flash"),
        "api_key": api_key,
        "text": text,
        "voice": voice,
        "stream": False,
    }
    instructions = s.get("qwen_instructions", "").strip()
    if instructions:
        kwargs["instructions"] = instructions
        kwargs["optimize_instructions"] = bool(s.get("qwen_optimize_instructions", True))

    response = MultiModalConversation.call(**kwargs)
    if isinstance(response, dict):
        status = response.get("status_code")
        data = response
    else:
        status = getattr(response, "status_code", None)
        data = getattr(response, "__dict__", {}) or {}
    if status and int(status) != 200:
        msg = getattr(response, "message", "") or (data.get("message", "") if isinstance(data, dict) else "")
        raise RuntimeError(f"Qwen/CosyVoice 回傳 HTTP {status}：{msg}")

    if not isinstance(data, dict) or not data.get("output"):
        try:
            data = json.loads(json.dumps(response, default=lambda o: getattr(o, "__dict__", str(o))))
        except Exception:
            data = {}
    audio = (data.get("output") or {}).get("audio") or {}
    audio_url = audio.get("url")
    audio_data = audio.get("data")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if audio_data:
        import base64
        out_path.write_bytes(base64.b64decode(audio_data))
        return
    if audio_url:
        import httpx
        resp = httpx.get(audio_url, timeout=300.0)
        if resp.status_code != 200:
            raise RuntimeError(f"下載 Qwen/CosyVoice 音檔失敗 HTTP {resp.status_code}")
        out_path.write_bytes(resp.content)
        return
    raise RuntimeError(f"Qwen/CosyVoice 回應沒有 audio.url 或 audio.data：{str(data)[:500]}")

