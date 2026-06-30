import pytest
import os
from unittest.mock import patch
from orchestrator.audio_sync import stretch_audio, mix_audio_to_video

def test_stretch_audio_invalid_target():
    # Giả lập file tồn tại để vượt qua check đầu tiên
    with patch("os.path.exists", return_value=True):
        with pytest.raises(ValueError, match="target_duration must be positive"):
            stretch_audio("dummy.wav", "out.wav", -1)

def test_stretch_audio_missing_input():
    with pytest.raises(FileNotFoundError, match="Input file not found"):
        stretch_audio("does_not_exist.wav", "out.wav", 5.0)

def test_mix_audio_to_video_missing_input(tmp_path):
    video = tmp_path / "v.mp4"
    vocal = tmp_path / "vocal.wav"
    bg = tmp_path / "bg.wav"
    out = tmp_path / "out.mp4"
    
    # Missing all
    with pytest.raises(FileNotFoundError, match="Missing input"):
        mix_audio_to_video(str(video), str(vocal), str(bg), str(out))
        
    # Touch one, still missing others
    video.touch()
    with pytest.raises(FileNotFoundError, match="Missing input"):
        mix_audio_to_video(str(video), str(vocal), str(bg), str(out))

@patch("orchestrator.audio_sync.subprocess.run")
def test_mix_audio_to_video_ffmpeg_fail(mock_run, tmp_path):
    video = tmp_path / "v.mp4"
    vocal = tmp_path / "vocal.wav"
    bg = tmp_path / "bg.wav"
    out = tmp_path / "out.mp4"
    
    video.touch()
    vocal.touch()
    bg.touch()
    
    # Mock subprocess to fail
    class MockResult:
        returncode = 1
        stderr = "ffmpeg crashed!"
        
    mock_run.return_value = MockResult()
    
    with pytest.raises(RuntimeError, match="FFmpeg mux failed"):
        mix_audio_to_video(str(video), str(vocal), str(bg), str(out))
