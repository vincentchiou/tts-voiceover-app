"""
system_probe.py — 硬體環境偵測
偵測 GPU/VRAM/RAM/磁碟/Ollama，決定安裝設定檔
"""

import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

import config
import tts_providers


@dataclass
class GpuInfo:
    name: str = ""
    vram_mb: int = 0
    vendor: str = ""          # nvidia / amd / intel / apple
    cuda_version: str = ""


@dataclass
class SystemInfo:
    os: str = ""              # windows / linux / macos
    arch: str = ""            # x86_64 / arm64
    ram_gb: float = 0.0
    disk_free_gb: float = 0.0
    gpu: Optional[GpuInfo] = None
    install_profile: str = "cpu-only"   # nvidia-cuda / cpu-only
    ollama_available: bool = False
    ollama_models: list = field(default_factory=list)
    # 已安裝元件狀態
    ffmpeg_ready: bool = False
    gptsovits_ready: bool = False
    whisper_ready: bool = False        # whisper 模型已下載
    yt_dlp_ready: bool = False         # yt-dlp 套件已安裝
    faster_whisper_pkg_ready: bool = False  # faster-whisper 套件已安裝


def _run(cmd: list[str], timeout: int = 5) -> str:
    """執行命令，回傳 stdout，失敗則回傳空字串"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def _detect_nvidia() -> Optional[GpuInfo]:
    """偵測 NVIDIA GPU"""
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    out = _run([
        nvidia_smi,
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader,nounits"
    ])
    if not out:
        return None
    parts = [p.strip() for p in out.split(",")]
    if len(parts) < 3:
        return None

    # 取得 CUDA 版本（從 nvidia-smi 第一行標頭）
    header = _run([nvidia_smi])
    cuda_ver = ""
    m = re.search(r"CUDA Version:\s*([\d.]+)", header)
    if m:
        cuda_ver = m.group(1)

    return GpuInfo(
        name=parts[0],
        vram_mb=int(parts[1]) if parts[1].isdigit() else 0,
        vendor="nvidia",
        cuda_version=cuda_ver,
    )


def _detect_amd() -> Optional[GpuInfo]:
    """偵測 AMD GPU（Windows）"""
    out = _run(["wmic", "path", "win32_VideoController", "get", "name,AdapterRAM", "/format:list"])
    for line in out.splitlines():
        if "Name=" in line and "AMD" in line.upper():
            return GpuInfo(name=line.split("=", 1)[1], vendor="amd")
    return None


def _detect_apple_silicon() -> Optional[GpuInfo]:
    """偵測 Apple Silicon"""
    if platform.system() == "Darwin" and platform.machine() in ("arm64", "aarch64"):
        # 取得 unified memory 大小
        out = _run(["sysctl", "-n", "hw.memsize"])
        vram_mb = int(out) // (1024 * 1024) if out.isdigit() else 0
        return GpuInfo(name="Apple Silicon", vram_mb=vram_mb, vendor="apple")
    return None


def _get_ram_gb() -> float:
    """取得系統 RAM（GB）"""
    sys = platform.system()
    if sys == "Windows":
        # 方法 1：ctypes GlobalMemoryStatusEx（最可靠，不需任何外部命令）
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            msx = MEMORYSTATUSEX()
            msx.dwLength = ctypes.sizeof(msx)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(msx))
            if msx.ullTotalPhys > 0:
                return msx.ullTotalPhys / (1024 ** 3)
        except Exception:
            pass
        # 方法 2：wmic（備用）
        out = _run(["wmic", "ComputerSystem", "get", "TotalPhysicalMemory", "/value"])
        m = re.search(r"TotalPhysicalMemory=(\d+)", out)
        if m:
            return int(m.group(1)) / (1024 ** 3)
    elif sys == "Darwin":
        out = _run(["sysctl", "-n", "hw.memsize"])
        if out.isdigit():
            return int(out) / (1024 ** 3)
    elif sys == "Linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb / (1024 ** 2)
        except Exception:
            pass
    # 最後備用：psutil
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        pass
    return 0.0


def _get_disk_free_gb() -> float:
    """取得 APP_HOME 磁碟可用空間（GB）"""
    try:
        import shutil as _shutil
        total, used, free = _shutil.disk_usage(config.APP_HOME.parent)
        return free / (1024 ** 3)
    except Exception:
        return 0.0


def _check_ollama() -> tuple[bool, list[str]]:
    """檢查 Ollama 是否可用，並列出已安裝模型"""
    models = []

    # 方法 1：HTTP API（最可靠，Ollama 跑服務時不需要 PATH）
    try:
        import urllib.request, json as _json
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as resp:
            data = _json.loads(resp.read())
            for m in data.get("models", []):
                name = m.get("name", "")
                if name:
                    models.append(name)
            return True, models
    except Exception:
        pass

    # 方法 2：CLI（需要 ollama 在 PATH）
    if shutil.which("ollama"):
        out = _run(["ollama", "list"], timeout=3)
        for line in out.splitlines()[1:]:
            parts = line.split()
            if parts:
                models.append(parts[0])
        if out:
            return True, models

    return False, []


def _select_profile(gpu: Optional[GpuInfo], ram_gb: float) -> str:
    """根據硬體選擇安裝設定檔（可跨機器自動偵測）

    - NVIDIA GPU + ≥4GB VRAM → nvidia-cuda（PyTorch CUDA build）
    - Apple Silicon (M1/M2/M3/M4) → apple-mps（PyTorch MPS build，預設 wheel 即可）
    - AMD GPU on Linux → amd-rocm（僅 Linux 有 ROCm wheel）
    - 其他（含 AMD on Windows、Intel iGPU、無 GPU） → cpu-only
    """
    if gpu:
        if gpu.vendor == "nvidia" and gpu.vram_mb >= 4096:
            return "nvidia-cuda"
        if gpu.vendor == "apple":
            return "apple-mps"
        if gpu.vendor == "amd" and platform.system() == "Linux":
            return "amd-rocm"
    return "cpu-only"


def probe() -> SystemInfo:
    """執行完整硬體偵測，回傳 SystemInfo"""
    info = SystemInfo()
    info.os   = platform.system().lower()   # windows / linux / darwin
    info.arch = platform.machine().lower()

    # GPU 偵測（依優先順序）
    info.gpu = (
        _detect_apple_silicon() or
        _detect_nvidia() or
        _detect_amd()
    )

    info.ram_gb       = _get_ram_gb()
    info.disk_free_gb = _get_disk_free_gb()
    info.install_profile = _select_profile(info.gpu, info.ram_gb)

    # Ollama
    info.ollama_available, info.ollama_models = _check_ollama()

    # 已安裝元件狀態
    # GPT-SoVITS 需要：marker 存在 + 程式碼 repo 已 clone + 權重目錄存在
    info.ffmpeg_ready    = config.MARKER_FFMPEG.exists()
    info.gptsovits_ready = (
        config.MARKER_GPTSOVITS.exists()
        and config.GPTSOVITS_REPO.exists()
        and config.GPTSOVITS_PRETRAINED.exists()
    )
    info.whisper_ready   = config.MARKER_WHISPER.exists()

    # Python 套件偵測（後端 venv 內）
    info.yt_dlp_ready = _python_pkg_available("yt_dlp")
    info.faster_whisper_pkg_ready = _python_pkg_available("faster_whisper")

    return info


def _python_pkg_available(module: str) -> bool:
    """檢查後端 venv 是否能 import 指定模組（在子行程中試）"""
    import sys
    py = sys.executable  # 當前 process 已在 venv 內
    try:
        r = subprocess.run(
            [py, "-c", f"import {module}"],
            capture_output=True, timeout=8,
        )
        return r.returncode == 0
    except Exception:
        return False


def probe_dict() -> dict:
    """回傳可序列化的字典（給 API 用）"""
    info = probe()
    return {
        "os": info.os,
        "arch": info.arch,
        "ram_gb": round(info.ram_gb, 1),
        "disk_free_gb": round(info.disk_free_gb, 1),
        "gpu": {
            "name": info.gpu.name,
            "vram_mb": info.gpu.vram_mb,
            "vendor": info.gpu.vendor,
            "cuda_version": info.gpu.cuda_version,
        } if info.gpu else None,
        "install_profile": info.install_profile,
        "ollama_available": info.ollama_available,
        "ollama_models": info.ollama_models,
        "components": {
            "ffmpeg": info.ffmpeg_ready,
            "gptsovits": info.gptsovits_ready,
            # GPT-SoVITS 子狀態：方便前端顯示更細的訊息
            "gptsovits_code": config.GPTSOVITS_REPO.exists(),
            "gptsovits_model": config.GPTSOVITS_PRETRAINED.exists(),
            "whisper": info.whisper_ready,
            "yt_dlp": info.yt_dlp_ready,
            "faster_whisper_pkg": info.faster_whisper_pkg_ready,
            "tts_providers": tts_providers.provider_status(),
        },
        "ready": info.ffmpeg_ready and info.gptsovits_ready,
    }
