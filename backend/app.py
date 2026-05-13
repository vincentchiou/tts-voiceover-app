"""
app.py — FastAPI 主程式
提供 REST API + 靜態前端服務
"""

import asyncio
import concurrent.futures
import json
import logging
import os
import shutil
import uuid
from pathlib import Path

# 設定 logging，輸出到 console（start.ps1 的終端機視窗可見）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

import config
import content as content_mod
import jobs
import runtime_manager
import system_probe

config.ensure_dirs()

app = FastAPI(title="文生語音 APP", version="1.0.0")

# CORS（開發用，允許本機各 port）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8765", "http://127.0.0.1:8765",
                   "http://localhost:5173", "null"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 掛載靜態檔（CSS / JS）
if config.FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(config.FRONTEND_DIR)), name="static")


# ── 生命週期：關閉時停掉 GPT-SoVITS 子行程 ────────────────────
@app.on_event("shutdown")
def _on_shutdown():
    try:
        import gptsovits_service
        gptsovits_service.stop()
    except Exception:
        pass


# ── 首頁：回傳前端 HTML ────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = config.FRONTEND_DIR / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return HTMLResponse("<h1>前端檔案未找到</h1>", status_code=404)


# ── 健康檢查 ──────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── 硬體 / 安裝狀態 ───────────────────────────────────────

@app.get("/system/check")
async def system_check():
    # probe_dict() 含 subprocess 呼叫，用 executor 避免阻塞 event loop
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(pool, system_probe.probe_dict)
    return result


# ── 環境安裝 ──────────────────────────────────────────────

class InstallRequest(BaseModel):
    profile: str = "auto"  # auto / nvidia-cuda / cpu-only


@app.post("/setup/install")
async def setup_install(req: InstallRequest):
    profile = req.profile
    if profile == "auto":
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            info = await loop.run_in_executor(pool, system_probe.probe)
        profile = info.install_profile

    started = runtime_manager.start_install(profile)
    if not started:
        return {"status": "already_running"}
    return {"status": "started", "profile": profile}


@app.get("/setup/progress")
async def setup_progress():
    """SSE 串流安裝進度"""
    async def generate():
        while True:
            progress = runtime_manager.get_progress()
            data = json.dumps(progress, ensure_ascii=False)
            yield f"data: {data}\n\n"
            if progress["stage"] in ("complete", "error"):
                break
            await asyncio.sleep(0.8)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/setup/progress/once")
async def setup_progress_once():
    """一次性取得目前安裝進度（供輪詢用）"""
    return runtime_manager.get_progress()


# ── 模型下載 ──────────────────────────────────────────────

class ModelDownloadRequest(BaseModel):
    model_id: str  # gptsovits-v4 / faster-whisper-medium


@app.post("/models/download")
async def download_model(req: ModelDownloadRequest):
    started = runtime_manager.start_model_download(req.model_id)
    if not started:
        return {"status": "already_running"}
    return {"status": "started", "model_id": req.model_id}


# ── LLM 設定 ──────────────────────────────────────────────

@app.get("/settings/llm")
async def get_llm_settings():
    s = content_mod.load_llm_settings()
    # 不回傳完整 API key（只回傳是否已設定）
    return {
        **s,
        "openai_api_key":    "***" if s.get("openai_api_key") else "",
        "anthropic_api_key": "***" if s.get("anthropic_api_key") else "",
    }


class LlmSettingsRequest(BaseModel):
    provider:            Optional[str] = None
    ollama_model:        Optional[str] = None
    ollama_base_url:     Optional[str] = None
    lmstudio_base_url:   Optional[str] = None
    lmstudio_model:      Optional[str] = None
    openai_api_key:      Optional[str] = None
    openai_model:        Optional[str] = None
    anthropic_api_key:   Optional[str] = None
    anthropic_model:     Optional[str] = None


@app.post("/settings/llm")
async def save_llm_settings(req: LlmSettingsRequest):
    current = content_mod.load_llm_settings()
    update  = {k: v for k, v in req.model_dump().items() if v is not None}
    # "***" 代表維持原值（前端沒改 key）
    for key in ("openai_api_key", "anthropic_api_key"):
        if update.get(key) == "***":
            update[key] = current.get(key, "")
    merged = content_mod.save_llm_settings({**current, **update})
    return {"status": "ok", "provider": merged["provider"]}


@app.get("/settings/llm/lmstudio/models")
async def list_lmstudio_models(base_url: str = ""):
    """列出 LMStudio 可用模型（用於前端下拉選單）"""
    import httpx
    url = (base_url or "").strip().rstrip("/")
    if not url:
        s = content_mod.load_llm_settings()
        url = s.get("lmstudio_base_url", "http://localhost:1234").rstrip("/")
    try:
        resp = httpx.get(f"{url}/v1/models", timeout=5.0)
        if resp.status_code != 200:
            return {"status": "error", "models": [], "message": f"HTTP {resp.status_code}"}
        data = resp.json()
        models = [m.get("id") for m in data.get("data", []) if m.get("id")]
        # 過濾掉 embedding 類模型（不能拿來做 chat completion）
        models = [m for m in models if "embed" not in m.lower()]
        return {"status": "ok", "models": models}
    except Exception as e:
        return {"status": "error", "models": [], "message": str(e)}


@app.post("/settings/llm/test")
async def test_llm_connection():
    """快速測試 LLM 連線是否正常"""
    try:
        result = content_mod._call_llm(
            system="你是助手。",
            user="請回覆「連線成功」四個字，不要說其他的。",
            target_chars=10,
        )
        if result:
            return {"status": "ok", "response": result[:50]}
        return {"status": "error", "response": "LLM 未回應，請檢查設定"}
    except Exception as e:
        return {"status": "error", "response": str(e)}


