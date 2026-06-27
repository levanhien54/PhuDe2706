# whisperx-service

A local FastAPI service that wraps [WhisperX](https://github.com/m-bain/whisperX) for audio transcription with word-level alignment and optional speaker diarization.

Built as part of the video dubbing pipeline. It is **not pulled from a registry** — it is built locally via `docker compose build`.

## Endpoints

### `GET /health`
Returns `{"status": "ok", "device": "...", "model": "..."}` when the service is up.

### `POST /transcribe`
Accepts a multipart form upload with a single field named `file` (the audio file, e.g. `vocal.wav`).

Returns:
```json
{
  "segments": [
    {"start": 0.0, "end": 2.5, "text": "Hello world", "speaker": "SPEAKER_00"},
    ...
  ]
}
```
`speaker` is `null` when diarization is disabled (no `HF_TOKEN`).

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `large-v3` | WhisperX model size (e.g. `base`, `small`, `medium`, `large-v2`, `large-v3`) |
| `WHISPER_LANGUAGE` | *(auto-detect)* | Force a specific language code (e.g. `en`, `vi`). Leave unset for auto-detection. |
| `HF_TOKEN` | *(unset)* | Hugging Face token. Required for speaker diarization via pyannote. If unset, diarization is skipped and `speaker` will be `null`. |

## Build & Run

The service is wired into the project via `docker-compose.yml`. To build and start it:

```bash
docker compose build whisperx-service
docker compose up whisperx-service
```

The model cache is mounted at `./models/whisper` → `/root/.cache` to persist downloaded weights across container restarts.
