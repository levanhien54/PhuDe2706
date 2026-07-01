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
from orchestrator.pipeline import (
    run_pipeline_phase1, run_pipeline_phase2,
    JobCancelled, request_cancel, is_cancel_requested, clear_cancel,
)
from orchestrator.database import (
    save_job, update_job_status, get_job, get_job_by_filename,
    save_segments, get_segments, update_segment_translation,
    get_jobs_by_filenames, get_jobs_by_status, fail_stale_jobs,
    get_watch_config, set_watch_config,
    get_app_config, set_app_config
)

log = get_logger(__name__)

job_queue = asyncio.Queue()
# Currently-running pipeline tasks, keyed by job_id, so a cancel request can interrupt a
# stage mid-await (the cooperative _check_cancel covers the gaps between stages). args[0]
# is the job_id for both run_pipeline_task and run_pipeline_resume_task.
_running_tasks: dict[str, "asyncio.Task"] = {}

async def pipeline_worker():
    while True:
        task_func, args = await job_queue.get()
        job_id = args[0] if args else None
        try:
            t = asyncio.create_task(task_func(*args))
            if job_id:
                _running_tasks[job_id] = t
            await t
        except asyncio.CancelledError:
            log.info("worker_task_cancelled", job_id=job_id)
        except Exception as e:
            log.error("worker_error", error=str(e))
        finally:
            if job_id:
                _running_tasks.pop(job_id, None)
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
            # A temp dir is named after the job base_name (filename without extension). Match
            # active jobs on base_name directly rather than reconstructing filename+ext: the
            # old approach queried `item + ext` with lowercase extensions and missed jobs whose
            # stored extension case differs (SQLite compares case-sensitively), e.g. '.MP4',
            # so it could wipe the temp dir of a job still AWAITING_REVIEW.
            active_base_names = {
                os.path.splitext(j["filename"])[0]
                for j in get_jobs_by_status(_active_statuses)
            }
            for item in await asyncio.to_thread(os.listdir, temp_dir):
                try:
                    path = os.path.join(temp_dir, item)
                    if not os.path.isdir(path):
                        continue
                    if now - os.path.getmtime(path) <= 86400:
                        continue
                    # Never wipe dirs whose job is still active (AWAITING_REVIEW can sit >24h)
                    if item in active_base_names:
                        continue
                    # rmtree of a large frame dir off the event loop so status/cancel stay responsive
                    await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)
                    log.info("cleaned_up_stale_temp", path=path)
                except Exception:
                    log.exception("cleanup_loop_item_failed", item=item)
        except Exception:
            log.exception("cleanup_loop_iteration_failed")

WATCH_INTERVAL_SECONDS = 20

def _file_is_stable(path: str, settle_seconds: float = 5.0) -> bool:
    """True if the file hasn't been modified for a few seconds — avoids importing a
    video that is still being copied into the watch folder."""
    import time
    try:
        return (time.time() - os.path.getmtime(path)) >= settle_seconds
    except OSError:
        return False

