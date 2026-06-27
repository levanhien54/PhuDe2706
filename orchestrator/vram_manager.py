import asyncio
from contextlib import asynccontextmanager
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)

_TOTAL_BY_PROFILE = {"16gb": 16.0, "24gb": 24.0}
_RESERVED_OVERHEAD = 1.5  # OS + driver overhead GB


class VRAMManager:
    def __init__(self, settings: Settings):
        self.total_gb = _TOTAL_BY_PROFILE.get(settings.vram_profile, 16.0)
        self._allocated: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._event = asyncio.Event()
        self._event.set()

    def available_gb(self) -> float:
        used = sum(self._allocated.values())
        return self.total_gb - used

    def _capacity_gb(self) -> float:
        """Usable VRAM after reserving overhead."""
        return self.total_gb - _RESERVED_OVERHEAD

    async def acquire(self, service: str, vram_gb: float) -> None:
        while True:
            async with self._lock:
                if self.available_gb() >= vram_gb:
                    self._allocated[service] = vram_gb
                    log.info(
                        "vram_acquire",
                        service=service,
                        requested_gb=vram_gb,
                        remaining_gb=round(self.available_gb(), 2),
                    )
                    return
            # Not enough VRAM — wait for a release event
            self._event.clear()
            await self._event.wait()

    async def release(self, service: str) -> None:
        async with self._lock:
            freed = self._allocated.pop(service, 0.0)
            log.info(
                "vram_release",
                service=service,
                freed_gb=freed,
                remaining_gb=round(self.available_gb(), 2),
            )
        self._event.set()

    @asynccontextmanager
    async def slot(self, service: str, vram_gb: float):
        await self.acquire(service, vram_gb)
        try:
            yield
        finally:
            await self.release(service)
