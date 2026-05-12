"""
runtime_manager.py — 自動環境安裝管理
負責下載 uv、安裝 Python、下載模型，全程回報進度
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

import config
import system_probe


@dataclass
class InstallProgress:
    stage: str = "idle"          # idle / checking / downloading / extracting / installing / complete / error
    step: str = ""               # 目前步驟描述
    percent: int = 0             # 0-100
    error: str = ""


# 全域進度狀態（安裝時使用）
_progress = InstallProgress()
_install_lock = threading.Lock()
_install_thread: threading.Thread | None = None


def get_progress() -> dict:
    return {
        "stage":   _progress.stage,
        "step":    _progress.step,
        "percent": _progress.percent,
        "error":   _progress.error,
    }


def is_installing() -> bool:
    return _install_thread is not None and _install_thread.is_alive()


def _set(stage: str, step: str, percent: int, error: str = ""):
    _progress.stage   = stage
    _progress.step    = step
    _progress.percent = percent
    _progress.error   = error


def _load_manifest() -> dict:
    """讀取 runtime.windows.json"""
    path = config.MANIFESTS_DIR / "runtime.windows.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(cmd_list: list, uv: str, venv_python: str) -> list:
    """替換 manifest 中的 token"""
    runtime = str(config.RUNTIME_DIR)
    models  = str(config.MODELS_DIR)
    mapping = {
        "{uv}":          uv,
        "{python_dir}":  str(config.PYTHON_DIR),
        "{venv_python}": venv_python,
        "{runtime_dir}": runtime,
        "{models_dir}":  models,
    }
    return [mapping.get(t, t) for t in cmd_list]


def _download(url: str, dest: Path, label: str, pct_start: int, pct_end: int):
    """下載檔案，支援斷點續傳，動態更新進度"""
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.stat().st_size if dest.exists() else 0
    headers = {"Range": f"bytes={existing}-"} if existing else {}

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0)) + existing
            downloaded = existing
            mode = "ab" if existing else "wb"
            with dest.open(mode) as f:
                while chunk := resp.read(65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        ratio = downloaded / total
                        pct = int(pct_start + ratio * (pct_end - pct_start))
                        _set("downloading", f"下載 {label}... {downloaded//1024//1024}MB", pct)
    except Exception as e:
        raise RuntimeError(f"下載 {label} 失敗：{e}") from e


def _extract_zip(zip_path: Path, dest: Path, strip_top_dir: bool = False):
    """解壓縮 ZIP，可選擇略過最外層資料夾"""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        if strip_top_dir:
            # 找出共同前綴（最外層資料夾名稱）
            names = zf.namelist()
            prefix = names[0].split("/")[0] + "/" if names else ""
            for member in zf.infolist():
                rel = member.filename
                if rel.startswith(prefix):
                    rel = rel[len(prefix):]
                if not rel:
                    continue
                target = dest / rel
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        else:
            zf.extractall(dest)


def _run_cmd(cmd: list, label: str):
    """執行安裝命令，失敗則拋出例外"""
    env = {**os.environ}
    # 只有在 CosyVoice repo 已存在時才加入 PYTHONPATH
    if config.COSYVOICE_REPO.exists():
        env["PYTHONPATH"] = str(config.COSYVOICE_REPO)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"{label} 失敗：{result.stderr[-500:]}")


def _download_repo_zip(zip_url: str, dest: Path, label: str):
    """從 GitHub 下載 ZIP 並解壓（不需要 git）"""
    import urllib.request
    dest.parent.mkdir(parents=True, exist_ok=True)
    zip_path = dest.parent / f"_{dest.name}.zip"
    _set("downloading", f"下載 {label} 原始碼 ZIP...", _progress.percent)
    try:
        urllib.request.urlretrieve(zip_url, str(zip_path))
    except Exception as e:
        raise RuntimeError(f"下載 {label} 失敗：{e}") from e
    _set("installing", f"解壓縮 {label}...", _progress.percent)
    _extract_zip(zip_path, dest, strip_top_dir=True)
    zip_path.unlink(missing_ok=True)


def _git_clone(url: str, dest: Path, branch: str = "main"):
    """git clone（若已存在則 git pull）；無 git 時改用 ZIP 下載"""
    git = shutil.which("git")
    if not git:
        # 沒有 git → 下載 ZIP（GitHub 固定格式）
        repo = url.rstrip("/").removesuffix(".git")
        zip_url = f"{repo}/archive/refs/heads/{branch}.zip"
        _download_repo_zip(zip_url, dest, dest.name)
        return
    if dest.exists():
        subprocess.run([git, "-C", str(dest), "pull", "--ff-only"],
                       capture_output=True, timeout=60)
    else:
        subprocess.run([git, "clone", "--depth=1", "--branch", branch,
                        url, str(dest)], check=True, capture_output=True, timeout=300)


def _install_profile(profile_name: str):
    """執行完整安裝流程（在子執行緒中跑）"""
    try:
        config.ensure_dirs()
        manifest = _load_manifest()
        profile  = manifest["profiles"][profile_name]
        comps    = manifest["components"]

        uv = str(config.UV_EXE)
        venv_python = str(config.VENV_DIR / "Scripts" / "python.exe")

        component_ids = profile["components"]
        total = len(component_ids)

        for idx, cid in enumerate(component_ids):
            comp = comps[cid]
            label = comp["label"]
            marker = config.RUNTIME_DIR / comp.get("marker", f".{cid}-installed")
            pct_base = int(idx / total * 90)
            pct_next = int((idx + 1) / total * 90)

            # 已安裝則跳過
            if marker.exists():
                _set("checking", f"✓ {label}（已安裝）", pct_next)
                continue

            _set("checking", f"準備安裝：{label}", pct_base)

            # ── 下載 ZIP ────────────────────────────────
            if "download_url" in comp:
                url = comp["download_url"]
                fname = url.split("/")[-1]
                zip_path = config.DOWNLOADS_DIR / fname
                _download(url, zip_path, label, pct_base, pct_base + (pct_next - pct_base) // 2)
                _set("extracting", f"解壓縮 {label}...", pct_base + (pct_next - pct_base) // 2)
                dest = config.RUNTIME_DIR / comp["extract_to"]
                _extract_zip(zip_path, dest, comp.get("strip_top_dir", False))
                zip_path.unlink(missing_ok=True)

            # ── 多步驟安裝（如 CosyVoice2）────────────
            if "steps" in comp:
                steps = comp["steps"]
                for si, step in enumerate(steps):
                    step_label = step.get("label", f"步驟 {si+1}")
                    step_pct = pct_base + int((si + 1) / len(steps) * (pct_next - pct_base))
                    _set("installing", f"{label} — {step_label}", step_pct)

                    if "git_clone" in step:
                        clone_dest = Path(step["clone_to"].replace("{runtime_dir}", str(config.RUNTIME_DIR)))
                        _git_clone(step["git_clone"], clone_dest, step.get("branch", "main"))
                    elif "cmd" in step:
                        cmd = _resolve(step["cmd"], uv, venv_python)
                        _run_cmd(cmd, step_label)

            # ── 單一命令安裝 ──────────────────────────
            elif "install_cmd" in comp:
                _set("installing", f"安裝 {label}...", pct_base + 5)
                cmd = _resolve(comp["install_cmd"], uv, venv_python)
                _run_cmd(cmd, label)

            elif "cmd" in comp:
                _set("installing", f"安裝 {label}...", pct_base + 5)
                cmd = _resolve(comp["cmd"], uv, venv_python)
                _run_cmd(cmd, label)

            # 寫入安裝標記
            marker.touch()
            _set("checking", f"✓ {label} 安裝完成", pct_next)

        _set("complete", "所有元件安裝完成！🎉", 100)

    except Exception as e:
        _set("error", str(e), _progress.percent, str(e))


def _ensure_hf_hub(venv_python: str):
    """確保 huggingface_hub 已安裝（自我修復）"""
    check = subprocess.run(
        [venv_python, "-c", "import huggingface_hub"],
        capture_output=True
    )
    if check.returncode != 0:
        _set("installing", "安裝 huggingface_hub...", _progress.percent)
        subprocess.run(
            [str(config.UV_EXE), "pip", "install",
             "--python", venv_python, "huggingface_hub>=0.23"],
            check=True, capture_output=True
        )


def _install_model_cosyvoice():
    """
    完整安裝 CosyVoice2：
      1. Clone 程式碼（若不存在）
      2. 安裝 PyTorch + 依賴套件（若不存在）
      3. 下載模型權重
    """
    try:
        venv_python = str(config.VENV_DIR / "Scripts" / "python.exe")
        uv = str(config.UV_EXE)

        # ── 步驟 1：確認 huggingface_hub ──────────────────
        _set("installing", "確認下載工具...", 3)
        _ensure_hf_hub(venv_python)

        # ── 步驟 2：Clone CosyVoice 程式碼 ────────────────
        if not config.COSYVOICE_REPO.exists():
            _set("installing", "複製 CosyVoice2 程式碼（需要 git）...", 6)
            _git_clone(
                "https://github.com/FunAudioLLM/CosyVoice.git",
                config.COSYVOICE_REPO,
                "main",
            )
        else:
            _set("checking", "✓ CosyVoice2 程式碼已存在", 6)

        # ── 步驟 3：安裝 PyTorch（自動依硬體選擇 build）────────────
        # 跨機器自動選擇最佳 wheel：
        #   nvidia-cuda → cu121 (Windows/Linux)
        #   apple-mps   → 預設 wheel（macOS PyTorch 已內建 MPS）
        #   amd-rocm    → rocm6.0 (Linux only)
        #   cpu-only    → cpu wheel
        info = system_probe.probe()
        profile = info.install_profile

        if profile == "nvidia-cuda":
            index_url = "https://download.pytorch.org/whl/cu121"
            variant_label = "CUDA 12.1"
            expected_tag  = "+cu"
        elif profile == "apple-mps":
            index_url = None   # 用 PyPI 預設（macOS 預設 wheel 內含 MPS 支援）
            variant_label = "Apple MPS"
            expected_tag  = ""   # macOS wheel 無 +xxx 後綴
        elif profile == "amd-rocm":
            index_url = "https://download.pytorch.org/whl/rocm6.0"
            variant_label = "AMD ROCm 6.0"
            expected_tag  = "+rocm"
        else:
            index_url = "https://download.pytorch.org/whl/cpu"
            variant_label = "CPU"
            expected_tag  = "+cpu"

        check_torch = subprocess.run(
            [venv_python, "-c",
             "import torch; print(torch.__version__); "
             "print('cuda=', torch.cuda.is_available()); "
             "print('mps=', getattr(torch.backends,'mps',None) and torch.backends.mps.is_available())"],
            capture_output=True, text=True,
        )
        installed_ver = (check_torch.stdout.splitlines() or [""])[0].strip()
        # 判斷已裝版本是否符合目前硬體 profile
        if check_torch.returncode != 0 or not installed_ver:
            needs_install = True
        elif expected_tag and expected_tag not in installed_ver:
            needs_install = True
        elif not expected_tag and any(t in installed_ver for t in ("+cu","+rocm","+cpu")):
            needs_install = True   # Apple MPS 期望乾淨版本號
        else:
            needs_install = False

        if needs_install:
            _set("installing", f"安裝 PyTorch {variant_label} 版（約 300MB~2GB，請耐心等待）...", 12)
            if installed_ver:
                subprocess.run(
                    [uv, "pip", "uninstall", "--python", venv_python, "torch", "torchaudio"],
                    capture_output=True
                )
            cmd = [
                uv, "pip", "install", "--python", venv_python,
                "torch==2.3.1", "torchaudio==2.3.1",
            ]
            if index_url:
                cmd += ["--index-url", index_url]
            _run_cmd(cmd, f"PyTorch {variant_label}")
        else:
            _set("checking", f"✓ PyTorch {installed_ver} 已安裝（{variant_label}）", 20)

        # ── 步驟 4：安裝 CosyVoice2 依賴套件 ──────────────
        check_omegaconf = subprocess.run(
            [venv_python, "-c", "import omegaconf"],
            capture_output=True,
        )
        # 每次都重新確認必要套件（以 CosyVoice2 官方 requirements.txt 為準）
        _set("installing", "安裝／確認 CosyVoice2 依賴套件...", 25)
        deps = [
            uv, "pip", "install", "--python", venv_python,
            # 核心 ML 依賴
            "omegaconf", "hydra-core",
            "onnxruntime",          # Windows 版（非 GPU）
            "soundfile", "librosa",
            "conformer==0.3.2",
            "diffusers", "transformers", "accelerate", "pydub",
            # CosyVoice2 必要依賴
            "HyperPyYAML",
            "matcha-tts",
            "modelscope",
            "openai-whisper",       # cosyvoice/cli/frontend.py 直接 import whisper
            # 其他官方清單套件
            "inflect", "pyworld", "rich", "wget",
            "x-transformers",
        ]
        _run_cmd(deps, "CosyVoice2 依賴套件")
        # WeTextProcessing 在 Windows 可能失敗，單獨安裝，失敗不中斷
        try:
            _run_cmd([
                uv, "pip", "install", "--python", venv_python,
                "WeTextProcessing",
            ], "WeTextProcessing")
        except Exception:
            pass

        # ── 步驟 5：下載模型權重 ───────────────────────────
        _set("downloading", "下載 CosyVoice2-0.5B 模型權重（約 1.5GB）...", 40)
        config.COSYVOICE_DIR.mkdir(parents=True, exist_ok=True)

        script = f"""
