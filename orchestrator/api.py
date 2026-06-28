import os
import uuid
import asyncio
import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Dict, Any, List

from orchestrator.config import get_settings
from orchestrator.logger import setup_logging, get_logger
from orchestrator.models import PipelineJob, SrtSegment
from orchestrator.pipeline import run_pipeline_phase1, run_pipeline_phase2
from orchestrator.database import (
    save_job, update_job_status, get_job, get_job_by_filename,
    save_segments, get_segments, update_segment_translation,
    get_jobs_by_filenames, fail_stale_jobs
)

log = get_logger(__name__)

job_queue = asyncio.Queue()

async def pipeline_worker():
    while True:
        task_func, args = await job_queue.get()
        try:
            await task_func(*args)
        except Exception as e:
            log.error("worker_error", error=str(e))
        finally:
            job_queue.task_done()

async def cleanup_loop():
    _active_statuses = {"PROCESSING", "AWAITING_REVIEW", "PROCESSING_PHASE2"}
    while True:
        await asyncio.sleep(3600)  # check every hour
        try:
            temp_dir = os.path.join(settings.data_dir, "temp")
            if not os.path.exists(temp_dir):
                continue
            import time
            now = time.time()
            for item in os.listdir(temp_dir):
                try:
                    path = os.path.join(temp_dir, item)
                    if not os.path.isdir(path):
                        continue
                    if now - os.path.getmtime(path) <= 86400:
                        continue
                    # Never wipe dirs whose job is still active (AWAITING_REVIEW can sit >24h)
                    is_active = False
                    for ext in ALLOWED_EXTENSIONS:
                        job_info = get_job_by_filename(item + ext)
                        if job_info and job_info.get("status") in _active_statuses:
                            is_active = True
                            break
                    if is_active:
                        continue
                    shutil.rmtree(path, ignore_errors=True)
                    log.info("cleaned_up_stale_temp", path=path)
                except Exception:
                    log.exception("cleanup_loop_item_failed", item=item)
        except Exception:
            log.exception("cleanup_loop_iteration_failed")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup: recover stale jobs from previous crash
    recovered = fail_stale_jobs(timeout_hours=2)
    if recovered:
        log.info("startup_recovered_stale_jobs", count=recovered)
        
    worker_task = asyncio.create_task(pipeline_worker())
    clean_task = asyncio.create_task(cleanup_loop())
    
    yield
    
    worker_task.cancel()
    clean_task.cancel()

app = FastAPI(title="Video Dubbing API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings = get_settings()
setup_logging("INFO")

input_dir = os.path.join(settings.data_dir, "input")
output_dir = os.path.join(settings.data_dir, "output")
os.makedirs(input_dir, exist_ok=True)
os.makedirs(output_dir, exist_ok=True)

app.mount("/output", StaticFiles(directory=output_dir), name="output")

class SegmentUpdate(BaseModel):
    id: int
    translated_text: str

ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}

def _is_valid_video_header(head: bytes) -> bool:
    """Validate first 12 bytes look like a known video container."""
    if len(head) < 12:
        return False
    is_mp4_mov = head[4:8] in (b'ftyp', b'moov', b'mdat', b'wide', b'free', b'skip')
    is_ebml = head[:4] == b'\x1a\x45\xdf\xa3'  # MKV and WebM share this
    is_avi = head[:4] == b'RIFF' and head[8:12] == b'AVI '
    return is_mp4_mov or is_ebml or is_avi

@app.get("/api/videos")
async def list_videos():
    videos = [f for f in os.listdir(input_dir) if os.path.splitext(f)[1].lower() in ALLOWED_EXTENSIONS]
    jobs_map = get_jobs_by_filenames(videos)  # single query
    result = []
    for v in videos:
        base_name = os.path.splitext(v)[0]
        output_file = os.path.join(output_dir, f"{base_name}_dubbed.mp4")
        job_info = jobs_map.get(v)
        status = "PENDING"
        if job_info:
            status = job_info["status"]
        elif os.path.exists(output_file):
            status = "COMPLETED"
        result.append({
            "filename": v,
            "status": status,
            "has_output": os.path.exists(output_file),
            "job_id": job_info["job_id"] if job_info else None
        })
    return {"videos": result}

def _cleanup_temp(base_name: str, data_dir: str):
    temp_dir = os.path.join(data_dir, "temp", base_name)
    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    MAX_SIZE = 500 * 1024 * 1024
    CHUNK = 1024 * 1024  # 1MB

    safe_name = os.path.basename(file.filename)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    file_path = os.path.join(input_dir, safe_name)
    total = 0
    first_chunk = b""
    try:
        with open(file_path, "wb") as f:
            while True:
                chunk = await file.read(CHUNK)
                if not chunk:
                    break
                if not first_chunk:
                    first_chunk = chunk[:12]
                    if not _is_valid_video_header(first_chunk):
                        raise HTTPException(status_code=415, detail="File content does not appear to be a valid video.")
                total += len(chunk)
                if total > MAX_SIZE:
                    raise HTTPException(status_code=413, detail="File too large. Maximum size is 500MB.")
                f.write(chunk)
    except HTTPException:
        if os.path.exists(file_path):
            os.remove(file_path)  # clean up partial upload
        raise
    return {"filename": safe_name, "message": "Uploaded successfully"}

