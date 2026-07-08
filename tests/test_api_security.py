"""Regression tests for the path-traversal hardening on the dubbing API (audit HIGH #1).

Covers _safe_video_name (endpoint input validation) and _cleanup_temp (defense-in-depth
guard so a bad base_name can never make shutil.rmtree escape data/temp)."""
import asyncio
import os
import sys

import pytest
from fastapi import HTTPException

from orchestrator import api


# ---- _safe_video_name -------------------------------------------------------

def test_safe_video_name_accepts_plain_allowed():
    assert api._safe_video_name("movie.mp4") == "movie.mp4"
    assert api._safe_video_name("clip.v2.mkv") == "clip.v2.mkv"


@pytest.mark.parametrize("bad", ["../x.mp4", "a/b.mp4", "", ".", ".."])
def test_safe_video_name_rejects_traversal_portable(bad):
    with pytest.raises(HTTPException):
        api._safe_video_name(bad)


@pytest.mark.skipif(sys.platform != "win32", reason="backslash is a path separator only on Windows")
@pytest.mark.parametrize("bad", ["..\\..\\x.mp4", "sub\\b.mp4"])
def test_safe_video_name_rejects_backslash_traversal(bad):
    with pytest.raises(HTTPException):
        api._safe_video_name(bad)


def test_safe_video_name_rejects_bad_extension():
    with pytest.raises(HTTPException):
        api._safe_video_name("movie.txt")


# ---- _cleanup_temp ----------------------------------------------------------

def test_cleanup_temp_removes_own_dir(tmp_path):
    data_dir = str(tmp_path)
    temp_dir = os.path.join(data_dir, "temp", "job1")
    os.makedirs(temp_dir)
    api._cleanup_temp("job1", data_dir)
    assert not os.path.exists(temp_dir)


def test_cleanup_temp_refuses_traversal(tmp_path):
    """A base_name that resolves outside temp/ must be skipped, not deleted."""
    data_dir = str(tmp_path)
    os.makedirs(os.path.join(data_dir, "temp"))
    victim = os.path.join(data_dir, "victim")
    os.makedirs(victim)
    api._cleanup_temp(os.path.join("..", "victim"), data_dir)
    assert os.path.isdir(victim)  # guard prevented escape


def test_cleanup_temp_refuses_empty_base_name(tmp_path):
    """Empty base_name resolves to temp_root itself; must not wipe the whole temp dir."""
    data_dir = str(tmp_path)
    temp_root = os.path.join(data_dir, "temp")
    os.makedirs(os.path.join(temp_root, "keep"))
    api._cleanup_temp("", data_dir)
    assert os.path.isdir(temp_root)
    assert os.path.isdir(os.path.join(temp_root, "keep"))


# ---- watch-folder scan concurrency (finding 0.6) ----------------------------

@pytest.mark.asyncio
async def test_concurrent_watch_scans_import_once(monkeypatch, tmp_path):
    """Two scans of the same new file (racing watch_loop + an /api/watch endpoint) must import
    it exactly once. Without the _scan_lock both pass the existence check and copy+queue twice."""
    folder = tmp_path / "watch"
    input_dir = tmp_path / "input"
    folder.mkdir()
    input_dir.mkdir()
    (folder / "new.mp4").write_bytes(b"video-bytes")

    cfg = {
        "enabled": True, "folder": str(folder), "target_lang": "vi",
        "target_style": "Tiêu chuẩn", "enable_lipsync": False, "enable_ocr": False,
        "ocr_mode": "blur", "auto_resume": True, "voice_mode": "multi", "voice_preset": "",
    }
    saved = {}
    copy_calls = []

    def fake_get_job_by_filename(fn):
        return saved.get(fn)

    def fake_save_job(job_id, fn, *a, **k):
        saved[fn] = {"job_id": job_id, "filename": fn, "status": "QUEUED"}

    def fake_copy2(src, dst):
        copy_calls.append(dst)
        with open(dst, "wb") as f:
            f.write(b"x")

    monkeypatch.setattr(api, "job_queue", asyncio.Queue())
    monkeypatch.setattr(api, "input_dir", str(input_dir))
    monkeypatch.setattr(api, "get_watch_config", lambda: dict(cfg))
    monkeypatch.setattr(api, "get_job_by_filename", fake_get_job_by_filename)
    monkeypatch.setattr(api, "save_job", fake_save_job)
    monkeypatch.setattr(api, "_file_is_stable", lambda *a, **k: True)
    monkeypatch.setattr("shutil.copy2", fake_copy2)

    r1, r2 = await asyncio.gather(
        api.scan_watch_folder_once(), api.scan_watch_folder_once()
    )

    total_imported = len(r1["imported"]) + len(r2["imported"])
    assert total_imported == 1          # only one scan imported the file
    assert len(copy_calls) == 1         # the other scan never even reached the copy step
    assert api.job_queue.qsize() == 1   # exactly one job queued


# ---- upload partial-file cleanup (finding A4) -------------------------------

