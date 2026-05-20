"""
gptsovits_service.py — 管理 GPT-SoVITS api_v2.py 子行程
- 第一次呼叫時自動啟動 GPT-SoVITS 推論服務（port 9880）
- 主後端透過 HTTP /tts 呼叫合成
- 提供切換 GPT/SoVITS 權重的方法
"""

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import httpx

import config

logger = logging.getLogger(__name__)


# ── 服務狀態 ─────────────────────────────────────────────
_proc: Optional[subprocess.Popen] = None
_lock = threading.Lock()

# GPT-SoVITS api_v2.py 預設綁定
HOST = "127.0.0.1"
PORT = int(os.environ.get("TTS_GPTSOVITS_PORT", "9880"))
BASE_URL = f"http://{HOST}:{PORT}"


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """檢查 port 是否有東西在監聽"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def is_running() -> bool:
    """判斷 GPT-SoVITS 服務是否已啟動"""
    if _proc is not None and _proc.poll() is None and _port_open(HOST, PORT):
        return True
    # 外部已啟動的服務（手動跑 api_v2.py）也算
    return _port_open(HOST, PORT)


def _gptsovits_python() -> str:
    """取得 GPT-SoVITS 專用 venv 的 python.exe"""
    # 優先使用獨立 venv（避免依賴衝突）
    venv = config.GPTSOVITS_VENV / "Scripts" / "python.exe"
    if venv.exists():
        return str(venv)
    # 退而求其次：使用主 venv
    main_venv = config.VENV_DIR / "Scripts" / "python.exe"
    return str(main_venv)


def start(wait_seconds: int = 300) -> None:
    """啟動 GPT-SoVITS api_v2.py，阻塞直到 port 可連線或逾時"""
    global _proc
    with _lock:
        if is_running():
            return

        repo = config.GPTSOVITS_REPO
        if not repo.exists():
            raise RuntimeError(
                f"GPT-SoVITS 程式碼不存在於 {repo}\n"
                "請先執行 setup_gptsovits.ps1 安裝。"
            )
        config_yaml = repo / "GPT_SoVITS" / "configs" / "tts_infer.yaml"
        if not config_yaml.exists():
            raise RuntimeError(f"找不到 tts_infer.yaml：{config_yaml}")

        py = _gptsovits_python()
        cmd = [
            py, "api_v2.py",
            "-a", HOST,
            "-p", str(PORT),
            "-c", str(config_yaml.relative_to(repo)).replace("\\", "/"),
        ]
        logger.info(f"啟動 GPT-SoVITS 服務：{' '.join(cmd)}（cwd={repo}）")

        log_path = config.RUNTIME_DIR / "gptsovits.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logf = log_path.open("ab")

        _proc = subprocess.Popen(
            cmd,
            cwd=str(repo),
            stdout=logf,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

    # 等服務起來（出鎖後輪詢）
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if _port_open(HOST, PORT):
            logger.info(f"GPT-SoVITS 已就緒：{BASE_URL}")
            return
        if _proc is not None and _proc.poll() is not None:
            tail = ""
            try:
                tail = (config.RUNTIME_DIR / "gptsovits.log").read_text(
                    encoding="utf-8", errors="replace")[-1500:]
            except Exception:
                pass
            raise RuntimeError(
                f"GPT-SoVITS 啟動失敗（exit={_proc.returncode}）\n{tail}"
            )
        time.sleep(1.0)

    raise RuntimeError(f"GPT-SoVITS 啟動逾時（{wait_seconds}s），請檢查 runtime/gptsovits.log")


def stop() -> None:
    """停止 GPT-SoVITS 服務"""
    global _proc
    with _lock:
        if _proc is not None and _proc.poll() is None:
            try:
                _proc.terminate()
                _proc.wait(timeout=5)
            except Exception:
                _proc.kill()
        _proc = None


def ensure_started():
    """合成前呼叫；服務未開則自動開"""
    if not is_running():
        start()


# ── 權重切換 ─────────────────────────────────────────────
_current_gpt_weights: Optional[str] = None
_current_sovits_weights: Optional[str] = None


def set_gpt_weights(weights_path: str) -> None:
    """切換 GPT 模型權重（如 s1v3.ckpt for v4）"""
    global _current_gpt_weights
    if _current_gpt_weights == weights_path:
        return
    resp = httpx.get(
        f"{BASE_URL}/set_gpt_weights",
        params={"weights_path": weights_path},
        timeout=60.0,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"切換 GPT 權重失敗：{resp.text}")
    _current_gpt_weights = weights_path


def set_sovits_weights(weights_path: str) -> None:
    """切換 SoVITS 模型權重（如 gsv-v4-pretrained/s2Gv4.pth）"""
    global _current_sovits_weights
    if _current_sovits_weights == weights_path:
        return
    resp = httpx.get(
        f"{BASE_URL}/set_sovits_weights",
        params={"weights_path": weights_path},
        timeout=60.0,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"切換 SoVITS 權重失敗：{resp.text}")
    _current_sovits_weights = weights_path


def ensure_v4_weights() -> None:
    """確保載入 v4 權重組合（首次呼叫會載入）"""
    ensure_started()
    set_gpt_weights("GPT_SoVITS/pretrained_models/s1v3.ckpt")
    set_sovits_weights("GPT_SoVITS/pretrained_models/gsv-v4-pretrained/s2Gv4.pth")


# ── TTS 合成 ─────────────────────────────────────────────
def synthesize(
    text: str,
    ref_audio_path: str,
    prompt_text: str,
    out_path: Path,
    text_lang: str = "zh",
    prompt_lang: str = "zh",
    top_k: int = 15,
    top_p: float = 1.0,
    temperature: float = 1.0,
    speed_factor: float = 1.0,
    text_split_method: str = "cut5",
    batch_size: int = 1,
    media_type: str = "wav",
    timeout: float = 300.0,
) -> None:
    """
    呼叫 GPT-SoVITS /tts 合成單段文字，寫入 out_path。
    需先確認 ref_audio_path 為 GPT-SoVITS 可讀的絕對路徑。
    """
    ensure_v4_weights()

    payload = {
        "text": text,
        "text_lang": text_lang,
        "ref_audio_path": ref_audio_path,
        "prompt_text": prompt_text,
        "prompt_lang": prompt_lang,
        "top_k": top_k,
        "top_p": top_p,
        "temperature": temperature,
        "speed_factor": speed_factor,
        "text_split_method": text_split_method,
        "batch_size": batch_size,
        "media_type": media_type,
        "streaming_mode": False,
    }
    resp = httpx.post(f"{BASE_URL}/tts", json=payload, timeout=timeout)
    if resp.status_code != 200:
        try:
            err = resp.json()
        except Exception:
            err = resp.text
        raise RuntimeError(f"GPT-SoVITS /tts 失敗：{err}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(resp.content)
