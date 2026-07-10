import asyncio
import mimetypes
import os
import random
import httpx
from orchestrator.config import Settings
from orchestrator.logger import get_logger

log = get_logger(__name__)

# Hard ceiling (seconds) for a GPU child subprocess (separation / lip-sync / inpaint) so a
# wedged process can't hang the worker forever. Large default (1h) covers slow HD jobs;
# override with GPU_SUBPROCESS_TIMEOUT_SEC. Read at call time so tests/env can adjust it.
_DEFAULT_GPU_SUBPROCESS_TIMEOUT = 3600.0


def gpu_subprocess_timeout() -> float:
    try:
        return float(os.environ.get("GPU_SUBPROCESS_TIMEOUT_SEC", _DEFAULT_GPU_SUBPROCESS_TIMEOUT))
    except (TypeError, ValueError):
        return _DEFAULT_GPU_SUBPROCESS_TIMEOUT


def _guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


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

    async def _retry(self, url: str, do):
        """Run an async request thunk under the shared retry/backoff policy.
        Retries on connect/timeout and 5xx; propagates 4xx immediately."""
        last_exc = None
        for attempt in range(self.settings.http_retries):
            try:
                return await do()
            except (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.RemoteProtocolError,
                httpx.ReadError,
            ) as e:
                # RemoteProtocolError/ReadError: the server dropped the connection mid-response.
                # That is transient (like a connect/timeout failure), so retry rather than abort.
                last_exc = e
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500:
                    raise  # 4xx: don't retry, propagate immediately
                last_exc = e
            if attempt >= self.settings.http_retries - 1:
                break  # don't sleep after the final attempt — we're about to raise
            wait = (2 ** attempt) + random.uniform(0, 0.5)  # jitter to avoid synchronized retries
            log.warning("http_retry", attempt=attempt + 1, url=url, error=str(last_exc), wait=round(wait, 3))
            await asyncio.sleep(wait)
        raise ServiceUnavailableError(f"Failed after {self.settings.http_retries} retries: {last_exc}")

    async def post_json(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.base_url}{endpoint}"
        async def _do():
            async with httpx.AsyncClient(timeout=self.settings.http_timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Server error {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                return resp.json()
        return await self._retry(url, _do)

    async def post_file(self, endpoint: str, file_path: str, extra_data: dict | None = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        async def _do():
            async with httpx.AsyncClient(timeout=self.settings.http_timeout) as client:
                with open(file_path, "rb") as f:
                    files = {"file": (os.path.basename(file_path), f, _guess_mime(file_path))}
                    resp = await client.post(url, files=files, data=extra_data or {})
                    if resp.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"Server error {resp.status_code}", request=resp.request, response=resp
                        )
                    resp.raise_for_status()
                    return resp.json()
        return await self._retry(url, _do)
