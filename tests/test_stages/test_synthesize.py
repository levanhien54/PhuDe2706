import os
import sys
import types
import pytest
import numpy as np

# Stub out heavy dependencies before importing stages
for _mod in ("pyrubberband", "librosa"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

import soundfile as sf
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from orchestrator.stages.synthesize import run_synthesize
from orchestrator.models import SrtSegment, PipelineJob
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager


@pytest.fixture
def job():
    return PipelineJob(
        job_id="test-002",
        filename="sample.mp4",
        base_name="sample",
        vram_profile="16gb",
        created_at=datetime.utcnow(),
    )


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=str(tmp_path))


@pytest.fixture
def setup_temp(settings, job):
    """Create temp dir and a dummy vocal.wav reference file."""
    temp_dir = os.path.join(settings.data_dir, "temp", job.base_name)
    os.makedirs(temp_dir, exist_ok=True)
    vocal_path = os.path.join(temp_dir, "vocal.wav")
    sr = 22050
    dummy = np.zeros(sr, dtype=np.float32)
    sf.write(vocal_path, dummy, sr)
    return temp_dir, sr


@pytest.mark.asyncio
async def test_run_synthesize_success(job, settings, setup_temp):
    temp_dir, sr = setup_temp
    segments = [
        SrtSegment(start=0.0, end=2.0, text="Hello world", translated="Xin chào thế giới"),
        SrtSegment(start=2.0, end=4.0, text="Good morning", translated="Chào buổi sáng"),
    ]
    vram = VRAMManager(settings)

    def fake_synthesize_side_effect(text, reference_audio, output_path, target_duration, language=None, ref_text=None):
        data = np.zeros(int(sr * target_duration), dtype=np.float32)
        sf.write(output_path, data, sr)
        return output_path

    def fake_stretch_audio(input_path, output_path, target_duration):
        data, file_sr = sf.read(input_path)
        sf.write(output_path, data, file_sr)

    with patch(
        "orchestrator.stages.synthesize.TTSClient"
    ) as MockTTSClient, patch(
        "orchestrator.stages.synthesize.stretch_audio", side_effect=fake_stretch_audio
    ):
        mock_client = MagicMock()
        mock_client.synthesize = AsyncMock(side_effect=fake_synthesize_side_effect)
        MockTTSClient.return_value = mock_client

        result = await run_synthesize(job, segments, settings, vram)

    assert result.success is True
    assert result.output_path is not None
    assert result.output_path.endswith("new_vocal.wav")
    assert os.path.exists(result.output_path)