async def scan_watch_folder_once() -> dict:
    """Scan the configured watch folder, import any new (unprocessed) video into
    data/input and queue a full auto-process job. Returns what it did."""
    cfg = get_watch_config()
    result = {"imported": [], "skipped": 0, "enabled": bool(cfg.get("enabled"))}
    folder = (cfg.get("folder") or "").strip()
    if not cfg.get("enabled") or not folder:
        return result
    if not os.path.isdir(folder):
        log.warning("watch_folder_missing", folder=folder)
        result["error"] = "folder_not_found"
        return result
    try:
        entries = sorted(os.listdir(folder))
    except OSError as e:
        log.warning("watch_folder_unreadable", folder=folder, error=str(e))
        result["error"] = "folder_unreadable"
        return result

    for fn in entries:
        if os.path.splitext(fn)[1].lower() not in ALLOWED_EXTENSIONS:
            continue
        src = os.path.join(folder, fn)
        if not os.path.isfile(src):
            continue
        dest = os.path.join(input_dir, fn)
        # Skip if a non-failed job already exists for this name (processing / awaiting / done).
        existing = get_job_by_filename(fn)
        if existing and existing.get("status") != "FAILED":
            result["skipped"] += 1
            continue
        # No job, or only a FAILED one. If a copy already exists, re-import ONLY when the source
        # is newer (a corrected re-drop) — otherwise we'd reprocess the same failed file forever.
        if os.path.exists(dest):
            try:
                if os.path.getmtime(src) <= os.path.getmtime(dest):
                    result["skipped"] += 1
                    continue
            except OSError:
                result["skipped"] += 1
                continue
        if not _file_is_stable(src):
            continue  # still being written; pick it up on the next scan
        # Atomic import: copy to a temp name then rename, so a crash mid-copy never leaves a
        # truncated file at dest that a later scan would treat as already-imported.
        tmp_dest = dest + ".part"
        try:
            await asyncio.to_thread(shutil.copy2, src, tmp_dest)
            os.replace(tmp_dest, dest)
        except Exception as e:
            if os.path.exists(tmp_dest):
                try:
                    os.remove(tmp_dest)
                except OSError:
                    pass
            log.warning("watch_copy_failed", file=fn, error=str(e))
            continue
        job_id = str(uuid.uuid4())[:8]
        save_job(
            job_id, fn, cfg["target_lang"], settings.vram_profile,
            enable_lipsync=bool(cfg["enable_lipsync"]),
            enable_ocr=bool(cfg["enable_ocr"]),
            ocr_mode=cfg["ocr_mode"],
            target_style=cfg["target_style"],
            auto_resume=bool(cfg.get("auto_resume", True)),
            voice_mode=cfg.get("voice_mode", "multi"),
            voice_preset=cfg.get("voice_preset", ""),
        )
        job_queue.put_nowait((run_pipeline_task, (job_id, fn, cfg["target_lang"])))
        result["imported"].append(fn)
        log.info("watch_imported", file=fn, job_id=job_id, auto_resume=bool(cfg.get("auto_resume", True)))
    return result

async def watch_loop():
    while True:
        await asyncio.sleep(WATCH_INTERVAL_SECONDS)
        try:
            await scan_watch_folder_once()
        except Exception:
            log.exception("watch_loop_iteration_failed")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup: recover stale jobs from previous crash
    recovered = fail_stale_jobs(timeout_hours=2)
    if recovered:
        log.info("startup_recovered_stale_jobs", count=recovered)

    worker_task = asyncio.create_task(pipeline_worker())
    clean_task = asyncio.create_task(cleanup_loop())
    watch_task = asyncio.create_task(watch_loop())

    yield

    worker_task.cancel()
    clean_task.cancel()
    watch_task.cancel()

