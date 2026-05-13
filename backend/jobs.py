"""
jobs.py — 工作狀態機
管理 TTS 工作的完整生命週期：建立 → 腳本生成 → 審閱 → 合成 → 完成
"""

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import config


# ── 狀態常數 ──────────────────────────────────────────────
STATUS_QUEUED          = "queued"
STATUS_RUNNING         = "running"
STATUS_AWAITING_REVIEW = "awaiting_review"
STATUS_SYNTHESIZING    = "synthesizing"
STATUS_COMPLETE        = "complete"
STATUS_FAILED          = "failed"

TERMINAL_STATUSES = {STATUS_AWAITING_REVIEW, STATUS_COMPLETE, STATUS_FAILED}


@dataclass
class Segment:
    """腳本的一個說話段落"""
    speaker: str    # "主持A" / "主持B" / "旁白"
    text: str
    audio_path: str = ""


@dataclass
class Job:
    id: str
    status: str = STATUS_QUEUED
    progress: int = 0
    message: str = ""
    error: str = ""

    # 輸入
    input_type: str = ""       # topic / pdf / youtube / srt / script
    output_mode: str = ""      # single / duo / short_video
    target_minutes: float = 5.0
    voice_a: str = "台灣女聲"
    voice_b: str = "台灣男聲"
    custom_voice_a: str = ""   # 複製音色 ID（若有）
    custom_voice_b: str = ""

    # 腳本
    raw_content: str = ""      # 原始輸入文字
    script_text: str = ""      # 最終腳本文字
    segments: list = field(default_factory=list)  # List[dict]
    estimated_minutes: float = 0.0

    # 輸出
    audio_path: str = ""
    script_path: str = ""

    # 時間戳
    created_at: str = ""
    updated_at: str = ""


# ── 記憶體中的工作字典（重啟後清空）────────────────────
_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat()


def create_job(
    input_type: str,
    output_mode: str,
    raw_content: str,
    target_minutes: float = 5.0,
    voice_a: str = "台灣女聲",
    voice_b: str = "台灣男聲",
    custom_voice_a: str = "",
    custom_voice_b: str = "",
) -> Job:
    """建立新工作並立即啟動腳本生成"""
    job = Job(
        id=str(uuid.uuid4()),
        input_type=input_type,
        output_mode=output_mode,
        raw_content=raw_content,
        target_minutes=target_minutes,
        voice_a=voice_a,
        voice_b=voice_b,
        custom_voice_a=custom_voice_a,
        custom_voice_b=custom_voice_b,
        created_at=_now(),
        updated_at=_now(),
    )
    # 建立工作資料夾
    job_dir = config.JOBS_DIR / job.id
    job_dir.mkdir(parents=True, exist_ok=True)

    with _jobs_lock:
        _jobs[job.id] = job

    # 在背景執行緒中處理
    t = threading.Thread(target=_process_job, args=(job.id,), daemon=True)
    t.start()

    return job


def get_job(job_id: str) -> Optional[Job]:
    with _jobs_lock:
        return _jobs.get(job_id)


def update_script(job_id: str, script_text: str) -> Optional[Job]:
    """使用者修改腳本（只能在 awaiting_review 狀態）"""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        if job.status not in (STATUS_AWAITING_REVIEW, STATUS_FAILED):
            return None
        job.script_text = script_text
        job.segments = _parse_segments(script_text, job.output_mode)
        job.estimated_minutes = _estimate_minutes(script_text)
        job.updated_at = _now()
        # 更新磁碟上的腳本檔
        _save_script(job)
    return job


def approve_job(job_id: str) -> Optional[Job]:
    """核准腳本，啟動 TTS 合成"""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job or job.status != STATUS_AWAITING_REVIEW:
            return None
        job.status = STATUS_SYNTHESIZING
        job.progress = 70
        job.message = "開始語音合成..."
        job.updated_at = _now()

    t = threading.Thread(target=_synthesize_job, args=(job_id,), daemon=True)
    t.start()
    return job


def job_to_dict(job: Job) -> dict:
    return {
        "id":                job.id,
        "status":            job.status,
        "progress":          job.progress,
        "message":           job.message,
        "error":             job.error,
        "input_type":        job.input_type,
        "output_mode":       job.output_mode,
        "target_minutes":    job.target_minutes,
        "voice_a":           job.voice_a,
        "voice_b":           job.voice_b,
        "script_text":       job.script_text,
        "segments":          job.segments,
        "estimated_minutes": job.estimated_minutes,
        "audio_path":        job.audio_path,
        "created_at":        job.created_at,
        "updated_at":        job.updated_at,
    }


# ── 內部處理函式 ──────────────────────────────────────────

def _update(job_id: str, **kwargs):
    """更新工作狀態（執行緒安全）"""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            for k, v in kwargs.items():
                setattr(job, k, v)
            job.updated_at = _now()


