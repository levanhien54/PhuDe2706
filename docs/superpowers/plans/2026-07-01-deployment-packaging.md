# Deployment Packaging & Auto-Verify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the app to other NVIDIA/Windows machines via the approved Setup.exe + app.7z model, with automatic environment preflight, an in-app service health dashboard, and a Vietnamese documentation set.

**Architecture:** Add a self-contained PowerShell preflight checker (run standalone + by the installer), an aggregated `GET /api/health` in the orchestrator feeding both an Electron splash checklist and a React header badge, and a `HƯỚNG-DẪN/` docs folder — all staged into the bundle by the existing pack/installer scripts.

**Tech Stack:** Python 3.10 / FastAPI (orchestrator), React 18 + Vite (frontend), Electron 31 (shell), PowerShell 5.1 (scripts), NSIS (installer), pytest + respx (tests).

## Global Constraints

- Target: Windows 10/11 x64 with an NVIDIA GPU (≥16 GB VRAM). CPU-only is out of scope.
- Deployment model is fixed: `Setup.exe` + `app.7z` (do NOT change it).
- Documentation is in **Vietnamese**.
- Script/asset filenames shipped in the bundle use **ASCII-safe names** (e.g. `Kiem-tra-he-thong.bat`), with Vietnamese labels only in shortcut text / file *contents* — avoids NSIS/encoding risk.
- Service settings come from `orchestrator/config.py`: `whisperx_api` (:8001), `tts_api` (:9880), `omnivoice_api` (:3900), `ollama_host` (:11434), `tts_engine` (default `omnivoice`), `llm_backend` (default `ollama`). Sub-services expose `GET /health`; Ollama exposes `GET /api/tags`.
- Run the Python test-suite with the project venv: `./venv/Scripts/python.exe -m pytest ... -p no:cacheprovider`.
- Frontend build/lint from `frontend/`: `./node_modules/.bin/vite build`, `./node_modules/.bin/oxlint <files>`.

---

### Task 1: Orchestrator `GET /api/health` aggregate endpoint

**Files:**
- Modify: `orchestrator/api.py` (add imports + `_gpu_info`, `_ping`, `_HEALTH_CACHE`, `api_health` route near the other `@app.get` routes)
- Test: `tests/test_api_health.py`

**Interfaces:**
- Produces: `GET /api/health` → JSON `{"services": {"orchestrator":"up","whisperx":"up|down", <tts>, <llm>}, "ready": int, "total": int, "gpu": {"name":str,"vram_used_mb":int,"vram_total_mb":int}|null}`. Always HTTP 200. `<tts>` key is `omnivoice` or `tts` per `tts_engine`; `<llm>` key is `ollama` or `vllm` per `llm_backend`.
- Consumes: `settings` (already module-global in api.py), `asyncio` (already imported).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_health.py`:
```python
import asyncio
import httpx
import respx
from orchestrator import api


def _reset_cache():
    api._HEALTH_CACHE.update(ts=0.0, data=None)


