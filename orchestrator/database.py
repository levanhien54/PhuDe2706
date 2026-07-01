import sqlite3
import os
import json
from contextlib import contextmanager
from datetime import datetime
from typing import List, Dict, Any

from orchestrator.config import get_settings

settings = get_settings()
DB_PATH = os.path.join(settings.data_dir, "jobs.db")


@contextmanager
def _connect(row_factory: bool = False):
    """SQLite connection with a busy_timeout (concurrent writers wait instead of raising
    'database is locked'), commit-on-success, and guaranteed close."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=5000")
    if row_factory:
        conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_job(row) -> Dict[str, Any]:
    d = dict(row)
    d['results'] = json.loads(d['results']) if d.get('results') else {}
    return d


def init_db():
    os.makedirs(settings.data_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        status TEXT NOT NULL,
        target_lang TEXT NOT NULL,
        target_style TEXT NOT NULL DEFAULT 'Tiêu chuẩn',
        vram_profile TEXT NOT NULL,
        enable_lipsync INTEGER NOT NULL DEFAULT 0,
        enable_ocr INTEGER NOT NULL DEFAULT 1,
        ocr_mode TEXT NOT NULL DEFAULT 'blur',
        voice_mode TEXT NOT NULL DEFAULT 'multi',
        voice_preset TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        results JSON,
        error TEXT
    )
    ''')
    # Migrations for databases that pre-date these columns
    for migration in [
        "ALTER TABLE jobs ADD COLUMN target_style TEXT NOT NULL DEFAULT 'Tiêu chuẩn'",
        "ALTER TABLE jobs ADD COLUMN enable_lipsync INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN enable_ocr INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE jobs ADD COLUMN ocr_mode TEXT NOT NULL DEFAULT 'blur'",
        "ALTER TABLE jobs ADD COLUMN auto_resume INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN voice_mode TEXT NOT NULL DEFAULT 'multi'",
        "ALTER TABLE jobs ADD COLUMN voice_preset TEXT NOT NULL DEFAULT ''",
    ]:
        try:
            cursor.execute(migration)
            conn.commit()
        except Exception:
            pass  # column already exists

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        start_time REAL NOT NULL,
        end_time REAL NOT NULL,
        original_text TEXT NOT NULL,
        translated_text TEXT,
        speaker TEXT,
        FOREIGN KEY (job_id) REFERENCES jobs (job_id)
    )
    ''')

    # Key/value store for app-level settings (e.g. the auto-process watch-folder config)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    ''')

    conn.commit()
    conn.close()


def save_job(job_id: str, filename: str, target_lang: str, vram_profile: str,
             status: str = "QUEUED", enable_lipsync: bool = False,
             enable_ocr: bool = False, ocr_mode: str = 'blur', target_style: str = 'Tiêu chuẩn',
             auto_resume: bool = False, voice_mode: str = 'multi', voice_preset: str = ''):
    with _connect() as conn:
        conn.execute('''
        INSERT OR REPLACE INTO jobs
            (job_id, filename, target_lang, target_style, vram_profile, enable_lipsync, enable_ocr, ocr_mode, status, auto_resume, voice_mode, voice_preset, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (job_id, filename, target_lang, target_style, vram_profile,
              int(enable_lipsync), int(enable_ocr), ocr_mode,
              status, int(auto_resume), voice_mode, voice_preset, datetime.utcnow()))


def update_job_status(job_id: str, status: str, results: Dict = None, error: str = None):
    with _connect() as conn:
        if results is not None:
            conn.execute('UPDATE jobs SET status=?, results=?, updated_at=? WHERE job_id=?',
                         (status, json.dumps(results), datetime.utcnow(), job_id))
        elif error is not None:
            conn.execute('UPDATE jobs SET status=?, error=?, updated_at=? WHERE job_id=?',
                         (status, error, datetime.utcnow(), job_id))
        else:
            conn.execute('UPDATE jobs SET status=?, updated_at=? WHERE job_id=?',
                         (status, datetime.utcnow(), job_id))


def get_job(job_id: str) -> Dict[str, Any]:
    with _connect(row_factory=True) as conn:
        row = conn.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def get_job_by_filename(filename: str) -> Dict[str, Any]:
    with _connect(row_factory=True) as conn:
        # Lấy job mới nhất cho filename
        row = conn.execute('SELECT * FROM jobs WHERE filename=? ORDER BY created_at DESC LIMIT 1',
                           (filename,)).fetchone()
    return _row_to_job(row) if row else None


def get_jobs_by_filenames(filenames: list) -> dict:
    """Returns {filename: job_dict} for the latest job per filename. SQLite-version-agnostic."""
    if not filenames:
        return {}
    with _connect(row_factory=True) as conn:
        placeholders = ",".join("?" * len(filenames))
        rows = conn.execute(
            f"SELECT * FROM jobs WHERE filename IN ({placeholders}) ORDER BY created_at DESC",
            filenames
        ).fetchall()
    result = {}
    for row in rows:
        d = _row_to_job(row)
        if d['filename'] in result:
            continue  # already have the latest (DESC order)
        result[d['filename']] = d
    return result


def get_jobs_by_status(statuses) -> list:
    """Return job dicts whose status is in `statuses`. Used by the temp-cleanup backstop to
    match a temp dir against active jobs by base_name (robust to filename extension case)."""
    statuses = list(statuses)
    if not statuses:
        return []
    with _connect(row_factory=True) as conn:
        placeholders = ",".join("?" * len(statuses))
        rows = conn.execute(
            f"SELECT * FROM jobs WHERE status IN ({placeholders})", statuses
        ).fetchall()
    return [_row_to_job(row) for row in rows]


def fail_stale_jobs(timeout_hours: int = 2) -> int:
    """Startup recovery: time-out stuck PROCESSING jobs, and converge orphaned CANCELLING rows.

    A CANCELLING row at startup means the cancelling task died (crash/restart) before it could
    write CANCELLED — there is no in-memory task left to finalize it, so resolve it to the terminal
    CANCELLED state here, else it sticks forever (UI polls it; watch-folder skips the file)."""
    with _connect() as conn:
        cutoff = datetime.utcnow().isoformat()
        cur = conn.execute(
            """UPDATE jobs SET status='FAILED', error='Job timed out', updated_at=?
               WHERE status IN ('PROCESSING','PROCESSING_PHASE2')
               AND updated_at < datetime(?, '-' || ? || ' hours')""",
            (cutoff, cutoff, str(timeout_hours))
        )
        n = cur.rowcount
        cur2 = conn.execute(
            "UPDATE jobs SET status='CANCELLED', updated_at=? WHERE status='CANCELLING'",
            (cutoff,)
        )
        return n + cur2.rowcount


def save_segments(job_id: str, segments: List[Any]):
    with _connect() as conn:
        conn.execute('DELETE FROM segments WHERE job_id=?', (job_id,))
        conn.executemany(
            '''INSERT INTO segments (job_id, start_time, end_time, original_text, translated_text, speaker)
               VALUES (?, ?, ?, ?, ?, ?)''',
            [(job_id, seg.start, seg.end, seg.text, seg.translated, seg.speaker) for seg in segments]
        )


def get_segments(job_id: str) -> List[Dict[str, Any]]:
    with _connect(row_factory=True) as conn:
        rows = conn.execute('SELECT * FROM segments WHERE job_id=? ORDER BY start_time ASC',
                            (job_id,)).fetchall()
    return [dict(r) for r in rows]


def update_segment_translation(segment_id: int, translated_text: str):
    with _connect() as conn:
        conn.execute('UPDATE segments SET translated_text=? WHERE id=?', (translated_text, segment_id))


# --- Auto-process watch-folder config (persisted in app_settings) ---
_WATCH_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "folder": "",
    "target_lang": "Tiếng Việt",
    "target_style": "Tiêu chuẩn",
    "enable_lipsync": False,
    "enable_ocr": False,
    "ocr_mode": "blur",
    "voice_mode": "multi",
    "voice_preset": "",
    "auto_resume": True,   # run phase-2 automatically (no manual review)
}


def get_watch_config() -> Dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key='watch_config'").fetchone()
    cfg = dict(_WATCH_DEFAULTS)
    if row and row[0]:
        try:
            cfg.update(json.loads(row[0]))
        except Exception:
            pass
    return cfg


def set_watch_config(partial: Dict[str, Any]) -> Dict[str, Any]:
    """Merge the provided keys into the saved config and return the full result."""
    merged = get_watch_config()
    merged.update({k: v for k, v in partial.items() if k in _WATCH_DEFAULTS})
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('watch_config', ?)",
            (json.dumps(merged),),
        )
    return merged


# App-level config (general settings shown in the "Cau hinh he thong" modal).
_APP_DEFAULTS: Dict[str, Any] = {
    # Extra folder the finished video is ALSO saved to. "" = data/output only.
    # data/output stays the canonical copy the UI serves (preview/download/list).
    "output_folder": "",
}


def get_app_config() -> Dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key='app_config'").fetchone()
    cfg = dict(_APP_DEFAULTS)
    if row and row[0]:
        try:
            cfg.update(json.loads(row[0]))
        except Exception:
            pass
    return cfg


def set_app_config(partial: Dict[str, Any]) -> Dict[str, Any]:
    """Merge the provided keys into the saved app config and return the full result."""
    merged = get_app_config()
    merged.update({k: v for k, v in partial.items() if k in _APP_DEFAULTS})
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('app_config', ?)",
            (json.dumps(merged),),
        )
    return merged


# Initialize DB on import
init_db()