def _process_job(job_id: str):
    """背景執行：輸入處理 → 腳本生成"""
    try:
        job = _jobs.get(job_id)
        if not job:
            return

        _update(job_id, status=STATUS_RUNNING, progress=5, message="準備處理輸入...")

        # ── Step 1：取得原始文字 ──────────────────────
        import content

        if job.input_type == "topic":
            _update(job_id, progress=15, message="用 AI 生成腳本中...")
            script_text = content.from_topic(
                topic=job.raw_content,
                output_mode=job.output_mode,
                target_minutes=job.target_minutes,
            )

        elif job.input_type == "pdf":
            _update(job_id, progress=10, message="讀取 PDF 中...")
            import pdf_handler
            extracted = pdf_handler.extract(Path(job.raw_content))
            _update(job_id, progress=25, message="AI 改寫成口語腳本...")
            script_text = content.from_text(
                text=extracted,
                output_mode=job.output_mode,
                target_minutes=job.target_minutes,
            )

        elif job.input_type == "youtube":
            _update(job_id, progress=10, message="下載影片音訊...")
            import video_handler
            job_dir = config.JOBS_DIR / job_id
            audio_file = video_handler.download_audio(job.raw_content, job_dir)
            _update(job_id, progress=30, message="AI 語音轉文字中...")
            transcript = video_handler.transcribe(audio_file)
            _update(job_id, progress=50, message="AI 改寫成口語腳本...")
            script_text = content.from_text(
                text=transcript,
                output_mode=job.output_mode,
                target_minutes=job.target_minutes,
            )

        elif job.input_type in ("srt", "script"):
            _update(job_id, progress=20, message="處理文字內容...")
            if job.input_type == "srt":
                import video_handler
                text = video_handler.parse_srt(job.raw_content)
            else:
                text = job.raw_content
            script_text = content.from_text(
                text=text,
                output_mode=job.output_mode,
                target_minutes=job.target_minutes,
                rewrite=False,  # 腳本直接使用，不改寫
            )
        else:
            raise ValueError(f"未知的輸入類型：{job.input_type}")

        # ── Step 2：解析腳本段落 ──────────────────────
        segments = _parse_segments(script_text, job.output_mode)
        estimated = _estimate_minutes(script_text)

        _update(
            job_id,
            status=STATUS_AWAITING_REVIEW,
            progress=65,
            message="腳本已生成，請審閱後確認合成",
            script_text=script_text,
            segments=segments,
            estimated_minutes=estimated,
        )

        # 儲存腳本檔
        job = _jobs.get(job_id)
        if job:
            _save_script(job)

    except Exception as e:
        _update(job_id, status=STATUS_FAILED, message="處理失敗", error=str(e))


def _synthesize_job(job_id: str):
    """背景執行：TTS 合成"""
    try:
        import audio

        job = _jobs.get(job_id)
        if not job:
            return

        # 先確認 GPT-SoVITS 環境就緒，給出明確錯誤訊息
        if not config.GPTSOVITS_REPO.exists():
            raise RuntimeError(
                "GPT-SoVITS 程式碼尚未安裝。\n"
                "請在專案根目錄執行 setup_gptsovits.ps1 完成安裝。"
            )
        if not config.MARKER_GPTSOVITS.exists():
            raise RuntimeError(
                "GPT-SoVITS 尚未完成設定。\n"
                "請執行 setup_gptsovits.ps1 直到看到「安裝完成！」訊息。"
            )

        job_dir = config.JOBS_DIR / job_id

        _update(job_id, progress=72, message="載入語音模型...")

        audio_file = audio.synthesize(
            job=job,
            job_dir=job_dir,
            progress_cb=lambda p, msg: _update(job_id, progress=p, message=msg),
        )

        _update(
            job_id,
            status=STATUS_COMPLETE,
            progress=100,
            message="語音合成完成！🎉",
            audio_path=str(audio_file),
        )

    except Exception as e:
        _update(job_id, status=STATUS_FAILED, message="合成失敗", error=str(e))


def _parse_segments(script_text: str, output_mode: str) -> list[dict]:
    """將腳本文字解析成段落列表"""
    segments = []
    if output_mode == "duo":
        # 支援多種 LLM 可能輸出的格式
        _A_PREFIXES = ("主持A：", "主持A:", "小艾：", "小艾:", "A：", "A:")
        _B_PREFIXES = ("主持B：", "主持B:", "大維：", "大維:", "B：", "B:")
        for line in script_text.splitlines():
            line = line.strip()
            if not line:
                continue
            matched = False
            for pfx in _A_PREFIXES:
                if line.startswith(pfx):
                    segments.append({"speaker": "主持A", "text": line[len(pfx):].strip()})
                    matched = True; break
            if not matched:
                for pfx in _B_PREFIXES:
                    if line.startswith(pfx):
                        segments.append({"speaker": "主持B", "text": line[len(pfx):].strip()})
                        matched = True; break
            if not matched:
                if segments:
                    segments[-1]["text"] += " " + line
                else:
                    segments.append({"speaker": "主持A", "text": line})
    elif output_mode == "short_video":
        import re
        for line in script_text.splitlines():
            line = line.strip()
            if not line:
                continue
            # 移除時間戳記 [00:00] 等
            text = re.sub(r"^\[\d{2}:\d{2}\]\s*", "", line)
            if text:
                segments.append({"speaker": "旁白", "text": text})
    else:  # single
        for para in script_text.split("\n\n"):
            para = para.strip()
            if para:
                segments.append({"speaker": "旁白", "text": para})
    return segments


def _estimate_minutes(text: str) -> float:
    """估算腳本朗讀時長（分鐘）"""
    # 中文字約 260 字/分鐘（口語速度）
    zh_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    en_words = len([w for w in text.split() if w.isascii()])
    total_units = zh_chars + en_words * 2
    return round(total_units / 260, 1)


def _save_script(job: Job):
    """將腳本儲存到工作資料夾"""
    job_dir = config.JOBS_DIR / job.id
    job_dir.mkdir(exist_ok=True)
    script_path = job_dir / "script.md"
    script_path.write_text(job.script_text, encoding="utf-8")
    job.script_path = str(script_path)
