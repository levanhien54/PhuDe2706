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
