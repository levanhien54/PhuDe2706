"""Source-separation engine selection (Demucs default, BS-Roformer alternative).

Verifies run_audio_separate builds the client chosen by SEPARATION_ENGINE and calls its
separate(); the client is mocked so no model/GPU is needed."""
import asyncio
from unittest.mock import patch, AsyncMock

from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.models import PipelineJob
from orchestrator.stages import audio_separate


def _ctx(engine, tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "input").mkdir(parents=True)
    (data_dir / "input" / "v.mp4").write_bytes(b"x")
    settings = Settings(
        vram_profile="16gb", separation_engine=engine, data_dir=str(data_dir), _env_file=None,
    )
    return settings, VRAMManager(settings), PipelineJob(job_id="j", filename="v.mp4", base_name="v")


def test_default_engine_is_demucs(monkeypatch):
    monkeypatch.delenv("SEPARATION_ENGINE", raising=False)
    assert Settings(_env_file=None).separation_engine == "demucs"


def test_selects_bs_roformer_when_configured(tmp_path):
    settings, vram, job = _ctx("bs_roformer", tmp_path)
    fake = AsyncMock(return_value={"vocal": "v.wav", "background": "b.wav"})
    with patch("orchestrator.stages.audio_separate.BSRoformerClient") as bs, \
         patch("orchestrator.stages.audio_separate.DemucsClient") as dm:
        bs.return_value.separate = fake
        result = asyncio.run(audio_separate.run_audio_separate(job, settings, vram))
    assert result.success
    bs.assert_called_once()
    dm.assert_not_called()


def test_selects_demucs_by_default(tmp_path):
    settings, vram, job = _ctx("demucs", tmp_path)
    fake = AsyncMock(return_value={"vocal": "v.wav", "background": "b.wav"})
    with patch("orchestrator.stages.audio_separate.BSRoformerClient") as bs, \
         patch("orchestrator.stages.audio_separate.DemucsClient") as dm:
        dm.return_value.separate = fake
        result = asyncio.run(audio_separate.run_audio_separate(job, settings, vram))
    assert result.success
    dm.assert_called_once()
    bs.assert_not_called()