async def run_pipeline_task(job_id: str, filename: str, target_lang: str):
    update_job_status(job_id, "PROCESSING")
    base_name = os.path.splitext(filename)[0]
    
    job = PipelineJob(
        job_id=job_id,
        filename=filename,
        base_name=base_name,
        target_language=target_lang,
        vram_profile=settings.vram_profile,
        created_at=datetime.utcnow()
    )
    
    try:
        results, segments = await run_pipeline_phase1(job, settings)
        
        critical_stages = {"audio_separate", "transcribe", "translate", "video_ocr"}
        success = all(
            results[s].success for s in critical_stages if s in results
        )
        phase1_summary = {"phase1": {k: {"success": v.success, "duration": v.duration_seconds} for k, v in results.items()}}
        if success:
            save_segments(job_id, segments)
            update_job_status(job_id, "AWAITING_REVIEW", phase1_summary)
        else:
            update_job_status(job_id, "FAILED", phase1_summary)
            _cleanup_temp(base_name, settings.data_dir)

    except Exception as e:
        log.error("pipeline_error", error=str(e))
        update_job_status(job_id, "FAILED", error=str(e))
        _cleanup_temp(base_name, settings.data_dir)


@app.post("/api/dub/{filename}")
async def start_dubbing(filename: str, target_lang: str = "Tiếng Việt"):
    job_id = str(uuid.uuid4())[:8]
    save_job(job_id, filename, target_lang, settings.vram_profile)
    job_queue.put_nowait((run_pipeline_task, (job_id, filename, target_lang)))
    return {"job_id": job_id, "message": "Dubbing queued"}

@app.get("/api/status/{filename}")
async def get_status(filename: str):
    job_info = get_job_by_filename(filename)
    if job_info:
        return job_info
        
    base_name = os.path.splitext(filename)[0]
    output_file = os.path.join(output_dir, f"{base_name}_dubbed.mp4")
    if os.path.exists(output_file):
        return {"filename": filename, "status": "COMPLETED"}
        
    return {"filename": filename, "status": "NOT_FOUND"}

@app.get("/api/jobs/{job_id}/segments")
async def api_get_segments(job_id: str):
    segs = get_segments(job_id)
    return {"segments": segs}

@app.put("/api/jobs/{job_id}/segments")
async def api_update_segment(job_id: str, data: SegmentUpdate):
    update_segment_translation(data.id, data.translated_text)
    return {"message": "Updated"}

async def run_pipeline_resume_task(job_id: str):
    update_job_status(job_id, "PROCESSING_PHASE2")
    job_info = get_job(job_id)
    if not job_info:
        return
        
    job = PipelineJob(
        job_id=job_id,
        filename=job_info["filename"],
        base_name=os.path.splitext(job_info["filename"])[0],
        target_language=job_info["target_lang"],
        vram_profile=job_info["vram_profile"],
    )
    
    # Lấy segments từ DB để format thành SrtSegment
    raw_segs = get_segments(job_id)
    segments = [
        SrtSegment(
            start=s["start_time"],
            end=s["end_time"],
            text=s["original_text"],
            translated=s["translated_text"],
            speaker=s.get("speaker")
        ) for s in raw_segs
    ]
    
    try:
        results = await run_pipeline_phase2(job, segments, settings)
        
        success = True
        for stage, r in results.items():
            if not r.success and stage != "lip_sync":
                success = False
                
        # Nối kết quả phase 1 và phase 2
        final_res = job_info.get("results", {})
        final_res["phase2"] = {k: {"success": v.success, "duration": v.duration_seconds} for k, v in results.items()}
        
        update_job_status(job_id, "COMPLETED" if success else "FAILED", final_res)
        _cleanup_temp(job.base_name, settings.data_dir)
    except Exception as e:
        log.error("pipeline_resume_error", error=str(e))
        update_job_status(job_id, "FAILED", error=str(e))
        _cleanup_temp(job.base_name, settings.data_dir)

@app.post("/api/jobs/{job_id}/resume")
async def resume_dubbing(job_id: str):
    job_info = get_job(job_id)
    if not job_info or job_info["status"] != "AWAITING_REVIEW":
        raise HTTPException(status_code=400, detail="Job not ready for resume")
        
    job_queue.put_nowait((run_pipeline_resume_task, (job_id,)))
    return {"message": "Resume queued"}
