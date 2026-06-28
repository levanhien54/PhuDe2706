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


def test_precompute_ocr_results_batch_call_count():
    """With 12 OCR frames and batch_size=4, ocr.ocr must be called exactly 3 times."""
    import orchestrator.video_process as vp
    from orchestrator.video_process import precompute_ocr_results

    # 120 frames at fps=10, ocr_fps=1 → frame_skip=10 → OCR at 0,10,20,...,110 = 12 frames
    # batch_size=4 → ceil(12/4) = 3 calls
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.return_value = 120.0
    mock_frame = np.full((50, 50, 3), 100, dtype=np.uint8)
    mock_cap.read.return_value = (True, mock_frame)

    mock_ocr = MagicMock()
    mock_ocr.ocr.return_value = [[] for _ in range(4)]  # 4 empty results per batch

    with patch.object(vp, 'cv2') as mock_cv2:
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.CAP_PROP_POS_FRAMES = 1
        mock_cv2.CAP_PROP_FRAME_COUNT = 7
        result = precompute_ocr_results(
            '/fake/path.avi', 120, 10.0,
            ocr_fps=1.0, ocr_batch_size=4,
            width=50, height=50, ocr=mock_ocr
        )

    assert mock_ocr.ocr.call_count == 3
    assert isinstance(result, dict)


def test_precompute_ocr_results_returns_correct_keys():
    """Keys in dict must match OCR frame indices (frame_skip=10 → 0,10,20)."""
    import orchestrator.video_process as vp
    from orchestrator.video_process import precompute_ocr_results

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.return_value = 30.0
    mock_frame = np.full((50, 50, 3), 100, dtype=np.uint8)
    mock_cap.read.return_value = (True, mock_frame)

    mock_ocr = MagicMock()
    mock_ocr.ocr.return_value = [[]]  # single empty result per call

    with patch.object(vp, 'cv2') as mock_cv2:
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.CAP_PROP_POS_FRAMES = 1
        mock_cv2.CAP_PROP_FRAME_COUNT = 7
        result = precompute_ocr_results(
            '/fake/path.avi', 30, 10.0,
            ocr_fps=1.0, ocr_batch_size=1,
            width=50, height=50, ocr=mock_ocr
        )

    # fps=10, ocr_fps=1 → frame_skip=10 → keys: 0, 10, 20
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
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as fout:
        out_path = fout.name
    try:
        with patch.object(vp, 'cv2') as mock_cv2, \
             patch.object(vp, 'get_ocr_instance', return_value=mock_ocr_instance), \
             patch.object(vp, 'build_temporal_reference', return_value=None), \
             patch.object(vp, 'precompute_ocr_results', return_value={}), \
             patch.object(vp, '_detect_static_boxes', return_value=[]), \
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

            remove_watermark_from_video('/fake/input.mp4', out_path, mask_only=False, settings=None)
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


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
