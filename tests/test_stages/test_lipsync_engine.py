"""Lip-sync engine selection (LatentSync default, MuseTalk alternative).

Verifies run_lip_sync dispatches to the engine chosen by LIPSYNC_ENGINE without invoking any
real model (both clients are mocked), so it needs no GPU/weights."""
import asyncio
from unittest.mock import patch, AsyncMock

from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.models import PipelineJob
from orchestrator.stages import lip_sync


def _ctx(engine, tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "temp" / "v").mkdir(parents=True)
    settings = Settings(
        vram_profile="16gb", enable_lipsync=True, lipsync_engine=engine,
        data_dir=str(data_dir), _env_file=None,
    )
    return settings, VRAMManager(settings), PipelineJob(job_id="j", filename="v.mp4", base_name="v")


def test_default_engine_is_latentsync(monkeypatch):
    monkeypatch.delenv("LIPSYNC_ENGINE", raising=False)
    assert Settings(_env_file=None).lipsync_engine == "latentsync"


def test_selects_musetalk_when_configured(tmp_path):
    settings, vram, job = _ctx("musetalk", tmp_path)
    with patch("orchestrator.stages.lip_sync.run_musetalk_inference", new_callable=AsyncMock) as mt, \
         patch("orchestrator.stages.lip_sync.run_latentsync_inference", new_callable=AsyncMock) as ls:
        result = asyncio.run(lip_sync.run_lip_sync(job, settings, vram))
    assert result.success
    mt.assert_awaited_once()
    ls.assert_not_awaited()


def test_selects_latentsync_by_default(tmp_path):
    settings, vram, job = _ctx("latentsync", tmp_path)
    with patch("orchestrator.stages.lip_sync.run_musetalk_inference", new_callable=AsyncMock) as mt, \
         patch("orchestrator.stages.lip_sync.run_latentsync_inference", new_callable=AsyncMock) as ls:
        result = asyncio.run(lip_sync.run_lip_sync(job, settings, vram))
    assert result.success
    ls.assert_awaited_once()
    mt.assert_not_awaited()
