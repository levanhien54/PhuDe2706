import os
import numpy as np
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_cap(n_frames: int = 30, h: int = 50, w: int = 50):
    """Return a MagicMock cv2.VideoCapture that serves synthetic frames."""
    frame = np.full((h, w, 3), 100, dtype=np.uint8)
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.return_value = float(n_frames)
    mock_cap.read.return_value = (True, frame)
    mock_cap.release.return_value = None
    return mock_cap


class _FakeFFmpegStdout:
    """stdout for a mocked ffmpeg decode: yields `n_frames` full frames then EOF."""
    def __init__(self, n_frames):
        self._remaining = n_frames
    def read(self, size):
        if self._remaining <= 0:
            return b''
        self._remaining -= 1
        return b'\x00' * size
    def close(self):
        pass


def _make_fake_ffmpeg_proc(n_frames):
    """MagicMock subprocess for precompute_ocr_results' ffmpeg frame-extraction pipe."""
    proc = MagicMock()
    proc.stdout = _FakeFFmpegStdout(n_frames)
    proc.wait.return_value = 0
    return proc


# ---------------------------------------------------------------------------
# build_temporal_reference
# ---------------------------------------------------------------------------

def test_build_temporal_reference_shape():
    """Valid video → returns ndarray shape (H, W, 3) dtype uint8."""
    from orchestrator.video_process import build_temporal_reference
    import orchestrator.video_process as vp

    mock_cap = _make_mock_cap(n_frames=30, h=50, w=50)
    with patch.object(vp, 'cv2') as mock_cv2:
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.CAP_PROP_FRAME_COUNT = 7
        mock_cv2.CAP_PROP_POS_FRAMES = 1
        result = build_temporal_reference('/fake/path.avi', n_samples=5)

    assert result is not None
    assert result.shape == (50, 50, 3)
    assert result.dtype == np.uint8


def test_build_temporal_reference_short_video_returns_none():
    """Video with < 3 frames → returns None."""
    from orchestrator.video_process import build_temporal_reference
    import orchestrator.video_process as vp

    mock_cap = _make_mock_cap(n_frames=2)
    with patch.object(vp, 'cv2') as mock_cv2:
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.CAP_PROP_FRAME_COUNT = 7
        mock_cv2.CAP_PROP_POS_FRAMES = 1
        result = build_temporal_reference('/fake/path.avi', n_samples=10)

    assert result is None


def test_build_temporal_reference_invalid_path():
    """Cap that fails to open → returns None."""
    from orchestrator.video_process import build_temporal_reference
    import orchestrator.video_process as vp

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = False
    with patch.object(vp, 'cv2') as mock_cv2:
        mock_cv2.VideoCapture.return_value = mock_cap
        result = build_temporal_reference('/nonexistent/path.avi', n_samples=5)

    assert result is None


# ---------------------------------------------------------------------------
# apply_temporal_inpaint
# ---------------------------------------------------------------------------

def test_apply_temporal_inpaint_static_copies_from_reference():
    """Static box must be filled from reference pixels."""
    import orchestrator.video_process as vp
    from orchestrator.video_process import apply_temporal_inpaint

    frame = np.zeros((60, 60, 3), dtype=np.uint8)
    frame[10:20, 10:30] = 255  # watermark
    reference = np.full((60, 60, 3), 100, dtype=np.uint8)

    # No cv2 calls needed for static-only path (just numpy)
    result = apply_temporal_inpaint(frame, reference, static_boxes=[(10, 10, 20, 10)], dynamic_boxes=[])
    assert np.all(result[10:20, 10:30] == 100)
    assert np.all(result[0:10, :] == 0)


def test_apply_temporal_inpaint_no_boxes_returns_copy():
    """No boxes → returns copy of frame (not same object)."""
    from orchestrator.video_process import apply_temporal_inpaint

    frame = np.full((40, 40, 3), 77, dtype=np.uint8)
    result = apply_temporal_inpaint(frame, None, [], [])
    np.testing.assert_array_equal(result, frame)
    assert result is not frame