app = FastAPI(title="Video Dubbing API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # No cookie/session auth is used, so credentials must stay off: the wildcard-origin +
    # allow_credentials=True combo is unsafe (and browsers ignore it anyway).
    allow_credentials=False,
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


def _settings_for_job(job_info: dict):
    """Per-job settings override built from the job's stored flags (shared by phase-1/phase-2)."""
    return settings.model_copy(update={
        "enable_lipsync": bool(job_info.get("enable_lipsync", 0)),
        "enable_ocr": bool(job_info.get("enable_ocr", 1)),
        "ocr_mode": job_info.get("ocr_mode", "blur"),
        "voice_mode": job_info.get("voice_mode", "multi"),
        "voice_preset": job_info.get("voice_preset", ""),
    })

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
    def _scan_input():
        # Keep all filesystem I/O (listdir + per-file exists) off the event loop thread.
        vids = [f for f in os.listdir(input_dir) if os.path.splitext(f)[1].lower() in ALLOWED_EXTENSIONS]
        exists = {
            v: os.path.exists(os.path.join(output_dir, f"{os.path.splitext(v)[0]}_dubbed.mp4"))
            for v in vids
        }
        return vids, exists
    videos, output_exists = await asyncio.to_thread(_scan_input)
    jobs_map = get_jobs_by_filenames(videos)  # single query
    result = []
    for v in videos:
        job_info = jobs_map.get(v)
        status = "PENDING"
        if job_info:
            status = job_info["status"]
        elif output_exists.get(v):
            status = "COMPLETED"
        result.append({
            "filename": v,
            "status": status,
            "has_output": output_exists.get(v, False),
            "job_id": job_info["job_id"] if job_info else None
        })
    return {"videos": result}

def _cleanup_temp(base_name: str, data_dir: str):
    """Delete a finished/failed job's temp dir to bound disk use (the per-stage resume markers
    only matter while a job is mid-flight; the hourly cleanup_loop is the backstop)."""
    temp_root = os.path.abspath(os.path.join(data_dir, "temp"))
    temp_dir = os.path.abspath(os.path.join(temp_root, base_name))
    # Defense in depth: base_name must resolve to a single component directly under temp/.
    # This blocks path traversal (a base_name containing '..' or, on Windows, backslash
    # separators that os.path.join honours) from letting rmtree escape data/temp, and also
    # guards the empty-base_name case that would otherwise resolve to temp_root itself.
    if os.path.dirname(temp_dir) != temp_root:
        log.warning("cleanup_temp_skipped_unsafe", base_name=base_name, resolved=temp_dir)
        return
    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
        log.info("cleanup_temp", dir=temp_dir)

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
    if is_cancel_requested(job_id):          # cancelled while still queued
        clear_cancel(job_id)
        update_job_status(job_id, "CANCELLED")
        log.info("job_cancelled_before_start", job_id=job_id)
        return
    update_job_status(job_id, "PROCESSING")
    base_name = os.path.splitext(filename)[0]

    # Read per-job flags saved at queue time
    job_info = get_job(job_id) or {}
    phase1_settings = _settings_for_job(job_info)

    job = PipelineJob(
        job_id=job_id,
        filename=filename,
        base_name=base_name,
        target_language=target_lang,
        target_style=job_info.get("target_style", "Tiêu chuẩn"),
        vram_profile=settings.vram_profile,
        created_at=datetime.utcnow()
    )

    try:
        results, segments = await run_pipeline_phase1(job, phase1_settings)
        
        critical_stages = {"audio_separate", "transcribe", "translate"}
        success = all(
            results[s].success for s in critical_stages if s in results
        )
        phase1_summary = {"phase1": {k: v.summary() for k, v in results.items()}}
        if success:
            save_segments(job_id, segments)
            if job_info.get("auto_resume"):
                # Auto-process: skip manual review and go straight to phase-2. Set
                # PROCESSING_PHASE2 (not AWAITING_REVIEW) so the manual /resume guard can't
                # also enqueue a duplicate phase-2 task during the queue window.
                update_job_status(job_id, "PROCESSING_PHASE2", phase1_summary)
                log.info("auto_resume_enqueue_phase2", job_id=job_id)
                job_queue.put_nowait((run_pipeline_resume_task, (job_id,)))
            else:
                update_job_status(job_id, "AWAITING_REVIEW", phase1_summary)
        else:
            update_job_status(job_id, "FAILED", phase1_summary)
            _cleanup_temp(base_name, settings.data_dir)

    except (JobCancelled, asyncio.CancelledError):
        clear_cancel(job_id)
        update_job_status(job_id, "CANCELLED")
        _cleanup_temp(base_name, settings.data_dir)
        log.info("job_cancelled", job_id=job_id)
    except Exception as e:
        log.error("pipeline_error", error=str(e))
        update_job_status(job_id, "FAILED", error=str(e))
        _cleanup_temp(base_name, settings.data_dir)


def _safe_video_name(filename: str) -> str:
    """Validate a client-supplied video filename (URL path segment) and return a safe basename.

    A URL segment may contain '..' or, on Windows, backslash separators that os.path.join would
    honour, so any endpoint that turns {filename} into a filesystem path must never trust it raw.
    Reject anything that is not a bare filename with an allowed extension."""
    safe = os.path.basename(filename)
    if not safe or safe != filename or safe in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    ext = os.path.splitext(safe)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type '{ext}'.")
    return safe


@app.post("/api/dub/{filename}")
async def start_dubbing(
    filename: str,
    target_lang: str = "Tiếng Việt",
    target_style: str = "Tiêu chuẩn",
    enable_lipsync: bool = False,
    enable_ocr: bool = False,
    ocr_mode: str = "blur",
    voice_mode: str = "multi",
    voice_preset: str = "",
):
    filename = _safe_video_name(filename)
    if not os.path.isfile(os.path.join(input_dir, filename)):
        raise HTTPException(status_code=404, detail="Video not found.")
    job_id = str(uuid.uuid4())[:8]
    save_job(
        job_id, filename, target_lang, settings.vram_profile,
        enable_lipsync=enable_lipsync,
        enable_ocr=enable_ocr,
        ocr_mode=ocr_mode,
        target_style=target_style,
        voice_mode=voice_mode,
        voice_preset=voice_preset,
    )
    job_queue.put_nowait((run_pipeline_task, (job_id, filename, target_lang)))
    return {"job_id": job_id, "message": "Dubbing queued"}


class WatchConfig(BaseModel):
    enabled: bool | None = None
    folder: str | None = None
    target_lang: str | None = None
    target_style: str | None = None
    enable_lipsync: bool | None = None
    enable_ocr: bool | None = None
    ocr_mode: str | None = None
    auto_resume: bool | None = None
    voice_mode: str | None = None
    voice_preset: str | None = None


@app.get("/api/watch/config")
async def api_get_watch_config():
    cfg = get_watch_config()
    folder = (cfg.get("folder") or "").strip()
    return {**cfg, "folder_exists": bool(folder) and os.path.isdir(folder)}


@app.post("/api/watch/config")
async def api_set_watch_config(cfg: WatchConfig):
    provided = {k: v for k, v in cfg.model_dump().items() if v is not None}
    saved = set_watch_config(provided)
    folder = (saved.get("folder") or "").strip()
    folder_exists = bool(folder) and os.path.isdir(folder)
    # Scan immediately so a freshly-enabled folder starts processing without waiting.
    scan = await scan_watch_folder_once() if saved.get("enabled") else {"imported": [], "skipped": 0}
    return {"config": saved, "folder_exists": folder_exists, "scan": scan}


class AppConfig(BaseModel):
    # Extra folder the finished video is also saved to ("" = data/output only).
    output_folder: str | None = None


@app.get("/api/app-config")
async def api_get_app_config():
    cfg = get_app_config()
    folder = (cfg.get("output_folder") or "").strip()
    return {**cfg, "output_folder_exists": bool(folder) and os.path.isdir(folder)}


def _validate_output_folder(folder: str) -> str:
    """Confine the user-chosen output folder: absolute path, not a system / auto-run location.
    Defense-in-depth (the API also binds loopback now), so a stray/hostile value can't make the
    pipeline write finished dubs into Windows\\, Program Files, or the Startup auto-run folder."""
    folder = (folder or "").strip()
    if not folder:
        return ""
    p = os.path.abspath(folder)
    low = p.lower().rstrip("\\/")
    blocked = []
    for env in ("WINDIR", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        v = os.environ.get(env)
        if v:
            blocked.append(os.path.abspath(v).lower())
    appdata = os.environ.get("APPDATA")
    if appdata:
        blocked.append(os.path.join(os.path.abspath(appdata), "Microsoft", "Windows",
                                    "Start Menu", "Programs", "Startup").lower())
    for b in blocked:
        if low == b or low.startswith(b + os.sep):
            raise HTTPException(status_code=400, detail="Thư mục lưu không hợp lệ (thư mục hệ thống/khởi động).")
    return p


@app.post("/api/app-config")
async def api_set_app_config(cfg: AppConfig):
    provided = {k: v for k, v in cfg.model_dump().items() if v is not None}
    if "output_folder" in provided:
        provided["output_folder"] = _validate_output_folder(provided["output_folder"])
    saved = set_app_config(provided)
    folder = (saved.get("output_folder") or "").strip()
    return {"config": saved, "output_folder_exists": bool(folder) and os.path.isdir(folder)}


@app.post("/api/watch/scan")
async def api_watch_scan():
    return await scan_watch_folder_once()


@app.get("/api/voices")
async def api_list_voices():
    """Preset narrator voices (by country) for single-voice mode."""
    from orchestrator.voice_library import list_voices
    return {"voices": list_voices()}

@app.get("/api/status/{filename}")
async def get_status(filename: str):
    filename = _safe_video_name(filename)  # block path-traversal existence probing
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
    # Scope the write to this job so a stale/mismatched segment id can't overwrite another
    # job's translation (segments.id is a global autoincrement key).
    updated = update_segment_translation(data.id, data.translated_text, job_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Segment not found for this job.")
    return {"message": "Updated"}

async def run_pipeline_resume_task(job_id: str):
    if is_cancel_requested(job_id):          # cancelled while phase-2 was queued
        clear_cancel(job_id)
        update_job_status(job_id, "CANCELLED")
        log.info("job_cancelled_before_phase2", job_id=job_id)
        return
    update_job_status(job_id, "PROCESSING_PHASE2")
    job_info = get_job(job_id)
    if not job_info:
        return
        
    job = PipelineJob(
        job_id=job_id,
        filename=job_info["filename"],
        base_name=os.path.splitext(job_info["filename"])[0],
        target_language=job_info["target_lang"],
        target_style=job_info.get("target_style", "Tiêu chuẩn"),
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
        # Override per-job flags stored at queue time
        job_settings = _settings_for_job(job_info)
        results = await run_pipeline_phase2(job, segments, job_settings)
        
        success = True
        for stage, r in results.items():
            if not r.success and stage != "lip_sync":
                success = False
                
        # Nối kết quả phase 1 và phase 2
        final_res = job_info.get("results", {})
        final_res["phase2"] = {k: v.summary() for k, v in results.items()}
        
        update_job_status(job_id, "COMPLETED" if success else "FAILED", final_res)
        _cleanup_temp(job.base_name, settings.data_dir)
    except (JobCancelled, asyncio.CancelledError):
        clear_cancel(job_id)
        update_job_status(job_id, "CANCELLED")
        _cleanup_temp(job.base_name, settings.data_dir)
        log.info("job_cancelled", job_id=job_id)
    except Exception as e:
        log.error("pipeline_resume_error", error=str(e))
        update_job_status(job_id, "FAILED", error=str(e))
        _cleanup_temp(job.base_name, settings.data_dir)

@app.post("/api/jobs/{job_id}/resume")
async def resume_dubbing(job_id: str):
    job_info = get_job(job_id)
    if not job_info or job_info["status"] != "AWAITING_REVIEW":
        raise HTTPException(status_code=400, detail="Job not ready for resume")

    # Flip status immediately so a duplicate click (or an auto-resume racing this) cannot
    # enqueue phase-2 twice — a second call now fails the guard above.
    update_job_status(job_id, "PROCESSING_PHASE2")
    job_queue.put_nowait((run_pipeline_resume_task, (job_id,)))
    return {"message": "Resume queued"}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a queued or in-progress job. The pipeline stops at the next stage
    boundary (and a mid-await stage is interrupted immediately), ending as CANCELLED."""
    job_info = get_job(job_id)
    if not job_info:
        raise HTTPException(status_code=404, detail="Job not found")
    status = job_info.get("status")
    if status in ("COMPLETED", "FAILED", "CANCELLED"):
        return {"job_id": job_id, "status": status, "cancelled": False}
    request_cancel(job_id)
    t = _running_tasks.get(job_id)
    if t and not t.done():
        # A stage is actually running: interrupt its mid-await and let the task's own
        # JobCancelled/CancelledError handler finalize the row to CANCELLED.
        t.cancel()
        update_job_status(job_id, "CANCELLING")
        log.info("cancel_requested", job_id=job_id, prev_status=status)
        return {"job_id": job_id, "status": "CANCELLING", "cancelled": True}
    # No running task (e.g. AWAITING_REVIEW waiting for the user, or queued-but-not-started).
    # Nothing will ever consume a CANCELLING here, so finalize to CANCELLED right now — otherwise
    # the job sticks in CANCELLING forever and the UI polls it indefinitely. The cancel flag stays
    # set so that if a queued task does later run, its start-check also short-circuits to CANCELLED.
    update_job_status(job_id, "CANCELLED")
    log.info("cancel_finalized_no_task", job_id=job_id, prev_status=status)
    return {"job_id": job_id, "status": "CANCELLED", "cancelled": True}