class _FakeUpload:
    """Minimal stand-in for fastapi.UploadFile driving upload_video directly."""
    def __init__(self, filename, chunks):
        self.filename = filename
        self._chunks = list(chunks)

    async def read(self, n):
        if not self._chunks:
            return b""
        c = self._chunks.pop(0)
        if isinstance(c, Exception):
            raise c
        return c


@pytest.mark.asyncio
async def test_upload_removes_partial_on_non_http_error(monkeypatch, tmp_path):
    """A write error that is NOT an HTTPException must still delete the partial file (finding A4);
    previously only HTTPException triggered cleanup, leaving a truncated file behind."""
    monkeypatch.setattr(api, "input_dir", str(tmp_path))
    valid_header = b"\x00\x00\x00\x18ftypmp42"  # passes _is_valid_video_header
    up = _FakeUpload("clip.mp4", [valid_header, RuntimeError("disk full")])

    with pytest.raises(RuntimeError):
        await api.upload_video(up)

    assert not os.path.exists(os.path.join(str(tmp_path), "clip.mp4"))


# ---- job/worker lifecycle robustness (findings A5, A6, A8) ------------------

@pytest.mark.asyncio
async def test_run_pipeline_task_marks_failed_if_initial_status_write_fails(monkeypatch):
    """If the initial PROCESSING write fails, the job must end FAILED, not strand in QUEUED
    (finding A5: the write was outside the try and fail_stale_jobs doesn't recover QUEUED)."""
    calls = []

    def fake_update(job_id, status, *a, **k):
        calls.append(status)
        if status == "PROCESSING":
            raise RuntimeError("db down")

    monkeypatch.setattr(api, "update_job_status", fake_update)
    monkeypatch.setattr(api, "is_cancel_requested", lambda jid: False)
    monkeypatch.setattr(api, "get_job", lambda jid: {})
    monkeypatch.setattr(api, "_cleanup_temp", lambda *a, **k: None)

    await api.run_pipeline_task("j1", "movie.mp4", "vi")

    assert calls[0] == "PROCESSING"
    assert "FAILED" in calls          # the failure was caught and finalized, not propagated


@pytest.mark.asyncio
async def test_worker_cancels_inflight_job_on_shutdown(monkeypatch):
    """On shutdown the worker must cancel its in-flight job task and then exit, rather than
    swallowing the CancelledError, orphaning the job, and looping forever (finding A6)."""
    monkeypatch.setattr(api, "job_queue", asyncio.Queue())
    started = asyncio.Event()
    state = {"cancelled": False}

    async def fake_task(job_id):
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    api.job_queue.put_nowait((fake_task, ("jX",)))
    worker = asyncio.create_task(api.pipeline_worker())
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        assert "jX" in api._running_tasks

        worker.cancel()
        for _ in range(100):
            if worker.done():
                break
            await asyncio.sleep(0)

        assert worker.done(), "worker did not exit on shutdown cancellation"
        assert worker.cancelled()
        assert state["cancelled"] is True     # in-flight job was cancelled, not orphaned
        assert "jX" not in api._running_tasks
    finally:
        if not worker.done():
            worker.cancel()
        for t in list(api._running_tasks.values()):
            t.cancel()
        api._running_tasks.clear()


@pytest.mark.asyncio
async def test_cancel_awaiting_review_clears_cancel_flag(monkeypatch):
    """Cancelling a job that is AWAITING_REVIEW (no task will ever run) must discard the cancel
    flag so _cancel_requested stays bounded (finding A8)."""
    from orchestrator import pipeline
    pipeline._cancel_requested.discard("jA")
    api._running_tasks.pop("jA", None)
    monkeypatch.setattr(api, "get_job", lambda jid: {"status": "AWAITING_REVIEW"})
    monkeypatch.setattr(api, "update_job_status", lambda *a, **k: None)

    res = await api.cancel_job("jA")

    assert res["status"] == "CANCELLED"
    assert not pipeline.is_cancel_requested("jA")   # flag was discarded (previously leaked)


@pytest.mark.asyncio
async def test_cancel_queued_keeps_cancel_flag(monkeypatch):
    """A still-QUEUED job keeps its cancel flag so the pending task short-circuits to CANCELLED
    when it later runs (companion guard for finding A8)."""
    from orchestrator import pipeline
    pipeline._cancel_requested.discard("jQ")
    api._running_tasks.pop("jQ", None)
    monkeypatch.setattr(api, "get_job", lambda jid: {"status": "QUEUED"})
    monkeypatch.setattr(api, "update_job_status", lambda *a, **k: None)

    try:
        await api.cancel_job("jQ")
        assert pipeline.is_cancel_requested("jQ")
    finally:
        pipeline.clear_cancel("jQ")


# ---- logger path derivation (finding A7) ------------------------------------

def test_logger_uses_settings_data_dir():
    """The log file must live under settings.data_dir (absolute), not a cwd-relative 'data/'."""
    from orchestrator import logger as lg
    from orchestrator.config import get_settings
    expected = os.path.join(get_settings().data_dir, "orchestrator.log")
    assert lg._log_file_path() == expected
    assert os.path.isabs(lg._log_file_path())
