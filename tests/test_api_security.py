"""Regression tests for the path-traversal hardening on the dubbing API (audit HIGH #1).

Covers _safe_video_name (endpoint input validation) and _cleanup_temp (defense-in-depth
guard so a bad base_name can never make shutil.rmtree escape data/temp)."""
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