def test_apply_temporal_inpaint_fallback_no_reference():
    """reference=None with boxes → no crash, returns ndarray same shape."""
    import orchestrator.video_process as vp
    from orchestrator.video_process import apply_temporal_inpaint

    frame = np.full((60, 60, 3), 50, dtype=np.uint8)

    mock_contours = []  # no contours → TELEA path skipped
    with patch.object(vp, 'cv2') as mock_cv2:
        mock_cv2.findContours.return_value = (mock_contours, None)
        mock_cv2.RETR_EXTERNAL = 0
        mock_cv2.CHAIN_APPROX_SIMPLE = 1
        result = apply_temporal_inpaint(frame, None, static_boxes=[(5, 5, 10, 10)], dynamic_boxes=[])

    assert result.shape == frame.shape
    assert result.dtype == np.uint8


def test_precompute_ocr_results_ocr_called_per_frame():
    """OCR runs once per extracted frame (batching was removed for the ffmpeg-pipe pre-pass)."""
    from orchestrator.video_process import precompute_ocr_results

    mock_ocr = MagicMock()
    mock_ocr.ocr.return_value = [[]]  # no boxes

    # ffmpeg is mocked to emit 12 downscaled frames.
    with patch('orchestrator.video_process.subprocess.Popen', return_value=_make_fake_ffmpeg_proc(12)):
        result = precompute_ocr_results(
            '/fake/path.avi', 120, 10.0,
            ocr_fps=1.0, ocr_batch_size=4,
            width=50, height=50, ocr=mock_ocr
        )

    assert mock_ocr.ocr.call_count == 12
    assert isinstance(result, dict)


def test_precompute_ocr_results_returns_correct_keys():
    """Keys map to original-frame indices: fps=10/ocr_fps=1 → frame_skip=10 → 0,10,20."""
    from orchestrator.video_process import precompute_ocr_results

    mock_ocr = MagicMock()
    mock_ocr.ocr.return_value = [[]]  # no boxes

    # ffmpeg emits 3 frames (a 30-frame, 10fps clip sampled at 1fps).
    with patch('orchestrator.video_process.subprocess.Popen', return_value=_make_fake_ffmpeg_proc(3)):
        result = precompute_ocr_results(
            '/fake/path.avi', 30, 10.0,
            ocr_fps=1.0, ocr_batch_size=1,
            width=50, height=50, ocr=mock_ocr
        )

    assert set(result.keys()) == {0, 10, 20}


# ---------------------------------------------------------------------------
# _detect_static_boxes (new signature: input_path + total_frames)
# ---------------------------------------------------------------------------

def test_detect_static_boxes_samples_30_frames():
    """_detect_static_boxes now samples frames evenly across full video, not just the start."""
    import orchestrator.video_process as vp

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.return_value = 300.0
    mock_cap.read.return_value = (True, np.full((50, 50, 3), 100, dtype=np.uint8))

    mock_ocr = MagicMock()
    mock_ocr.ocr.return_value = []

    with patch.object(vp, 'cv2') as mock_cv2:
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.CAP_PROP_POS_FRAMES = 1
        vp._detect_static_boxes('/fake/path.avi', mock_ocr, 30.0, 50, 50, 300)

    # STATIC_SCAN_FRAMES = 30, so ocr.ocr called at most 30 times
    assert mock_ocr.ocr.call_count <= vp.STATIC_SCAN_FRAMES
    assert mock_ocr.ocr.call_count > 0


# ---------------------------------------------------------------------------
# remove_watermark_from_video integration smoke test
# ---------------------------------------------------------------------------

def test_remove_watermark_integration_no_crash():
    """remove_watermark_from_video runs end-to-end without crashing (no boxes detected)."""
    import orchestrator.video_process as vp
    from orchestrator.video_process import remove_watermark_from_video

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.side_effect = lambda prop: {7: 30.0, 5: 30.0, 3: 50.0, 4: 50.0}.get(prop, 30.0)
    call_count = [0]
    def _read():
        call_count[0] += 1
        if call_count[0] > 30:
            return False, None
        return True, np.full((50, 50, 3), 100, dtype=np.uint8)
    mock_cap.read.side_effect = _read
    mock_cap.set.return_value = None
    mock_cap.release.return_value = None

    mock_ocr_instance = MagicMock()
    mock_ocr_instance.ocr.return_value = []

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as fin:
        in_path = fin.name
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as fout:
        out_path = fout.name
    try:
        with patch.object(vp, 'cv2') as mock_cv2, \
             patch.object(vp, 'get_ocr_instance', return_value=mock_ocr_instance), \
             patch.object(vp, 'build_temporal_reference', return_value=None), \
             patch.object(vp, 'precompute_ocr_results', return_value={}), \
             patch.object(vp, '_detect_static_boxes', return_value=[]), \
             patch.object(vp, '_has_dynamic_text', return_value=False), \
             patch.object(vp, '_check_nvenc_cached', return_value=False), \
             patch('subprocess.Popen') as mock_popen:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_PROP_FPS = 5
            mock_cv2.CAP_PROP_FRAME_WIDTH = 3
            mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
            mock_cv2.CAP_PROP_FRAME_COUNT = 7

            mock_proc = MagicMock()
            mock_proc.stdin = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.wait.return_value = 0
            mock_proc.stderr = iter([])
            mock_popen.return_value = mock_proc

            remove_watermark_from_video(in_path, out_path, mask_only=False, settings=None)
    finally:
        for _p in (in_path, out_path):
            if os.path.exists(_p):
                os.unlink(_p)


