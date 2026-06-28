import os
import sys
import tempfile
import numpy as np
import pytest
from unittest.mock import MagicMock, patch, call


# Skip this test module if cv2 is not really available (test environment)
try:
    import cv2
    _cv2_available = hasattr(cv2, 'VideoCapture') and hasattr(cv2, 'VideoWriter')
except (ImportError, AttributeError):
    _cv2_available = False


def _make_test_video(path: str, n_frames: int = 30, h: int = 50, w: int = 50) -> None:
    """Tạo video synthetic dùng MJPG codec (không cần ffmpeg)."""
    import cv2
    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
    writer = cv2.VideoWriter(path, fourcc, 10.0, (w, h))
    assert writer.isOpened(), f"VideoWriter failed for {path}"
    for i in range(n_frames):
        # Frame màu xám với giá trị tăng dần để median dễ tính
        frame = np.full((h, w, 3), min(i * 8, 200), dtype=np.uint8)
        writer.write(frame)
    writer.release()


@pytest.mark.skipif(not _cv2_available, reason="cv2.VideoCapture not available in test environment")
def test_build_temporal_reference_shape():
    from orchestrator.video_process import build_temporal_reference

    with tempfile.NamedTemporaryFile(suffix='.avi', delete=False) as f:
        path = f.name
    try:
        _make_test_video(path, n_frames=30, h=50, w=50)
        result = build_temporal_reference(path, n_samples=10)
        assert result is not None
        assert result.shape == (50, 50, 3)
        assert result.dtype == np.uint8
    finally:
        if os.path.exists(path):
            os.unlink(path)


@pytest.mark.skipif(not _cv2_available, reason="cv2.VideoCapture not available in test environment")
def test_build_temporal_reference_short_video_returns_none():
    from orchestrator.video_process import build_temporal_reference

    with tempfile.NamedTemporaryFile(suffix='.avi', delete=False) as f:
        path = f.name
    try:
        _make_test_video(path, n_frames=2)
        result = build_temporal_reference(path, n_samples=10)
        assert result is None
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_build_temporal_reference_invalid_path():
    """Test that invalid path returns None."""
    # In test environment, cv2 is stubbed, so we import and patch at function call level
    import orchestrator.video_process as vp_module

    # Create a mock VideoCapture that fails to open
    mock_cap_class = MagicMock()
    mock_cap_instance = MagicMock()
    mock_cap_instance.isOpened.return_value = False
    mock_cap_instance.release.return_value = None
    mock_cap_class.return_value = mock_cap_instance

    original_cv2 = vp_module.cv2
    original_cap = getattr(original_cv2, 'VideoCapture', None)

    try:
        # Mock cv2.VideoCapture to return a closed capture
        vp_module.cv2.VideoCapture = mock_cap_class

        from orchestrator.video_process import build_temporal_reference
        result = build_temporal_reference("/nonexistent/path.avi", n_samples=5)
        assert result is None
    finally:
        # Restore original
        if original_cap is not None:
            vp_module.cv2.VideoCapture = original_cap