from huggingface_hub import snapshot_download
snapshot_download(
    'FunAudioLLM/CosyVoice2-0.5B',
    local_dir=r'{config.COSYVOICE_DIR}',
    ignore_patterns=['*.bin', 'flac/*'],
)
print('DONE')
"""
        proc = subprocess.run(
            [venv_python, "-c", script],
            capture_output=True, text=True, timeout=1800,
        )
        if proc.returncode != 0 or "DONE" not in proc.stdout:
            raise RuntimeError(f"模型下載失敗：{proc.stderr[-500:]}")

        config.MARKER_COSYVOICE.touch()
        _set("complete", "CosyVoice2 安裝完成！可以開始合成語音 🎉", 100)

    except Exception as e:
        _set("error", str(e), _progress.percent, str(e))


def _install_model_whisper():
    """下載 faster-whisper-medium 模型"""
    try:
        venv_python = str(config.VENV_DIR / "Scripts" / "python.exe")
        _set("installing", "確認下載工具...", 5)
        _ensure_hf_hub(venv_python)

        _set("downloading", "下載 Whisper Medium 模型（約 1.5GB）...", 10)
        config.WHISPER_DIR.mkdir(parents=True, exist_ok=True)

        script = f"""
from huggingface_hub import snapshot_download
snapshot_download(
    'Systran/faster-whisper-medium',
    local_dir=r'{config.WHISPER_DIR}',
)
print('DONE')
"""
        proc = subprocess.run(
            [venv_python, "-c", script],
            capture_output=True, text=True, timeout=1800
        )
        if proc.returncode != 0 or "DONE" not in proc.stdout:
            raise RuntimeError(f"Whisper 模型下載失敗：{proc.stderr[-300:]}")

        config.MARKER_WHISPER.touch()
        _set("complete", "Whisper Medium 模型下載完成！", 100)

    except Exception as e:
        _set("error", str(e), _progress.percent, str(e))


def start_install(profile: str) -> bool:
    """啟動安裝執行緒，回傳是否成功啟動"""
    global _install_thread
    with _install_lock:
        if is_installing():
            return False
        _set("checking", "開始安裝...", 0)
        _install_thread = threading.Thread(
            target=_install_profile, args=(profile,), daemon=True
        )
        _install_thread.start()
    return True


def start_model_download(model_id: str) -> bool:
    """啟動模型下載執行緒"""
    global _install_thread
    with _install_lock:
        if is_installing():
            return False
        if model_id == "cosyvoice2-0.5b":
            target = _install_model_cosyvoice
        elif model_id == "faster-whisper-medium":
            target = _install_model_whisper
        else:
            return False
        _set("checking", f"準備下載 {model_id}...", 0)
        _install_thread = threading.Thread(target=target, daemon=True)
        _install_thread.start()
    return True


def _repair_cosyvoice_deps():
    """只補裝缺失的 Python 依賴套件（不重下模型）"""
    try:
        venv_python = str(config.VENV_DIR / "Scripts" / "python.exe")
        uv = str(config.UV_EXE)
        _set("installing", "補裝 CosyVoice2 缺失套件...", 10)
        deps = [
            uv, "pip", "install", "--python", venv_python,
            "omegaconf", "hydra-core", "onnxruntime",
            "soundfile", "librosa", "conformer==0.3.2",
            "diffusers", "transformers", "accelerate", "pydub",
            "HyperPyYAML", "matcha-tts",
            "modelscope", "openai-whisper",
            "inflect", "pyworld", "rich", "wget", "x-transformers",
        ]
        _run_cmd(deps, "CosyVoice2 依賴套件")
        try:
            _run_cmd([uv, "pip", "install", "--python", venv_python,
                      "WeTextProcessing"], "WeTextProcessing")
        except Exception:
            pass
        config.MARKER_COSYVOICE.touch()
        _set("complete", "依賴套件補裝完成！請重試語音合成 🎉", 100)
    except Exception as e:
        _set("error", str(e), _progress.percent, str(e))


def start_repair_cosyvoice() -> bool:
    """啟動補裝執行緒"""
    global _install_thread
    with _install_lock:
        if is_installing():
            return False
        _set("checking", "準備補裝依賴套件...", 0)
        _install_thread = threading.Thread(target=_repair_cosyvoice_deps, daemon=True)
        _install_thread.start()
    return True