@app.post("/setup/repair-cosyvoice")
async def repair_cosyvoice():
    """補裝 CosyVoice2 缺失的 Python 依賴套件（不重下模型）"""
    started = runtime_manager.start_repair_cosyvoice()
    if not started:
        return {"status": "already_running"}
    return {"status": "started"}


# ── 音色管理 ──────────────────────────────────────────────

@app.get("/voices")
async def list_voices():
    """列出預設音色 + 已複製音色"""
    models_json = config.MANIFESTS_DIR / "models.json"
    data = json.loads(models_json.read_text(encoding="utf-8"))
    preset = data.get("preset_voices", {})

    import audio as audio_mod
    cloned = audio_mod.list_cloned_voices()

    return {
        "preset": [
            {"id": k, "label": v["label"], "gender": v.get("gender", ""),
             "is_cloned": False}
            for k, v in preset.items()
        ],
        "cloned": [
            {"id": v["id"], "label": v["label"], "is_cloned": True}
            for v in cloned
        ],
    }


@app.post("/voices/clone")
async def clone_voice(
    file: UploadFile = File(...),
    voice_name: str = Form(...),
    reference_text: str = Form(""),
):
    """上傳參考音檔，建立複製音色"""
    # 安全化 voice_id
    voice_id = "cloned_" + "".join(
        c for c in voice_name if c.isalnum() or c in ("-", "_")
    )[:20] or f"cloned_{uuid.uuid4().hex[:8]}"

    # 儲存上傳的音檔
    upload_path = config.UPLOADS_DIR / f"{voice_id}_ref{Path(file.filename).suffix}"
    upload_path.write_bytes(await file.read())

    import audio as audio_mod
    try:
        meta = audio_mod.clone_voice(upload_path, voice_id, reference_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        upload_path.unlink(missing_ok=True)

    return {"status": "ok", "voice_id": voice_id, "label": voice_name}


# ── 工作管理 ──────────────────────────────────────────────

class JobCreateRequest(BaseModel):
    input_type: str       # topic / pdf_path / youtube / srt / script
    content: str          # 主題文字 / 已上傳 PDF 路徑 / YouTube URL / SRT/腳本文字
    output_mode: str      # single / duo / short_video
    target_minutes: float = 5.0
    voice_a: str = "台灣女聲"
    voice_b: str = "台灣男聲"
    custom_voice_a: str = ""
    custom_voice_b: str = ""


@app.post("/jobs")
async def create_job(req: JobCreateRequest):
    job = jobs.create_job(
        input_type=req.input_type,
        output_mode=req.output_mode,
        raw_content=req.content,
        target_minutes=req.target_minutes,
        voice_a=req.voice_a,
        voice_b=req.voice_b,
        custom_voice_a=req.custom_voice_a,
        custom_voice_b=req.custom_voice_b,
    )
    return jobs.job_to_dict(job)


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="工作不存在")
    return jobs.job_to_dict(job)


@app.get("/jobs/{job_id}/events")
async def job_events(job_id: str):
    """SSE 串流工作進度"""
    async def generate():
        while True:
            job = jobs.get_job(job_id)
            if not job:
                yield f"data: {json.dumps({'error': '工作不存在'})}\n\n"
                break
            data = json.dumps(jobs.job_to_dict(job), ensure_ascii=False)
            yield f"data: {data}\n\n"
            if job.status in jobs.TERMINAL_STATUSES:
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(generate(), media_type="text/event-stream")


class ScriptUpdateRequest(BaseModel):
    script_text: str


@app.put("/jobs/{job_id}/script")
async def update_script(job_id: str, req: ScriptUpdateRequest):
    job = jobs.update_script(job_id, req.script_text)
    if not job:
        raise HTTPException(status_code=400, detail="無法修改腳本（狀態不允許）")
    return jobs.job_to_dict(job)


@app.post("/jobs/{job_id}/approve")
async def approve_job(job_id: str):
    job = jobs.approve_job(job_id)
    if not job:
        raise HTTPException(status_code=400, detail="無法核准（工作不存在或狀態不正確）")
    return jobs.job_to_dict(job)


@app.get("/jobs/{job_id}/download")
async def download_audio(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="工作不存在")
    if job.status != jobs.STATUS_COMPLETE:
        raise HTTPException(status_code=400, detail="音訊尚未合成完成")
    mp3_path = Path(job.audio_path)
    if not mp3_path.exists():
        raise HTTPException(status_code=404, detail="音訊檔案不存在")
    return FileResponse(
        path=str(mp3_path),
        media_type="audio/mpeg",
        filename=f"tts_{job_id[:8]}.mp3",
    )


# ── 檔案上傳（PDF / SRT） ────────────────────────────────

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """上傳 PDF 或 SRT 檔案，回傳檔案路徑供後續使用"""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".pdf", ".srt", ".txt"):
        raise HTTPException(status_code=400, detail="僅支援 PDF / SRT / TXT 檔案")

    upload_id = uuid.uuid4().hex[:12]
    save_path = config.UPLOADS_DIR / f"{upload_id}{suffix}"
    save_path.write_bytes(await file.read())

    # 若是 SRT，直接讀取文字
    if suffix == ".srt":
        import video_handler
        content = video_handler.parse_srt(save_path.read_text(encoding="utf-8", errors="replace"))
        save_path.unlink(missing_ok=True)
        return {"type": "srt", "content": content}

    return {"type": "pdf", "path": str(save_path), "filename": file.filename}
