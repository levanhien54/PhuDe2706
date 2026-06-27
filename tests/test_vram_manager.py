import pytest
import asyncio
from orchestrator.vram_manager import VRAMManager
from orchestrator.config import Settings


@pytest.fixture
def mgr_16():
    return VRAMManager(Settings(vram_profile="16gb"))


@pytest.fixture
def mgr_24():
    return VRAMManager(Settings(vram_profile="24gb"))


@pytest.mark.asyncio
async def test_16gb_total(mgr_16):
    assert mgr_16.total_gb == 16.0


@pytest.mark.asyncio
async def test_24gb_total(mgr_24):
    assert mgr_24.total_gb == 24.0


@pytest.mark.asyncio
async def test_acquire_release(mgr_16):
    await mgr_16.acquire("whisperx", 5.0)
    assert mgr_16.available_gb() == 11.0
    await mgr_16.release("whisperx")
    assert mgr_16.available_gb() == 16.0


@pytest.mark.asyncio
async def test_slot_context_manager(mgr_16):
    async with mgr_16.slot("demucs", 3.0):
        assert mgr_16.available_gb() == 13.0
    assert mgr_16.available_gb() == 16.0


@pytest.mark.asyncio
async def test_waits_for_capacity(mgr_16):
    await mgr_16.acquire("big_model", 14.0)
    # Now only 2GB available, requesting 5GB should wait
    acquired = False

    async def delayed_release():
        await asyncio.sleep(0.1)
        await mgr_16.release("big_model")

    async def try_acquire():
        nonlocal acquired
        await mgr_16.acquire("other", 5.0)
        acquired = True

    await asyncio.gather(delayed_release(), try_acquire())
    assert acquired is True
