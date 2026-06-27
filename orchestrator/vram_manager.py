import asyncio
from contextlib import asynccontextmanager
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)

_TOTAL_BY_PROFILE = {"16gb": 16.0, "24gb": 24.0}

class VRAMManager:
    def __init__(self, settings: Settings):
        self.total_gb = _TOTAL_BY_PROFILE.get(settings.vram_profile, 16.0)
        self._allocated: dict[str, float] = {}
        self._condition = asyncio.Condition()

    def available_gb(self) -> float:
        return self.total_gb - sum(self._allocated.values())

    async def acquire(self, service: str, vram_gb: float) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: self.available_gb() >= vram_gb)
            self._allocated[service] = vram_gb
            log.info("vram_acquire", service=service, requested_gb=vram_gb, remaining_gb=round(self.available_gb(), 2))

    async def release(self, service: str) -> None:
        async with self._condition:
            freed = self._allocated.pop(service, 0.0)
            log.info("vram_release", service=service, freed_gb=freed, remaining_gb=round(self.available_gb(), 2))
            self._condition.notify_all()

    @asynccontextmanager
    async def slot(self, service: str, vram_gb: float):
        await self.acquire(service, vram_gb)
        try:
            yield
        finally:
            await self.release(service)


_instance: "VRAMManager | None" = None

def get_vram_manager(settings) -> "VRAMManager":
    global _instance
    if _instance is None:
        _instance = VRAMManager(settings)
    return _instance