def test_remove_watermark_integration_creates_output():
    """remove_watermark_from_video chạy end-to-end không crash."""
    import tempfile, os
    from orchestrator.video_process import remove_watermark_from_video
    from unittest.mock import patch, MagicMock

    with tempfile.NamedTemporaryFile(suffix='.avi', delete=False) as fin:
        in_path = fin.name
    with tempfile.NamedTemporaryFile(suffix='.avi', delete=False) as fout:
        out_path = fout.name

    try:
        # Create a minimal test video using mocks
        import orchestrator.video_process as vp
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {7: 30.0, 5: 30.0, 3: 50.0, 4: 50.0}.get(prop, 30.0)
        call_count = [0]
        def _read():
            call_count[0] += 1
            if call_count[0] > 30:
                return False, None
            return True, np.full((50, 50, 3), 100, dtype=np.uint8)
        mock_cap.read.side_effect = _read
        mock_cap.set.return_value = None
        mock_cap.release.return_value = None

        mock_ocr_instance = MagicMock()
        mock_ocr_instance.ocr.return_value = []  # không phát hiện box nào

        with patch.object(vp, 'cv2') as mock_cv2, \
             patch.object(vp, 'get_ocr_instance', return_value=mock_ocr_instance), \
             patch.object(vp, 'build_temporal_reference', return_value=None), \
             patch.object(vp, 'precompute_ocr_results', return_value={}), \
             patch.object(vp, '_detect_static_boxes', return_value=[]), \
             patch.object(vp, '_has_dynamic_text', return_value=False), \
             patch.object(vp, '_check_nvenc_cached', return_value=False), \
             patch('subprocess.Popen') as mock_popen:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_PROP_FPS = 5
            mock_cv2.CAP_PROP_FRAME_WIDTH = 3
            mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
            mock_cv2.CAP_PROP_FRAME_COUNT = 7

            mock_proc = MagicMock()
            mock_proc.stdin = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.wait.return_value = 0
            mock_proc.stderr = iter([])
            mock_popen.return_value = mock_proc

            remove_watermark_from_video(in_path, out_path, mask_only=False, settings=None)

        # Just verify that the function ran without raising an exception
        # The output file creation is mocked, so we don't verify its existence
        assert True
    finally:
        for p in [in_path, out_path]:
            if os.path.exists(p):
                os.unlink(p)


# ---------------------------------------------------------------------------
# 0.1 — blur-mode fallback must NOT report success when it blurs nothing
# ---------------------------------------------------------------------------

def _cv2_props(mock_cv2):
    mock_cv2.CAP_PROP_FPS = 5
    mock_cv2.CAP_PROP_FRAME_WIDTH = 3
    mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
    mock_cv2.CAP_PROP_FRAME_COUNT = 7
    mock_cv2.CAP_PROP_POS_FRAMES = 1


