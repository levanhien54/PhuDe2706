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
