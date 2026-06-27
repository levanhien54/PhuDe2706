import asyncio
import httpx
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)


class ServiceUnavailableError(Exception):
    pass


class BaseClient:
    def __init__(self, base_url: str, settings: Settings):
        self.base_url = base_url.rstrip("/")
        self.settings = settings

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    async def post_json(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.base_url}{endpoint}"
        last_exc = None
        for attempt in range(self.settings.http_retries):
            try:
                async with httpx.AsyncClient(timeout=self.settings.http_timeout) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"Server error {resp.status_code}", request=resp.request, response=resp
                        )
                    resp.raise_for_status()
                    return resp.json()
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = e
                wait = 2 ** attempt
                log.warning("http_retry", attempt=attempt + 1, url=url, error=str(e), wait=wait)
                await asyncio.sleep(wait)
        raise ServiceUnavailableError(f"Failed after {self.settings.http_retries} retries: {last_exc}")

    async def post_file(self, endpoint: str, file_path: str, extra_data: dict | None = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        last_exc = None
        for attempt in range(self.settings.http_retries):
            try:
                async with httpx.AsyncClient(timeout=self.settings.http_timeout) as client:
                    with open(file_path, "rb") as f:
                        files = {"file": (file_path.split("/")[-1], f, "audio/wav")}
                        data = extra_data or {}
                        resp = await client.post(url, files=files, data=data)
                        if resp.status_code >= 500:
                            raise httpx.HTTPStatusError(
                                f"Server error {resp.status_code}", request=resp.request, response=resp
                            )
                        resp.raise_for_status()
                        return resp.json()
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = e
                wait = 2 ** attempt
                log.warning("http_retry", attempt=attempt + 1, url=url, error=str(e), wait=wait)
                await asyncio.sleep(wait)
        raise ServiceUnavailableError(f"Failed after {self.settings.http_retries} retries: {last_exc}")
