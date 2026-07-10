"""Encoder-arg selection for the OCR-blur re-encode / frame writer: constant-quality NVENC on the
GPU when a real session opens, else libx264 at the same crf. (The GPU path can't be exercised on a
non-NVENC CI box, so we assert the arg construction directly.)"""
from unittest.mock import patch

from orchestrator import video_process


def test_nvenc_args_use_constant_quality_when_available():
    with patch("orchestrator.video_process._check_nvenc_cached", return_value=True):
        args = video_process._nvenc_or_x264_args(23)
    assert "h264_nvenc" in args
    assert args[args.index("-cq") + 1] == "23"          # x264-crf-equivalent quality
    assert args[args.index("-b:v") + 1] == "0"          # constant-quality, NOT a fixed bitrate
    assert "5M" not in args                              # regression: old fixed 5M bitrate is gone


def test_nvenc_args_fall_back_to_libx264_when_unavailable():
    with patch("orchestrator.video_process._check_nvenc_cached", return_value=False):
        args = video_process._nvenc_or_x264_args(23)
    assert "libx264" in args
    assert args[args.index("-crf") + 1] == "23"
    assert "h264_nvenc" not in args


def test_nvenc_args_respect_cq_argument():
    with patch("orchestrator.video_process._check_nvenc_cached", return_value=True):
        assert video_process._nvenc_or_x264_args(19)[video_process._nvenc_or_x264_args(19).index("-cq") + 1] == "19"