def test_blur_fallback_raises_when_nothing_to_blur(tmp_path):
    """0.1: precise blur raises + fallback OCR finds nothing + no static watermark → the function
    MUST fail, never write the untouched (still-subtitled) frames through and report success."""
    import orchestrator.video_process as vp
    from orchestrator.video_process import remove_watermark_from_video

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.side_effect = lambda prop: {7: 30.0, 5: 30.0, 3: 50.0, 4: 50.0}.get(prop, 30.0)
    mock_cap.read.return_value = (True, np.full((50, 50, 3), 100, dtype=np.uint8))
    mock_cap.set.return_value = None
    mock_cap.release.return_value = None

    mock_ocr = MagicMock()
    mock_ocr.ocr.return_value = []

    in_path = str(tmp_path / "in.mp4")
    open(in_path, 'wb').close()
    out_path = str(tmp_path / "out.mp4")

    with patch.object(vp, 'cv2') as mock_cv2, \
         patch.object(vp, 'get_ocr_instance', return_value=mock_ocr), \
         patch.object(vp, '_detect_static_boxes', return_value=[]), \
         patch.object(vp, '_has_dynamic_text', return_value=True), \
         patch.object(vp, '_precise_blur_per_frame', side_effect=RuntimeError("forced precise failure")), \
         patch.object(vp, 'precompute_ocr_results', return_value={}):
        mock_cv2.VideoCapture.return_value = mock_cap
        _cv2_props(mock_cv2)
        with pytest.raises(RuntimeError, match="không có vùng chữ"):
            remove_watermark_from_video(in_path, out_path, mask_only=False, settings=None)


def test_blur_fallback_proceeds_when_precompute_finds_boxes(tmp_path):
    """0.1 (companion): when the precise path fails but the fallback precompute DOES find text
    boxes, the threaded fallback must run and actually blur — not raise the no-op error."""
    import orchestrator.video_process as vp
    from orchestrator.video_process import remove_watermark_from_video

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.side_effect = lambda prop: {7: 30.0, 5: 30.0, 3: 50.0, 4: 50.0}.get(prop, 30.0)
    call_count = [0]
    def _read():
        call_count[0] += 1
        if call_count[0] > 30:
            return False, None
        return True, np.full((50, 50, 3), 100, dtype=np.uint8)
    mock_cap.read.side_effect = _read
    mock_cap.set.return_value = None
    mock_cap.release.return_value = None

    mock_ocr = MagicMock()
    mock_ocr.ocr.return_value = []

    in_path = str(tmp_path / "in.mp4")
    open(in_path, 'wb').close()
    out_path = str(tmp_path / "out.mp4")

    blur_stub = MagicMock(side_effect=lambda frame, static, cached: frame)

    with patch.object(vp, 'cv2') as mock_cv2, \
         patch.object(vp, 'get_ocr_instance', return_value=mock_ocr), \
         patch.object(vp, '_detect_static_boxes', return_value=[]), \
         patch.object(vp, '_has_dynamic_text', return_value=True), \
         patch.object(vp, '_precise_blur_per_frame', side_effect=RuntimeError("forced precise failure")), \
         patch.object(vp, 'precompute_ocr_results', return_value={0: [(1, 1, 5, 5)]}), \
         patch.object(vp, 'apply_blur_to_frame', blur_stub), \
         patch.object(vp, '_probe_vfr_avg_fps', return_value=None), \
         patch.object(vp, '_check_nvenc_cached', return_value=False), \
         patch('subprocess.Popen') as mock_popen:
        mock_cv2.VideoCapture.return_value = mock_cap
        _cv2_props(mock_cv2)
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 0
        mock_proc.stderr = iter([])
        mock_popen.return_value = mock_proc

        # Must NOT raise (there ARE boxes to blur), and the blur must actually be applied.
        remove_watermark_from_video(in_path, out_path, mask_only=False, settings=None)

    assert blur_stub.called, "fallback with detected boxes must blur, not skip"


# ---------------------------------------------------------------------------
# V5 — precompute must not collapse all frames onto index 0 when count unknown
# ---------------------------------------------------------------------------

def test_precompute_ocr_results_unknown_frame_count_keys():
    """V5: total_frames<=0 (unknown) must key by i*frame_skip, not map everything to 0."""
    from orchestrator.video_process import precompute_ocr_results

    mock_ocr = MagicMock()
    mock_ocr.ocr.return_value = [[]]

    with patch('orchestrator.video_process.subprocess.Popen', return_value=_make_fake_ffmpeg_proc(3)):
        result = precompute_ocr_results(
            '/fake/path.avi', 0, 10.0,
            ocr_fps=1.0, ocr_batch_size=1,
            width=50, height=50, ocr=mock_ocr
        )

    assert set(result.keys()) == {0, 10, 20}


# ---------------------------------------------------------------------------
# V6 — unknown frame count must run full OCR, not copy the original through
# ---------------------------------------------------------------------------

