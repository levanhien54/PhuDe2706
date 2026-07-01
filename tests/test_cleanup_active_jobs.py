"""Regression test for the temp-cleanup active-job matching (audit MEDIUM #5).

cleanup_loop must not wipe the temp dir of a job that is still active. The old code
reconstructed filename+lowercase-ext and queried SQLite (case-sensitive), so a job stored
with an uppercase extension (e.g. 'MOVIE.MP4') was missed and its temp dir deleted. The fix
matches active jobs by base_name via get_jobs_by_status."""
import os

import pytest

from orchestrator import database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "jobs.db")
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()
    return db_file


def test_active_job_with_uppercase_ext_is_matched_by_basename(temp_db):
    database.save_job("j1", "MOVIE.MP4", "vi", "16gb", status="AWAITING_REVIEW")
    database.save_job("j2", "done.mp4", "vi", "16gb", status="COMPLETED")

    active_statuses = {"PROCESSING", "AWAITING_REVIEW", "PROCESSING_PHASE2"}
    jobs = database.get_jobs_by_status(active_statuses)
    assert {j["filename"] for j in jobs} == {"MOVIE.MP4"}

    # This is exactly how cleanup_loop decides whether to keep temp/<item>:
    active_base_names = {os.path.splitext(j["filename"])[0] for j in jobs}
    assert "MOVIE" in active_base_names  # temp/MOVIE is preserved (was wrongly wiped before)


def test_get_jobs_by_status_empty(temp_db):
    assert database.get_jobs_by_status(set()) == []
    assert database.get_jobs_by_status({"PROCESSING"}) == []
