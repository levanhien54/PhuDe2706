# tts-service — GPT-SoVITS Adapter

A thin REST adapter that wraps [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) and exposes the exact JSON API the orchestrator's `TTSClient` expects.

## Why this adapter exists

The upstream GPT-SoVITS API streams raw audio bytes. The orchestrator contract requires:

- `GET /health` → `{"status": "ok"}`
- `POST /tts` with JSON body → `{"output_path": "/path/to/written.wav"}`

This adapter accepts the JSON request, runs GPT-SoVITS inference, **writes the WAV to the shared volume path** (`output_path`), and returns the JSON response the orchestrator reads.

## When is this service used?

Only when `TTS_ENGINE=gpt_sovits` in your environment. The default engine is `omnivoice`; this service is ignored in that configuration.

## Endpoints

### `GET /health`
Returns `{"status": "ok"}`. Used by Docker healthcheck and the orchestrator's startup probe.

### `POST /tts`
Request body (all fields unless noted):

```json
{
  "text": "Xin chào thế giới",
  "text_language": "vi",
  "refer_wav_path": "/data/temp/reference.wav",
  "output_path": "/data/temp/out_segment_01.wav",
  "prompt_text": "optional transcription of the reference clip",
  "prompt_language": "vi"
}
```

- `refer_wav_path` and `output_path` must be paths **inside the shared `./data/temp` volume** that both the orchestrator and this container mount.
- `prompt_text` / `prompt_language` are optional. If omitted, the service falls back to `GPT_SOVITS_PROMPT_TEXT` / `GPT_SOVITS_PROMPT_LANG` env vars.

Response:
```json
{"output_path": "/data/temp/out_segment_01.wav"}
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `GPT_SOVITS_DIR` | `/app/GPT-SoVITS` | Path where the repo is cloned at build time |
| `GPT_SOVITS_PROMPT_TEXT` | `""` | Fallback transcription of the reference clip when `prompt_text` is not sent by the caller |
| `GPT_SOVITS_PROMPT_LANG` | `auto` | Fallback language for the reference clip |

## Models

GPT-SoVITS models (GPT weights `.ckpt` and SoVITS weights `.pth`) must be present before inference works. Mount your model directory into the container at the path GPT-SoVITS expects (typically `/app/GPT-SoVITS/GPT_weights` and `/app/GPT-SoVITS/SoVITS_weights`) or configure via the upstream repo's own env vars.

## Integration point — single place to update

The entire GPT-SoVITS-specific call lives in **one function** in `app.py`:

```python
def synthesize_wav(text, text_language, refer_wav_path, output_path, prompt_text, prompt_language):
```

Inside it, the import:

```python
from GPT_SoVITS.inference_webui import get_tts_wav
```

is the **only line that must be verified on the GPU host**. If the pinned repo revision changes the module layout (e.g. the function moves or is renamed), update that import and the call signature here — nothing else needs to change.

## Build

```bash
docker build -t tts-service ./tts-service
```

The Dockerfile clones GPT-SoVITS at `--depth 1` (latest HEAD) at build time, installs PyTorch 2.1 + cu118, the upstream `requirements.txt`, and our thin adapter deps.

To pin a specific commit, change the clone line in the Dockerfile:

```dockerfile
RUN git clone --depth 1 --branch v2.0 https://github.com/RVC-Boss/GPT-SoVITS.git /app/GPT-SoVITS
```
