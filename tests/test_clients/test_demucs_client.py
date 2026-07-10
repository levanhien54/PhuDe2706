import asyncio
import os
from unittest.mock import patch

import pytest
import respx
import httpx
from orchestrator.clients.demucs_client import DemucsClient
from orchestrator.config import Settings


@pytest.fixture
def settings():
    return Settings(demucs_api="http://demucs-test:8000", http_retries=1, http_timeout=5.0)


@pytest.fixture
def tmp_video(tmp_path):
    f = tmp_path / "test.mp4"
    f.write_bytes(b"fake_video_content")
    return str(f)


@pytest.mark.asyncio
async def test_separate_returns_paths(settings, tmp_video, tmp_path):
    with respx.mock:
        respx.get("http://demucs-test:8000/health").mock(return_value=httpx.Response(200))
        respx.post("http://demucs-test:8000/separate").mock(
            return_value=httpx.Response(200, json={
                "vocal": "/data/temp/test_vocal.wav",
                "background": "/data/temp/test_bg.wav"
            })
        )
        client = DemucsClient(settings)
        result = await client.separate(tmp_video, str(tmp_path))
        assert "vocal" in result
        assert "background" in result


def _fake_demucs(out_dir, model, base):
    """create_subprocess_exec stand-in: records argv and emulates demucs writing its stems under
    <out>/<model>/<base>/ (so the client's move/cleanup uses the right, model-named folder)."""
    captured = {}

    def fake_create(*args, **kwargs):
        captured["cmd"] = list(args)
        d = os.path.join(out_dir, model, base)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "vocals.wav"), "w").close()
        open(os.path.join(d, "no_vocals.wav"), "w").close()

        class _P:
            returncode = 0

            async def communicate(self):
                return (b"", b"")

            def kill(self):
                pass

            async def wait(self):
                return 0

        return _P()

    return fake_create, captured


def test_demucs_default_model_is_ft():
    assert Settings(_env_file=None).demucs_model == "htdemucs_ft"


def test_demucs_local_uses_configured_model(tmp_path):
    # FAST_MODE / DEMUCS_MODEL=htdemucs must flow into BOTH the -n flag and the output-folder path;
    # a mismatch would make the stem move look in the wrong (htdemucs_ft) folder and fail.
    out = tmp_path / "out"
    out.mkdir()
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"x")
    settings = Settings(demucs_api="local", demucs_model="htdemucs", _env_file=None)
    client = DemucsClient(settings)

    fake_create, captured = _fake_demucs(str(out), "htdemucs", "v")
    with patch("asyncio.create_subprocess_exec", side_effect=fake_create):
        result = asyncio.run(client.separate(str(vid), str(out)))

    cmd = captured["cmd"]
    assert cmd[cmd.index("-n") + 1] == "htdemucs"
    assert os.path.exists(result["vocal"]) and os.path.exists(result["background"])
    assert not os.path.exists(os.path.join(str(out), "htdemucs"))  # work dir cleaned after move
