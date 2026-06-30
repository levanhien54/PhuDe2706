# Full Deployment Installer — Design Spec

Date: 2026-06-30
Status: Approved (proceed to implementation)

## Goal

Ship the AI Video Dubbing app to **another Windows machine** as easily as installing a
single piece of software: a **Setup.exe** that installs every component (no manual
Python/Node/FFmpeg/Ollama install, no setup scripts), then the user double-clicks one
**"Video Dubbing.exe"** and it runs. Optimised for the **current working configuration**
(GPU cu118 venv, 24 GB VRAM `.env`, `qwen2.5:14b` LLM) — not a portable/CPU variant.

## Hard constraints (current config)

- **Target must have an NVIDIA GPU + recent driver.** The bundled venv is cu118 torch +
  paddle-gpu; a CPU-only target is explicitly out of scope.
- Offline 100% — every model/binary is bundled.
- Bundle size ≈ **30 GB** (venv 11 GB, models 15 GB incl. 8.4 GB Ollama model, Ollama
  runtime 3.1 GB, python-runtime 0.12 GB, ffmpeg ~0.3 GB).

## Core technical mechanism (validated)

The venv is **not** self-contained: `venv/Lib` holds only `site-packages` (no stdlib),
and `venv/Scripts/python.exe` has no `python310.dll`. Both come from the base Python via
`venv/pyvenv.cfg`'s `home`, which on this machine is an absolute path
(`...\Programs\Python\Python310`) that won't exist on the target.

**Fix (proven):** ship the base Python 3.10.11 (only 121 MB) as `python-runtime/` and
repoint `pyvenv.cfg home` at it. Validated: with `home` → a *copied* runtime, the venv
runs fully — `sys.base_prefix`/stdlib resolve to the copy and `torch 2.7.1+cu118
cuda=True`, `cv2`, `easyocr` all import. So the venv runs on a machine with **no system
Python**.

## Launch-flow gaps found in `electron/main.js` (fixed)

The EXE spawns the Python services itself, but on a clean machine three things break:

1. **OmniVoice always uses `venv/Scripts/python.exe`** → needs `pyvenv.cfg` repaired.
2. **It never starts Ollama** → translation (Qwen2.5) fails. Must bundle `ollama.exe` +
   `lib/` and run `ollama serve` with `OLLAMA_MODELS` → bundled model store.
3. **FFmpeg/FFprobe not on PATH** → `ffprobe` only exists under
   `ffmpeg_extracted/.../bin`; services call bare `ffmpeg`/`ffprobe`.

Also: `.env` sets relative `WHISPER_MODEL_DIR=./models/whisper`, which resolves against a
service's own CWD (a subdir) and misses the weights — must be made absolute.

### `main.js` changes (done)

- `repairVenvConfig()` at startup: if `python-runtime/python.exe` exists, rewrite
  `venv/pyvenv.cfg` `home` → `<root>/python-runtime` (idempotent, no-op in dev).
- `resolveSystemPython()`: prefer `python-runtime/python.exe` (clean interpreter, dodges
  the venv shm.dll bug, ABI-correct 3.10).
- `loadEnv()`: prepend `[PROJECT_ROOT, ffmpeg bin, ollama dir]` to PATH; set absolute
  `WHISPER_MODEL_DIR`/`OMNIVOICE_MODEL_DIR`; set `OLLAMA_MODELS`.
- `startOllama()`: spawn bundled `ollama/ollama.exe serve` (fallback to system), tracked
  for cleanup; called first in `startAllServices()`.

## Bundle layout (staged self-contained folder)

```
<install dir>/
  Video Dubbing.exe         portable Electron+Chromium shell (PORTABLE_EXECUTABLE_DIR = this dir)
  frontend/dist/            UI loaded from disk
  orchestrator/  whisperx-service/  tts-service/  omnivoice-service/  GPT-SoVITS/
  venv/                     11 GB, cu118 (pyvenv.cfg repaired on first launch)
  python-runtime/           Python 3.10.11 base (121 MB)
  ffmpeg_extracted/.../bin/ ffmpeg.exe + ffprobe.exe
  ollama/                   ollama.exe + lib/ (CUDA)        [3.1 GB]
  models/                   easyocr, whisper, omnivoice, ollama  [15 GB]
  voices/                   narrator presets
  .env                      tuned 24 GB config
  icon.ico
  data/{input,output,temp}/
```

`offline_wheels/` is **excluded** — the venv ships pre-built, so no pip step on the
target (saves 3.3 GB).

## Packaging (Setup.exe)

A ~30 GB single Setup.exe is not robust (NSIS file-size limits, compile cost). Use:

- **`Setup.exe`** — small NSIS installer (dir picker, Start-Menu + Desktop shortcuts,
  registered uninstaller). Embeds `7za.exe` + extract/shortcut/uninstall logic.
- **`app.7z`** — the ~20 GB compressed staged folder, shipped **alongside** Setup.exe.
  The installer extracts the sibling payload to the chosen dir, then repairs `pyvenv.cfg`
  to the install path.

This is the standard "big software" install (setup.exe + data file) and still a single
double-click. Deliverable = a folder containing `Setup.exe` + `app.7z`.

## Build pipeline

1. `build-electron.ps1` (already fixed: UTF-8 BOM; winCodeSign pre-extracted) → portable
   `Video Dubbing.exe` with the patched `main.js`.
2. `pack_full_bundle.ps1` → assemble the staged self-contained folder (above).
3. 7z-compress staging → `app.7z`.
4. `installer.nsi` via bundled `makensis` → `Setup.exe`.
5. Validation: extract `app.7z` to a *different* path, launch, confirm services +
   pyvenv repair + Ollama + FFmpeg resolve.

## Out of scope

- CPU-only target (no GPU) — different venv, separate effort.
- GPT-SoVITS Python deps (alternate TTS; OmniVoice is default and fully covered).
- Auto driver install — assume a working NVIDIA driver on the target.
