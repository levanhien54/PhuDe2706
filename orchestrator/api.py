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

@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup: recover stale jobs from previous crash
    recovered = fail_stale_jobs(timeout_hours=2)
    if recovered:
        log.info("startup_recovered_stale_jobs", count=recovered)
    yield

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

@app.get("/api/videos")
async def list_videos():
    videos = [f for f in os.listdir(input_dir) if f.endswith(".mp4")]
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
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 500MB.")

    safe_name = os.path.basename(file.filename)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    # Check video magic bytes (MP4: ftyp at offset 4, MKV: EBML header 1A45DFA3, AVI: RIFF)
    if len(contents) >= 12:
        is_mp4 = contents[4:8] == b'ftyp'
        is_mkv = contents[:4] == b'\x1a\x45\xdf\xa3'
        is_avi = contents[:4] == b'RIFF' and contents[8:12] == b'AVI '
        is_mov = contents[4:8] in (b'ftyp', b'moov', b'mdat', b'wide', b'free')
        is_webm = contents[:4] == b'\x1a\x45\xdf\xa3'
        if not (is_mp4 or is_mkv or is_avi or is_mov or is_webm):
            raise HTTPException(status_code=415, detail="File content does not appear to be a valid video.")

    file_path = os.path.join(input_dir, safe_name)
    with open(file_path, "wb") as f:
        f.write(contents)
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
        
        # Kiểm tra xem có lỗi ở bước nào không
        success = True
        for stage, r in results.items():
            if not r.success:
                success = False
                
        critical_stages = {"audio_separate", "transcribe", "translate"}
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
async def start_dubbing(filename: str, background_tasks: BackgroundTasks, target_lang: str = "Tiếng Việt"):
    job_id = str(uuid.uuid4())[:8]
    save_job(job_id, filename, target_lang, settings.vram_profile)
    background_tasks.add_task(run_pipeline_task, job_id, filename, target_lang)
    return {"job_id": job_id, "message": "Dubbing started"}

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
async def resume_dubbing(job_id: str, background_tasks: BackgroundTasks):
    job_info = get_job(job_id)
    if not job_info or job_info["status"] != "AWAITING_REVIEW":
        raise HTTPException(status_code=400, detail="Job not ready for resume")
        
    background_tasks.add_task(run_pipeline_resume_task, job_id)
    return {"message": "Resumed"}