def test_api_health_all_up(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(api, "_gpu_info", lambda: None)
    with respx.mock:
        respx.get("http://127.0.0.1:8001/health").mock(return_value=httpx.Response(200))
        respx.get("http://127.0.0.1:3900/health").mock(return_value=httpx.Response(200))
        respx.get("http://127.0.0.1:11434/api/tags").mock(return_value=httpx.Response(200, json={}))
        data = asyncio.run(api.api_health())
    assert data["services"]["orchestrator"] == "up"
    assert data["services"]["whisperx"] == "up"
    assert data["services"]["omnivoice"] == "up"
    assert data["services"]["ollama"] == "up"
    assert data["ready"] == data["total"] == 4
    assert data["gpu"] is None


def test_api_health_reports_down(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(api, "_gpu_info", lambda: None)
    with respx.mock:
        respx.get("http://127.0.0.1:8001/health").mock(side_effect=httpx.ConnectError("x"))
        respx.get("http://127.0.0.1:3900/health").mock(return_value=httpx.Response(200))
        respx.get("http://127.0.0.1:11434/api/tags").mock(return_value=httpx.Response(200))
        data = asyncio.run(api.api_health())
    assert data["services"]["whisperx"] == "down"
    assert data["ready"] < data["total"]


def test_api_health_gpu_info(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(api, "_gpu_info", lambda: {"name": "RTX 4090", "vram_used_mb": 1000, "vram_total_mb": 24564})
    with respx.mock:
        respx.get("http://127.0.0.1:8001/health").mock(return_value=httpx.Response(200))
        respx.get("http://127.0.0.1:3900/health").mock(return_value=httpx.Response(200))
        respx.get("http://127.0.0.1:11434/api/tags").mock(return_value=httpx.Response(200))
        data = asyncio.run(api.api_health())
    assert data["gpu"]["vram_total_mb"] == 24564
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_api_health.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'orchestrator.api' has no attribute '_HEALTH_CACHE'` / `api_health`.

- [ ] **Step 3: Implement the endpoint**

In `orchestrator/api.py`: add `import httpx` and `import subprocess` to the imports block (check they aren't already imported). Then add, near the other `@app.get` routes (e.g. after `get_status`):
```python
_HEALTH_CACHE = {"ts": 0.0, "data": None}
_HEALTH_TTL = 2.0


def _gpu_info():
    """Best-effort GPU name + VRAM via nvidia-smi. Returns None if unavailable."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0 and out.stdout.strip():
            name, used, total = [x.strip() for x in out.stdout.strip().splitlines()[0].split(",")]
            return {"name": name, "vram_used_mb": int(used), "vram_total_mb": int(total)}
    except Exception:
        pass
    return None


async def _ping(client: "httpx.AsyncClient", url: str) -> bool:
    try:
        r = await client.get(url, timeout=1.5)
        return r.status_code < 500
    except Exception:
        return False


@app.get("/api/health")
async def api_health():
    """Aggregate readiness of the sub-services + GPU. Always returns 200 (never blocks the UI)."""
    now = time.monotonic()
    if _HEALTH_CACHE["data"] and now - _HEALTH_CACHE["ts"] < _HEALTH_TTL:
        return _HEALTH_CACHE["data"]
    checks = {"whisperx": f"{settings.whisperx_api}/health"}
    if settings.tts_engine == "omnivoice":
        checks["omnivoice"] = f"{settings.omnivoice_api}/health"
    else:
        checks["tts"] = f"{settings.tts_api}/health"
    if settings.llm_backend == "ollama":
        checks["ollama"] = f"{settings.ollama_host}/api/tags"
    else:
        checks["vllm"] = f"{settings.vllm_host}/v1/models"
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[_ping(client, u) for u in checks.values()])
    services = {"orchestrator": "up"}
    for name, ok in zip(checks.keys(), results):
        services[name] = "up" if ok else "down"
    ready = sum(1 for v in services.values() if v == "up")
    data = {"services": services, "ready": ready, "total": len(services),
            "gpu": await asyncio.to_thread(_gpu_info)}
    _HEALTH_CACHE.update(ts=now, data=data)
    return data
```
Note: `time` is already imported in api.py (used by cleanup_loop). If not, add `import time`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_api_health.py -q -p no:cacheprovider`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `./venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider`
Expected: previous count + 3, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/api.py tests/test_api_health.py
git commit -m "feat(api): add GET /api/health aggregate service+GPU status"
```

---

### Task 2: Frontend header health badge (`SystemStatus.jsx`)

**Files:**
- Create: `frontend/src/components/SystemStatus.jsx`
- Modify: `frontend/src/App.jsx` (import + render `<SystemStatus />` in the header)
- Modify: `frontend/src/index.css` (badge styles — append a small block)

**Interfaces:**
- Consumes: `GET /api/health` (Task 1). API base: `import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'` (matches README / Electron webSecurity:false localhost calls).
- Produces: `<SystemStatus />` default export — self-contained; no props.

- [ ] **Step 1: Create the component**

Create `frontend/src/components/SystemStatus.jsx`:
```jsx
import React, { useEffect, useState } from 'react';

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
const LABELS = {
  orchestrator: 'Điều phối', whisperx: 'Nhận giọng (WhisperX)',
  omnivoice: 'Giọng đọc (OmniVoice)', tts: 'Giọng đọc (TTS)',
  ollama: 'Dịch (Ollama)', vllm: 'Dịch (vLLM)',
};

export default function SystemStatus() {
  const [health, setHealth] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch(`${API}/api/health`);
        const d = await r.json();
        if (alive) setHealth(d);
      } catch { if (alive) setHealth(null); }
    };
    tick();
    const id = setInterval(() => { if (!document.hidden) tick(); }, 10000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const ready = health?.ready ?? 0;
  const total = health?.total ?? 0;
  const allUp = health && ready === total;

  return (
    <div className="sysstatus">
      <button className={`sysstatus-badge ${allUp ? 'ok' : 'warn'}`} onClick={() => setOpen(o => !o)}>
        <span className="sysstatus-dot" />
        Hệ thống: {health ? `${ready}/${total} sẵn sàng` : 'đang kiểm tra…'}
      </button>
      {open && health && (
        <div className="sysstatus-panel">
          {Object.entries(health.services).map(([k, v]) => (
            <div key={k} className="sysstatus-row">
              <span className={`sysstatus-dot ${v === 'up' ? 'ok' : 'down'}`} />
              {LABELS[k] || k}: {v === 'up' ? 'sẵn sàng' : 'chưa lên'}
            </div>
          ))}
          {health.gpu && (
            <div className="sysstatus-gpu">
              {health.gpu.name} — VRAM {Math.round(health.gpu.vram_used_mb / 1024)}/
              {Math.round(health.gpu.vram_total_mb / 1024)} GB
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add styles**

Append to `frontend/src/index.css`:
```css
.sysstatus { position: relative; }
.sysstatus-badge { display: inline-flex; align-items: center; gap: 6px; border: none;
  border-radius: 999px; padding: 4px 12px; font-size: 13px; cursor: pointer; }
.sysstatus-badge.ok { background: #10321f; color: #4ade80; }
.sysstatus-badge.warn { background: #3a2a10; color: #fbbf24; }
.sysstatus-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.sysstatus-dot.ok { background: #4ade80; } .sysstatus-dot.down { background: #f87171; }
.sysstatus-panel { position: absolute; right: 0; top: 130%; z-index: 50; min-width: 240px;
  background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 10px; font-size: 13px; }
.sysstatus-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
.sysstatus-gpu { margin-top: 6px; padding-top: 6px; border-top: 1px solid #333; color: #9ca3af; }
```

- [ ] **Step 3: Wire into App.jsx header**

In `frontend/src/App.jsx`: add `import SystemStatus from './components/SystemStatus';` with the other component imports, and render `<SystemStatus />` inside the top header/toolbar element (place it next to the app title). Read the current header JSX first and insert it there.

- [ ] **Step 4: Lint + build to verify**

Run (from `frontend/`): `./node_modules/.bin/oxlint src/components/SystemStatus.jsx src/App.jsx`
Expected: no errors on the new file.
Run: `./node_modules/.bin/vite build`
Expected: `✓ built` with no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SystemStatus.jsx frontend/src/App.jsx frontend/src/index.css
git commit -m "feat(ui): system health badge polling /api/health"
```

---

### Task 3: Preflight checker (`preflight_check.ps1` + launcher)

**Files:**
- Create: `preflight_check.ps1`
- Create: `Kiem-tra-he-thong.bat`

**Interfaces:**
- Produces: `preflight_check.ps1 -Root <installDir>` → prints a colored PASS/FAIL/WARN report, writes `preflight_report.txt` next to itself, exits 0 (all pass) or 1 (any FAIL). WARN does not fail.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write `preflight_check.ps1`**

Create `preflight_check.ps1` (structure each check as a function returning `[pscustomobject]@{Name;Status;Msg}` where Status ∈ `PASS|WARN|FAIL`):
```powershell
param([string]$Root = $PSScriptRoot)
$ErrorActionPreference = 'Continue'
$results = New-Object System.Collections.ArrayList
function Add-Result($name, $status, $msg) { [void]$results.Add([pscustomobject]@{Name=$name;Status=$status;Msg=$msg}) }

# 1. OS
if ([Environment]::Is64BitOperatingSystem -and [Environment]::OSVersion.Version.Major -ge 10) {
    Add-Result "Hệ điều hành" "PASS" "Windows 64-bit"
} else { Add-Result "Hệ điều hành" "FAIL" "Cần Windows 10/11 64-bit" }

# 2. GPU + driver
$smi = (Get-Command nvidia-smi -ErrorAction SilentlyContinue).Source
if (-not $smi -and (Test-Path "$env:SystemRoot\System32\nvidia-smi.exe")) { $smi = "$env:SystemRoot\System32\nvidia-smi.exe" }
if (-not $smi) {
    Add-Result "GPU NVIDIA" "FAIL" "Không tìm thấy nvidia-smi — máy chưa có GPU NVIDIA hoặc chưa cài driver."
} else {
    $line = (& $smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
    if ($line) {
        $p = $line.Split(","); $name = $p[0].Trim(); $drv = $p[1].Trim(); $vram = [int]($p[2].Trim())
        Add-Result "GPU NVIDIA" "PASS" "$name (driver $drv)"
        if ([version]($drv) -lt [version]"452.39") { Add-Result "Driver GPU" "WARN" "Driver $drv có thể quá cũ cho CUDA 11.8 — nên cập nhật ≥ 452.39." }
        else { Add-Result "Driver GPU" "PASS" "driver $drv" }
        if ($vram -lt 16000) { Add-Result "VRAM" "FAIL" "$([math]::Round($vram/1024,1)) GB < 16 GB tối thiểu." }
        elseif ($vram -lt 24000) { Add-Result "VRAM" "PASS" "$([math]::Round($vram/1024,1)) GB — dùng VRAM_PROFILE=16gb." }
        else { Add-Result "VRAM" "PASS" "$([math]::Round($vram/1024,1)) GB — dùng VRAM_PROFILE=24gb." }
    } else { Add-Result "GPU NVIDIA" "FAIL" "nvidia-smi không trả dữ liệu." }
}

# 3. Disk
try {
    $drive = (Get-Item $Root).PSDrive.Name
    $free = (Get-PSDrive $drive).Free
    if ($free -ge 35GB) { Add-Result "Dung lượng đĩa" "PASS" ("{0:N0} GB trống trên ổ {1}:" -f ($free/1GB), $drive) }
    else { Add-Result "Dung lượng đĩa" "FAIL" ("Chỉ {0:N0} GB trống trên ổ {1}: — cần ≥ 35 GB." -f ($free/1GB), $drive) }
} catch { Add-Result "Dung lượng đĩa" "WARN" "Không đọc được dung lượng ổ đĩa." }

# 4. Ports
$listen = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty LocalPort -Unique)
foreach ($port in 8000,8001,9880,3900,11434,5173) {
    if ($listen -contains $port) { Add-Result "Cổng $port" "WARN" "Đang bị chiếm — có thể xung đột khi chạy." }
    else { Add-Result "Cổng $port" "PASS" "trống" }
}

# 5. Bundle integrity (only when -Root points at an installed bundle)
$req = @("venv\Scripts\python.exe","python-runtime\python.exe","frontend\dist\index.html",".env",
         "ollama\ollama.exe","models\whisper","models\omnivoice","models\ollama\models\blobs","Video Dubbing.exe")
$hasBundle = Test-Path (Join-Path $Root "Video Dubbing.exe")
if ($hasBundle) {
    foreach ($rel in $req) {
        if (Test-Path (Join-Path $Root $rel)) { Add-Result "Bundle: $rel" "PASS" "có" }
        else { Add-Result "Bundle: $rel" "FAIL" "THIẾU — bundle chưa đầy đủ." }
    }
    $ffprobe = Get-ChildItem (Join-Path $Root "ffmpeg_extracted") -Recurse -Filter ffprobe.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($ffprobe) { Add-Result "Bundle: ffprobe.exe" "PASS" "có" } else { Add-Result "Bundle: ffprobe.exe" "FAIL" "THIẾU ffprobe.exe" }
} else {
    Add-Result "Bundle" "WARN" "Chạy ngoài thư mục cài — bỏ qua kiểm tra toàn vẹn bundle."
}

# --- Report ---
$colors = @{PASS='Green';WARN='Yellow';FAIL='Red'}
Write-Host "`n==== KIỂM TRA HỆ THỐNG — VIDEO DUBBING ====`n" -ForegroundColor Cyan
foreach ($r in $results) {
    Write-Host ("[{0}] {1}: {2}" -f $r.Status, $r.Name, $r.Msg) -ForegroundColor $colors[$r.Status]
}
$fail = @($results | Where-Object { $_.Status -eq 'FAIL' }).Count
$warn = @($results | Where-Object { $_.Status -eq 'WARN' }).Count
Write-Host ""
if ($fail -eq 0) { Write-Host "==> SẴN SÀNG ($warn cảnh báo)." -ForegroundColor Green }
else { Write-Host "==> CHƯA ĐẠT: $fail lỗi cần khắc phục (xem [FAIL] ở trên)." -ForegroundColor Red }
$reportPath = Join-Path $PSScriptRoot "preflight_report.txt"
$results | ForEach-Object { "[{0}] {1}: {2}" -f $_.Status, $_.Name, $_.Msg } | Out-File $reportPath -Encoding utf8
Write-Host "Báo cáo đã lưu: $reportPath"
if ($fail -eq 0) { exit 0 } else { exit 1 }
```

- [ ] **Step 2: Write the launcher `Kiem-tra-he-thong.bat`**

Create `Kiem-tra-he-thong.bat`:
```bat
@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0preflight_check.ps1" -Root "%~dp0"
echo.
pause
```

- [ ] **Step 3: Parse-check the script**

Run: `powershell -NoProfile -Command "$e=$null;[System.Management.Automation.Language.Parser]::ParseFile('preflight_check.ps1',[ref]$null,[ref]$e)|Out-Null; if($e){$e|ForEach-Object{$_.Message}}else{'PARSE OK'}"`
Expected: `PARSE OK`.

- [ ] **Step 4: Dry-run on the source machine**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File preflight_check.ps1 -Root .`
Expected: prints the report; GPU/VRAM PASS on this machine; "Bundle" shows WARN (running outside an installed bundle, since source has no `Video Dubbing.exe`? it does — so it will check integrity; note whichever files are absent in the repo root will read FAIL — acceptable for a dry-run, the real target is an installed bundle). Confirm no PowerShell errors and `preflight_report.txt` is written.

- [ ] **Step 5: Commit**

```bash
git add preflight_check.ps1 Kiem-tra-he-thong.bat
git commit -m "feat(deploy): preflight system checker + launcher"
```

---

### Task 4: Electron splash service dashboard

**Files:**
- Modify: `electron/main.js` (collect GPU + per-service status, push to splash via IPC; keep opening main window only when orchestrator ready)
- Modify: `electron/splash.html` (render the 6-row checklist; receive updates)
- Modify: `electron/preload.js` (expose `onServiceStatus`, `openLogs`)

**Interfaces:**
- Consumes: `GET /api/health` (Task 1) for aggregate status; direct port checks as fallback.
- Produces: IPC channel `service-status` carrying `{gpu: 'ok'|'missing', services: {orchestrator, whisperx, tts|omnivoice, ollama, ...: 'connecting'|'up'|'down'}}`.

- [ ] **Step 1: Read the current files**

Read `electron/main.js` (the `waitForPort`, `startAllServices`, and splash-creation sections), `electron/splash.html`, `electron/preload.js` in full so the edits match existing structure (window var names, how the splash BrowserWindow is created).

- [ ] **Step 2: Add a status poller in `main.js`**

Add a function that, after services are spawned, polls `http://127.0.0.1:8000/api/health` every 1.5s and forwards the result to the splash window; also does a one-time `nvidia-smi` presence check. Send via `splashWindow.webContents.send('service-status', payload)`. Keep the existing `waitForPort(8000)` gate for opening the main window. Concretely, add:
```javascript
function pollHealthToSplash(splashWindow) {
  const http = require('http');
  let stopped = false;
  const gpuOk = require('child_process').spawnSync('nvidia-smi', ['-L'], { windowsHide: true }).status === 0;
  function tick() {
    if (stopped || !splashWindow || splashWindow.isDestroyed()) return;
    const req = http.request({ host: '127.0.0.1', port: 8000, path: '/api/health', timeout: 2000 }, (res) => {
      let body = '';
      res.on('data', (c) => (body += c));
      res.on('end', () => {
        let payload = { gpu: gpuOk ? 'ok' : 'missing', services: {} };
        try { payload.services = JSON.parse(body).services || {}; } catch {}
        if (!splashWindow.isDestroyed()) splashWindow.webContents.send('service-status', payload);
        if (!stopped) setTimeout(tick, 1500);
      });
    });
    req.on('error', () => { if (!splashWindow.isDestroyed()) splashWindow.webContents.send('service-status', { gpu: gpuOk ? 'ok' : 'missing', services: {} }); if (!stopped) setTimeout(tick, 1500); });
    req.end();
  }
  tick();
  return () => { stopped = true; };
}
```
Call `const stopPoll = pollHealthToSplash(splashWindow);` right after services are spawned, and call `stopPoll()` when the main window opens (after the `waitForPort` resolves). Also add an IPC handler `ipcMain.handle('open-logs', () => shell.openPath(path.join(PROJECT_ROOT, 'data')));`.

- [ ] **Step 3: Expose the API in `preload.js`**

In `electron/preload.js` add (keeping contextIsolation):
```javascript
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('vd', {
  onServiceStatus: (cb) => ipcRenderer.on('service-status', (_e, data) => cb(data)),
  openLogs: () => ipcRenderer.invoke('open-logs'),
});
```
(Merge with whatever preload already exposes — do not drop existing exposures.)

- [ ] **Step 4: Render the checklist in `splash.html`**

In `electron/splash.html` add a `<ul id="svc-list">` with rows for GPU, Ollama (LLM), WhisperX, TTS/OmniVoice, Orchestrator, and a script:
```html
<ul id="svc-list"></ul>
<button id="logs-btn" style="display:none" onclick="window.vd.openLogs()">Mở thư mục log</button>
<script>
  const ROWS = [['gpu','GPU'],['ollama','Dịch (Ollama)'],['whisperx','Nhận giọng'],
                ['omnivoice','Giọng đọc'],['orchestrator','Điều phối']];
  const icon = (s) => s === 'up' || s === 'ok' ? '✅' : s === 'down' || s === 'missing' ? '❌' : '⏳';
  let downTicks = 0;
  window.vd?.onServiceStatus((d) => {
    const st = Object.assign({ gpu: d.gpu }, d.services || {});
    document.getElementById('svc-list').innerHTML = ROWS.map(([k, label]) =>
      `<li>${icon(st[k] || 'connecting')} ${label}</li>`).join('');
    const anyDown = ROWS.some(([k]) => st[k] === 'down' || st[k] === 'missing');
    downTicks = anyDown ? downTicks + 1 : 0;
    document.getElementById('logs-btn').style.display = downTicks > 8 ? 'inline-block' : 'none';
  });
</script>
```
(Adapt selectors/markup to the existing splash.html layout; keep its styling.)

- [ ] **Step 5: Verify by launch (manual)**

Run the smoke-test launch (as used previously): start `Video Dubbing.exe`, watch the splash show ⏳→✅ per service, confirm the main window opens when orchestrator is ready, then kill the process tree. (Electron UI can't be unit-tested; this manual launch is the verification.)

- [ ] **Step 6: Commit**

```bash
git add electron/main.js electron/preload.js electron/splash.html
git commit -m "feat(electron): live service dashboard on splash via /api/health"
```

---

### Task 5: Vietnamese documentation set

**Files:**
- Create: `HUONG-DAN/QUICKSTART.txt`
- Create: `HUONG-DAN/01-CAI-DAT.md`
- Create: `HUONG-DAN/02-SU-DUNG.md`
- Create: `HUONG-DAN/03-XU-LY-SU-CO.md`

(ASCII folder/file names for bundle safety; Vietnamese content inside.)

**Interfaces:** none (documentation). Content must match the real UI (`frontend/src/App.jsx` labels), the `.env` table from `README.md`, ports/services from `config.py`, and the preflight/dashboard behavior built in Tasks 1–4.

- [ ] **Step 1: Write `QUICKSTART.txt`** — one printable page, 5 numbered steps: (1) chép `Setup.exe` + `app.7z` vào cùng một thư mục; (2) double-click `Setup.exe`, chọn nơi cài; (3) double-click **"Kiểm tra hệ thống"** (shortcut) — đọc kết quả, tất cả phải là [ĐẠT]; (4) double-click **"Video Dubbing"**; (5) đợi màn hình khởi động báo đủ 5/5 service → trình duyệt/cửa sổ mở. Ghi thời gian dự kiến (copy ~20 GB theo tốc độ ổ đĩa; cài vài phút; khởi động lần đầu ~1–2 phút).

- [ ] **Step 2: Write `01-CAI-DAT.md`** — sections: Yêu cầu phần cứng (bảng: GPU NVIDIA ≥16 GB VRAM, driver ≥452.39, 35 GB đĩa trống, Windows 10/11); Chuẩn bị (2 file cùng thư mục); Các bước cài chi tiết; Chạy preflight & đọc `preflight_report.txt`; Xử lý khi mỗi mục [LỖI] (không GPU/driver cũ/thiếu VRAM/đĩa đầy/port bận/bundle thiếu) — mỗi trường hợp 1 dòng cách khắc phục.

- [ ] **Step 3: Write `02-SU-DUNG.md`** — sections: Mở app & màn khởi động (giải thích dashboard 5/5); Thêm video (kéo-thả / thư mục `data/input`); Chọn cấu hình mỗi video (lồng tiếng đa/đơn giọng, OCR/xóa chữ blur|inpaint, lip-sync); Theo dõi pipeline (các bước M2→M10); Review & sửa bản dịch; Lấy kết quả (`data/output`, chọn thư mục xuất); badge "Hệ thống" ở header. Dùng đúng nhãn UI thực tế.

- [ ] **Step 4: Write `03-XU-LY-SU-CO.md`** — bảng Triệu chứng → Nguyên nhân → Cách sửa cho: thiếu/cũ driver; "CUDA out of memory" (đặt `VRAM_PROFILE=16gb` trong `.env`); cổng bận (đổi cổng / tắt tiến trình chiếm); model thiếu (bundle chưa đủ — chạy lại preflight); một service báo ❌ trên dashboard (mở log `data/*.log`); Ollama không thấy model (`OLLAMA_MODELS` sai). Ghi vị trí log: `data/orchestrator.log`, và cửa sổ console mỗi service.

- [ ] **Step 5: Review pass** — reread all four against the current UI/config; fix any label/port/path that doesn't match.

- [ ] **Step 6: Commit**

```bash
git add HUONG-DAN/
git commit -m "docs(deploy): Vietnamese install/usage/troubleshooting guides"
```

---

### Task 6: Stage preflight + docs into the bundle & installer

**Files:**
- Modify: `pack_full_bundle.ps1` (copy `preflight_check.ps1`, `Kiem-tra-he-thong.bat`, `HUONG-DAN/` into `$Stage`)
- Modify: `installer/installer.nsi` (ship the docs + `.bat`; Start-Menu shortcut "Kiểm tra hệ thống"; run preflight at end of install)

**Interfaces:** Consumes the files from Tasks 3 & 5. Produces a staged bundle + installer that include them.

- [ ] **Step 1: Extend `pack_full_bundle.ps1`**

In the "Config / voices / data" step of `pack_full_bundle.ps1`, add before the summary:
```powershell
# --- preflight + docs ---
Step "Preflight + tài liệu"
foreach ($f in @('preflight_check.ps1','Kiem-tra-he-thong.bat')) {
    if (Test-Path "$Src\$f") { Copy-Item "$Src\$f" "$Stage\$f" -Force; OK $f }
}
if (Test-Path "$Src\HUONG-DAN") { Mirror "$Src\HUONG-DAN" "$Stage\HUONG-DAN"; OK "HUONG-DAN" }
```

- [ ] **Step 2: Read `installer/installer.nsi`**

Read the full file to find where it extracts the payload, creates shortcuts, and finishes — so the additions match its structure (section names, `$INSTDIR`).

- [ ] **Step 3: Add shortcut + auto-run preflight in `installer.nsi`**

In the shortcuts section add (alongside the existing app shortcut):
```nsis
CreateShortCut "$SMPROGRAMS\Video Dubbing\Kiem tra he thong.lnk" "$INSTDIR\Kiem-tra-he-thong.bat" "" "$INSTDIR\icon.ico"
```
At the end of the install section (after extraction + pyvenv repair), auto-run the preflight so the user sees the report:
```nsis
ExecShell "open" "$INSTDIR\Kiem-tra-he-thong.bat"
```
(The `HUONG-DAN/` folder and the two script files are already inside `app.7z` from Task 6 Step 1, so no extra File directives are needed unless the .nsi lists payload contents explicitly — if it does, add them there.)

- [ ] **Step 4: Parse-check the .nsi (best-effort) and the pack script**

Run: `powershell -NoProfile -Command "$e=$null;[System.Management.Automation.Language.Parser]::ParseFile('pack_full_bundle.ps1',[ref]$null,[ref]$e)|Out-Null; if($e){$e|%{$_.Message}}else{'PACK PARSE OK'}"`
Expected: `PACK PARSE OK`. (NSIS has no offline linter here; verify the `.nsi` edits are syntactically consistent by inspection — real compile happens in the user-run build.)

- [ ] **Step 5: Commit**

```bash
git add pack_full_bundle.ps1 installer/installer.nsi
git commit -m "build(deploy): stage preflight + docs into bundle and installer"
```

---

## Delivery (user-run, not automated here)

The final artifact (`app.7z` ~20 GB + `Setup.exe`) and clean-machine validation require the user's resources and a second machine, so they are **not** part of the automated tasks above. After Tasks 1–6 land, the operator runs:
```powershell
.\build-electron.ps1
.\pack_full_bundle.ps1 -Stage "D:\VD-Stage"
.\build_installer.ps1 -Stage "D:\VD-Stage" -Out "D:\VD-Installer"
```
then copies `D:\VD-Installer\{Setup.exe,app.7z}` to a target machine, installs, runs "Kiểm tra hệ thống", launches, and confirms the splash reaches 5/5 and a video processes end-to-end. (I can run `build-electron.ps1` + `pack_full_bundle.ps1` on request if disk allows.)

## Self-Review

- **Spec coverage:** Preflight (Comp.1)→Task 3; splash dashboard (Comp.2a)→Task 4; `/api/health` (Comp.2c)→Task 1; UI badge (Comp.2b)→Task 2; docs (Comp.3)→Task 5; build integration (Comp.4)→Task 6; testing (Comp.5)→per-task tests + the delivery note. All spec sections mapped.
- **Placeholders:** none — every code step contains full code; doc steps enumerate exact sections/content (the doc prose is the deliverable, written at execution).
- **Type consistency:** `/api/health` shape (`services`/`ready`/`total`/`gpu`) is identical in Task 1 (producer), Task 2 (badge), Task 4 (splash poller). IPC channel `service-status` and preload API `window.vd.{onServiceStatus,openLogs}` match between Tasks 3/4. Service keys (`whisperx`,`omnivoice`|`tts`,`ollama`|`vllm`) consistent with `config.py`.