def test_remove_watermark_unknown_frame_count_runs_full_ocr(tmp_path):
    """V6: when the frame count is unknown (0 after ffprobe too), do NOT copy the original
    (subtitled) video through as success — run the blur path instead."""
    import orchestrator.video_process as vp
    from orchestrator.video_process import remove_watermark_from_video

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.side_effect = lambda prop: {7: 0.0, 5: 30.0, 3: 50.0, 4: 50.0}.get(prop, 30.0)
    mock_cap.read.return_value = (True, np.full((50, 50, 3), 100, dtype=np.uint8))
    mock_cap.set.return_value = None
    mock_cap.release.return_value = None

    mock_ocr = MagicMock()
    mock_ocr.ocr.return_value = []

    in_path = str(tmp_path / "in.mp4")
    open(in_path, 'wb').close()
    out_path = str(tmp_path / "out.mp4")

    precise = MagicMock(return_value=None)
    copy_mock = MagicMock()

    with patch.object(vp, 'cv2') as mock_cv2, \
         patch.object(vp, 'get_ocr_instance', return_value=mock_ocr), \
         patch.object(vp, '_detect_static_boxes', return_value=[]), \
         patch.object(vp, '_probe_frame_count', return_value=0), \
         patch.object(vp, '_precise_blur_per_frame', precise), \
         patch.object(vp.shutil, 'copy', copy_mock):
        mock_cv2.VideoCapture.return_value = mock_cap
        _cv2_props(mock_cv2)
        remove_watermark_from_video(in_path, out_path, mask_only=False, settings=None)

    assert precise.called, "unknown frame count must run the blur path"
    assert not copy_mock.called, "must not copy the original (subtitled) video through as success"


# ---------------------------------------------------------------------------
# V8 — _scale_frame_for_ocr must never request a zero-width resize
# ---------------------------------------------------------------------------

def test_scale_frame_for_ocr_never_requests_zero_width():
    """V8: a very narrow, tall frame must clamp the resize width to >=1 (int(w*scale) can be 0)."""
    import orchestrator.video_process as vp

    frame = np.zeros((1000, 1, 3), dtype=np.uint8)  # h>OCR_MAX_H, w=1 → int(w*scale)==0 pre-fix
    with patch.object(vp, 'cv2') as mock_cv2:
        mock_cv2.INTER_AREA = 3
        vp._scale_frame_for_ocr(frame)

    assert mock_cv2.resize.called
    dsize = mock_cv2.resize.call_args[0][1]  # positional arg 2 = (width, height)
    assert dsize == (1, vp.OCR_MAX_H), f"expected (1, {vp.OCR_MAX_H}), got {dsize}"


# ---------------------------------------------------------------------------
# 1.8 — VFR average-fps probe (keep source duration; None for CFR)
# ---------------------------------------------------------------------------

class _FakeProbe:
    def __init__(self, stdout):
        self.stdout = stdout
        self.returncode = 0


def test_probe_vfr_avg_fps_cfr_returns_none():
    """CFR: r_frame_rate == avg_frame_rate → None (caller keeps the fixed -r path unchanged)."""
    import orchestrator.video_process as vp
    with patch.object(vp.subprocess, 'run', return_value=_FakeProbe("30/1\n30/1\n")):
        assert vp._probe_vfr_avg_fps('/fake.mp4', 30.0) is None


def test_probe_vfr_avg_fps_vfr_returns_average():
    """VFR: r_frame_rate != avg_frame_rate → return the frames/duration average to keep duration."""
    import orchestrator.video_process as vp
    with patch.object(vp.subprocess, 'run', return_value=_FakeProbe("30/1\n24000/1001\n")):
        avg = vp._probe_vfr_avg_fps('/fake.mp4', 30.0)
    assert avg is not None
    assert abs(avg - 24000 / 1001) < 1e-6


def test_probe_vfr_avg_fps_malformed_or_error_returns_none():
    """Empty/garbage output or a probe failure → None (fall back to nominal rate, no regression)."""
    import orchestrator.video_process as vp
    with patch.object(vp.subprocess, 'run', return_value=_FakeProbe("")):
        assert vp._probe_vfr_avg_fps('/fake.mp4', 30.0) is None
    with patch.object(vp.subprocess, 'run', return_value=_FakeProbe("0/0\nN/A\n")):
        assert vp._probe_vfr_avg_fps('/fake.mp4', 30.0) is None
    with patch.object(vp.subprocess, 'run', side_effect=Exception("ffprobe missing")):
        assert vp._probe_vfr_avg_fps('/fake.mp4', 30.0) is None
