import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Any

from orchestrator.config import get_settings

settings = get_settings()
DB_PATH = os.path.join(settings.data_dir, "jobs.db")

def init_db():
    os.makedirs(settings.data_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        status TEXT NOT NULL,
        target_lang TEXT NOT NULL,
        vram_profile TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        results JSON,
        error TEXT
    )
    ''')
    
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
    
    conn.commit()
    conn.close()

def save_job(job_id: str, filename: str, target_lang: str, vram_profile: str, status: str = "QUEUED"):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
    INSERT OR REPLACE INTO jobs (job_id, filename, target_lang, vram_profile, status, updated_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (job_id, filename, target_lang, vram_profile, status, datetime.utcnow()))
    conn.commit()
    conn.close()

def update_job_status(job_id: str, status: str, results: Dict = None, error: str = None):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    if results is not None:
        cursor.execute('UPDATE jobs SET status=?, results=?, updated_at=? WHERE job_id=?',
                       (status, json.dumps(results), datetime.utcnow(), job_id))
    elif error is not None:
        cursor.execute('UPDATE jobs SET status=?, error=?, updated_at=? WHERE job_id=?',
                       (status, error, datetime.utcnow(), job_id))
    else:
        cursor.execute('UPDATE jobs SET status=?, updated_at=? WHERE job_id=?',
                       (status, datetime.utcnow(), job_id))
    conn.commit()
    conn.close()

def get_job(job_id: str) -> Dict[str, Any]:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        res = dict(row)
        res['results'] = json.loads(res['results']) if res['results'] else {}
        return res
    return None

def get_job_by_filename(filename: str) -> Dict[str, Any]:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # Lấy job mới nhất cho filename
    cursor.execute('SELECT * FROM jobs WHERE filename=? ORDER BY created_at DESC LIMIT 1', (filename,))
    row = cursor.fetchone()
    conn.close()
    if row:
        res = dict(row)
        res['results'] = json.loads(res['results']) if res['results'] else {}
        return res
    return None

def save_segments(job_id: str, segments: List[Any]):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM segments WHERE job_id=?', (job_id,))
    
    for seg in segments:
        cursor.execute('''
        INSERT INTO segments (job_id, start_time, end_time, original_text, translated_text, speaker)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (job_id, seg.start, seg.end, seg.text, seg.translated, seg.speaker))
        
    conn.commit()
    conn.close()

def get_segments(job_id: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM segments WHERE job_id=? ORDER BY start_time ASC', (job_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_segment_translation(segment_id: int, translated_text: str):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('UPDATE segments SET translated_text=? WHERE id=?', (translated_text, segment_id))
    conn.commit()
    conn.close()

# Initialize DB on import
init_db()
