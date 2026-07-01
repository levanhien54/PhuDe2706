'use strict';
/**
 * Electron main process — Video Dubbing Desktop App
 *
 * Lifecycle:
 *   1. Show splash screen
 *   2. Spawn Python services (orchestrator:8000, whisperx:8001, tts:9880)
 *   3. Poll until orchestrator responds
 *   4. Close splash, open main window (Chromium loading frontend/dist)
 *   5. On quit: kill all child processes
 *
 * PROJECT_ROOT resolution:
 *   dev  → dirname(__dirname)           (project root)
 *   prod → dirname(process.execPath)    (exe sits in project root)
 */

const { app, BrowserWindow, Tray, Menu, nativeImage, shell, dialog, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path  = require('path');
const fs    = require('fs');
const http  = require('http');
const os    = require('os');

// ─── Path resolution ────────────────────────────────────────────────────────

const IS_DEV = !app.isPackaged;

const PROJECT_ROOT = IS_DEV
  ? path.join(__dirname, '..')                // dev: electron/ → project root
  : (process.env.PORTABLE_EXECUTABLE_DIR     // portable EXE: builder sets this to the EXE's folder
    || path.dirname(process.execPath));       // fallback: exe location

// ─── Deployed-bundle self-healing ─────────────────────────────────────────────
// In a deployed bundle a full Python 3.10 runtime is shipped as PROJECT_ROOT/python-runtime so the
// target needs no system Python. venv/Scripts/python.exe (used for OmniVoice) and the venv stdlib
// are located via venv/pyvenv.cfg's "home", which was written with the BUILD machine's absolute path
// and does not exist on the target. Repoint it at the bundled runtime so the venv interpreter finds
// python310.dll + the stdlib. No-op in dev (no python-runtime/), idempotent (skips if already right).
function repairVenvConfig() {
  try {
    const runtime = path.join(PROJECT_ROOT, 'python-runtime');
    const cfg = path.join(PROJECT_ROOT, 'venv', 'pyvenv.cfg');
    if (!fs.existsSync(path.join(runtime, 'python.exe')) || !fs.existsSync(cfg)) return;
    const txt = fs.readFileSync(cfg, 'utf-8');
    const want = `home = ${runtime}`;
    if (txt.split(/\r?\n/).some(l => l.trim() === want)) return;   // already correct
    fs.writeFileSync(cfg, txt.replace(/home\s*=.*/m, want), 'utf-8');
    console.log(`[Electron] venv pyvenv.cfg home -> ${runtime}`);
  } catch (e) {
    console.error('[Electron] repairVenvConfig:', e.message);
  }
}
repairVenvConfig();

// The runtime interpreter MUST match the venv's Python minor version — venv site-packages hold
// cp3XX binary extensions (av, torch, ctranslate2) that ABI-lock to it. Prefer a matching SYSTEM
// python (dodges a shm.dll loader bug in venv's python.exe); else fall back to the venv python.
// Override with PYTHON_EXE. Deliberately does NOT consult PATH (a stray wrong-minor python there
// would load against the cp310 site-packages and crash on import).
function venvPythonVersion() {
  try {
    const cfg = fs.readFileSync(path.join(PROJECT_ROOT, 'venv', 'pyvenv.cfg'), 'utf-8');
    const m = cfg.match(/version\s*=\s*(\d+\.\d+)/);
    if (m) return m[1].replace('.', '');   // "3.10" -> "310"
  } catch { /* fall through to default */ }
  return '310';
}
function resolveSystemPython() {
  const venvPy = process.platform === 'win32'
    ? path.join(PROJECT_ROOT, 'venv', 'Scripts', 'python.exe')
    : path.join(PROJECT_ROOT, 'venv', 'bin', 'python');
  if (process.platform !== 'win32') return venvPy;
  if (process.env.PYTHON_EXE && fs.existsSync(process.env.PYTHON_EXE)) return process.env.PYTHON_EXE;
  // Deployed bundle ships a full Python 3.10 runtime next to the EXE. Prefer it: it is a clean
  // interpreter (not the venv launcher, so it dodges the shm.dll bug) and is ABI-correct (3.10.x).
  const bundled = path.join(PROJECT_ROOT, 'python-runtime', 'python.exe');
  if (fs.existsSync(bundled)) return bundled;
  const ver = venvPythonVersion();
  const localPrograms = path.join(os.homedir(), 'AppData', 'Local', 'Programs', 'Python');
  for (const c of [path.join(localPrograms, `Python${ver}`, 'python.exe'), path.join('C:\\', `Python${ver}`, 'python.exe')]) {
    if (fs.existsSync(c)) return c;
  }
  return venvPy;   // ABI-correct (matches site-packages) even if it may hit the shm.dll bug
}
const PYTHON = resolveSystemPython();

// OmniVoice is launched with the venv interpreter (mirrors run_native.ps1, which runs it
// cleanly) rather than system Python.
const VENV_PYTHON = process.platform === 'win32'
  ? path.join(PROJECT_ROOT, 'venv', 'Scripts', 'python.exe')
  : path.join(PROJECT_ROOT, 'venv', 'bin', 'python');

// In dev, use __dirname to find frontend/dist.
// In prod, frontend/dist lives on-disk next to the exe, so use PROJECT_ROOT.
const FRONTEND_DIST = IS_DEV
  ? path.join(__dirname, '..', 'frontend', 'dist')
  : path.join(PROJECT_ROOT, 'frontend', 'dist');

// ─── State ───────────────────────────────────────────────────────────────────

let mainWindow  = null;
let splashWin   = null;
let tray        = null;
const services  = [];   // { name, proc }
let isQuitting  = false;

// ─── Environment loader ───────────────────────────────────────────────────────

function loadEnv() {
  const env   = { ...process.env, PYTHONUNBUFFERED: '1', PYTHONDONTWRITEBYTECODE: '1' };
  const envFile = path.join(PROJECT_ROOT, '.env');
  if (fs.existsSync(envFile)) {
    for (const raw of fs.readFileSync(envFile, 'utf-8').split(/\r?\n/)) {
      const m = raw.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)/);
      if (!m) continue;
      env[m[1]] = m[2].trim().replace(/^["']|["']$/g, '');
    }
  }
  // Override with known-local values
  env.WHISPERX_API      = 'http://127.0.0.1:8001';
  env.TTS_API           = 'http://127.0.0.1:9880';
  env.DEMUCS_API        = 'local';
  env.TTS_ENGINE        = env.TTS_ENGINE   || 'omnivoice';
  env.LLM_BACKEND       = env.LLM_BACKEND  || 'ollama';
  env.LLM_MODEL         = env.LLM_MODEL    || 'qwen2.5:14b';
  env.OLLAMA_HOST       = env.OLLAMA_HOST  || 'http://127.0.0.1:11434';
  env.DATA_DIR          = path.join(PROJECT_ROOT, 'data');
  env.GPT_SOVITS_DIR    = path.join(PROJECT_ROOT, 'GPT-SoVITS');
  // Absolute model dir — the service resolves a relative path against its own CWD otherwise.
  // Base 646-lang model (preferred over the VN fine-tune in A/B testing). To use the fine-tune,
  // point this at models/omnivoice-vi.
  env.OMNIVOICE_MODEL_DIR = path.join(PROJECT_ROOT, 'models', 'omnivoice');
  // PYTHONPATH: venv site-packages + GPT-SoVITS paths (required by system python)
  const venvSite = path.join(PROJECT_ROOT, 'venv', 'Lib', 'site-packages');
  const gptSoVITS = path.join(PROJECT_ROOT, 'GPT-SoVITS');
  env.PYTHONPATH        = [venvSite, gptSoVITS, path.join(gptSoVITS, 'GPT_SoVITS')].join(path.delimiter);
  env.PYTHONIOENCODING  = 'utf-8';
  env.PYTHONUTF8        = '1';
  // Intel-Fortran/MKL (torch/omnivoice) aborts with "forrtl: error (200)" on a console CLOSE/CTRL
  // event; disable that handler so the Python services survive.
  env.FOR_DISABLE_CONSOLE_CTRL_HANDLER = '1';
  env.WHISPER_PRELOAD   = env.WHISPER_PRELOAD || '0';
  // Absolute model dirs (a relative path in .env resolves against each service's own CWD — e.g.
  // whisperx-service/ — and misses the shipped weights). Point them at the bundled models/.
  env.WHISPER_MODEL_DIR   = path.join(PROJECT_ROOT, 'models', 'whisper');
  env.OMNIVOICE_MODEL_DIR = path.join(PROJECT_ROOT, 'models', 'omnivoice');
  // Bundled binaries so a clean target (no system FFmpeg / Ollama) resolves them: prepend the
  // FFmpeg bin (has ffmpeg.exe + ffprobe.exe), the project root, and the Ollama dir to PATH, and
  // point Ollama at the shipped model store.
  const ffmpegBin = path.join(PROJECT_ROOT, 'ffmpeg_extracted', 'ffmpeg-master-latest-win64-gpl', 'bin');
  const ollamaDir = path.join(PROJECT_ROOT, 'ollama');
  const pathParts = [PROJECT_ROOT];
  if (fs.existsSync(ffmpegBin)) pathParts.push(ffmpegBin);
  if (fs.existsSync(ollamaDir)) pathParts.push(ollamaDir);
  env.PATH = [...pathParts, env.PATH || ''].join(path.delimiter);
  env.OLLAMA_MODELS = path.join(PROJECT_ROOT, 'models', 'ollama', 'models');
  return env;
}

// ─── Service management ───────────────────────────────────────────────────────

function startService(name, cwd, args, pythonBin) {
  const env = loadEnv();
  const bin = pythonBin || PYTHON;
  console.log(`[${name}] starting → ${bin} ${args.join(' ')} (cwd: ${cwd})`);
  const proc = spawn(bin, args, {
    cwd,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  proc.stdout.on('data', d => process.stdout.write(`[${name}] ${d}`));
  proc.stderr.on('data', d => process.stderr.write(`[${name}] ${d}`));
  proc.on('exit',  code  => console.log(`[${name}] exit ${code}`));
  proc.on('error', err   => console.error(`[${name}] error: ${err.message}`));
  services.push({ name, proc });
  return proc;
}

// Ollama (translation LLM) — the orchestrator calls it at OLLAMA_HOST but does NOT launch it, so we
// start `ollama serve` ourselves from the bundled binary (clean target has no system Ollama). Prefer
// PROJECT_ROOT/ollama/ollama.exe; fall back to a system install. If a server is already up on 11434
// this second one just fails to bind and the running one serves — harmless.
function startOllama() {
  const env = loadEnv();
  const bundled = path.join(PROJECT_ROOT, 'ollama', 'ollama.exe');
  const system  = path.join(os.homedir(), 'AppData', 'Local', 'Programs', 'Ollama', 'ollama.exe');
  const exe = fs.existsSync(bundled) ? bundled : (fs.existsSync(system) ? system : null);
  if (!exe) { console.error('[ollama] ollama.exe not found (bundled or system) — translation will fail'); return; }
  console.log(`[ollama] starting → ${exe} serve (OLLAMA_MODELS=${env.OLLAMA_MODELS})`);
  const proc = spawn(exe, ['serve'], { cwd: PROJECT_ROOT, env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
  proc.stdout.on('data', d => process.stdout.write(`[ollama] ${d}`));
  proc.stderr.on('data', d => process.stderr.write(`[ollama] ${d}`));
  proc.on('exit',  code  => console.log(`[ollama] exit ${code}`));
  proc.on('error', err   => console.error(`[ollama] error: ${err.message}`));
  services.push({ name: 'ollama', proc });
}

function startAllServices() {
  const root = PROJECT_ROOT;
  startOllama();
  startService('orchestrator', root, [
    '-m', 'uvicorn', 'orchestrator.api:app',
    '--host', '127.0.0.1', '--port', '8000',
    '--log-level', 'warning',
  ]);
  startService('whisperx', path.join(root, 'whisperx-service'), [
    '-m', 'uvicorn', 'app:app',
    '--host', '127.0.0.1', '--port', '8001',
    '--log-level', 'warning',
  ]);
  startService('tts', path.join(root, 'tts-service'), [
    '-m', 'uvicorn', 'app:app',
    '--host', '127.0.0.1', '--port', '9880',
    '--log-level', 'warning',
  ]);
  // OmniVoice TTS (default engine in .env). Lazy-loads its model on first request,
  // so starting it here costs no VRAM until a dub actually synthesizes audio.
  startService('omnivoice', path.join(root, 'omnivoice-service'), [
    '-m', 'uvicorn', 'app:app',
    '--host', '127.0.0.1', '--port', '3900',
    '--log-level', 'warning',
  ], VENV_PYTHON);
}

function killAllServices() {
  for (const { name, proc } of services) {
    console.log(`[Electron] stopping ${name}`);
    try {
      if (process.platform === 'win32') {
        spawn('taskkill', ['/pid', proc.pid.toString(), '/f', '/t'], { windowsHide: true });
      } else {
        proc.kill('SIGTERM');
      }
    } catch (e) {
      console.error(`[Electron] kill ${name}:`, e.message);
    }
  }
}

// ─── Health check ─────────────────────────────────────────────────────────────

// Polls the orchestrator's /api/health every 1.5s and forwards the aggregate status to the
// splash window so it can render a live per-service checklist. Also does a one-time nvidia-smi
// presence check (GPU row). Returns a stop function; call it once the main window opens so the
// splash (now destroyed) is not written to and no timers leak.
function pollHealthToSplash(splashWindow) {
  let stopped = false;
  // Async GPU presence check so we never block the main/UI thread during startup.
  let gpuOk = false;
  require('child_process').execFile('nvidia-smi', ['-L'], { windowsHide: true }, (err) => { gpuOk = !err; });
  function tick() {
    if (stopped || !splashWindow || splashWindow.isDestroyed()) return;
    let scheduled = false;
    const scheduleNext = () => { if (!scheduled) { scheduled = true; if (!stopped) setTimeout(tick, 1500); } };
    const req = http.request({ host: '127.0.0.1', port: 8000, path: '/api/health', timeout: 2000 }, (res) => {
      let body = '';
      res.on('data', (c) => (body += c));
      res.on('end', () => {
        let payload = { gpu: gpuOk ? 'ok' : 'missing', services: {} };
        try { payload.services = JSON.parse(body).services || {}; } catch {}
        if (!splashWindow.isDestroyed()) splashWindow.webContents.send('service-status', payload);
        scheduleNext();
      });
    });
    // The `timeout` option alone only emits an event; it never aborts the request. Without this a
    // connected-but-slow orchestrator (busy loading models) would hang the request forever and the
    // poll loop would stop rescheduling. Destroying with an error routes into the handler below.
    req.on('timeout', () => req.destroy(new Error('health poll timeout')));
    // On any failure the orchestrator is unreachable; send an empty services map (the splash keeps
    // showing ⏳ rather than a harsh ❌ during the brief pre-bind window). The splash treats a
    // persistently-not-up orchestrator as a down-tick so the "open logs" affordance still appears.
    req.on('error', () => {
      if (!splashWindow.isDestroyed()) splashWindow.webContents.send('service-status', { gpu: gpuOk ? 'ok' : 'missing', services: {} });
      scheduleNext();
    });
    req.end();
  }
  tick();
  return () => { stopped = true; };
}

function waitForPort(port, timeoutMs = 90_000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;

    function attempt() {
      const req = http.request(
        { host: '127.0.0.1', port, path: '/api/jobs', method: 'GET' },
        () => resolve()
      );
      req.setTimeout(2000, () => { req.destroy(); retry(); });
      req.on('error', retry);
      req.end();
    }

    function retry() {
      if (Date.now() > deadline) return reject(new Error(`Port ${port} not ready after ${timeoutMs / 1000}s`));
      setTimeout(attempt, 1500);
    }

    // Small initial delay so the process has time to bind
    setTimeout(attempt, 3000);
  });
}

// ─── Splash window ────────────────────────────────────────────────────────────

function createSplash() {
  splashWin = new BrowserWindow({
    width: 480,
    height: 420,
    frame: false,
    transparent: true,
    resizable: false,
    center: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  splashWin.loadFile(path.join(__dirname, 'splash.html'));
  return splashWin;
}

// ─── Main window ──────────────────────────────────────────────────────────────

function createMain() {
  const iconPath = path.join(PROJECT_ROOT, 'icon.ico');
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    title: 'Video Dubbing',
    backgroundColor: '#0f172a',
    icon: fs.existsSync(iconPath) ? iconPath : undefined,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,         // allow file:// origin to call http://localhost
      allowRunningInsecureContent: true,
    },
  });

  const index = path.join(FRONTEND_DIST, 'index.html');
  if (fs.existsSync(index)) {
    mainWindow.loadFile(index);
  } else {
    mainWindow.loadURL('data:text/html,<body style="background:#0f172a;color:#e2e8f0;font-family:sans-serif;padding:40px"><h2>⚠️ Frontend chưa được build</h2><p>Chạy: <code>build-electron.ps1</code> hoặc <code>cd frontend && npm run build</code></p></body>');
  }

  mainWindow.once('ready-to-show', () => {
    if (splashWin && !splashWin.isDestroyed()) splashWin.destroy();
    mainWindow.show();
    mainWindow.focus();
  });

  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();  // minimize to tray instead of closing
    }
  });

  mainWindow.on('closed', () => { mainWindow = null; });

  // Open external links in default browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    // Check the parsed scheme (not a string prefix): startsWith('http') also matched
    // 'httpfoo://...' and forwarded arbitrary schemes to the OS handler.
    try {
      const { protocol } = new URL(url);
      if (protocol === 'http:' || protocol === 'https:') shell.openExternal(url);
    } catch { /* invalid URL — deny */ }
    return { action: 'deny' };
  });

  // DevTools in dev mode
  if (IS_DEV) mainWindow.webContents.openDevTools({ mode: 'detach' });
}

// ─── System tray ─────────────────────────────────────────────────────────────

function buildTrayIcon() {
  const iconPath = path.join(PROJECT_ROOT, 'icon.ico');
  if (fs.existsSync(iconPath)) {
    try {
      return nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });
    } catch { /* fall through */ }
  }
  // Minimal 16×16 blue-purple PNG as fallback
  const b64 = 'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAABmJLR0QA/wD/AP+gvaeTAAAATklEQVQ4jWNgGAWkAkYGBob/DAwMJGsm1wBSDWBiIFUzBQYwMJCsmVwDSDWAiYFUzRQYwMBAsmZyDSDVACYGUjVTYAADA8maKTCAFAAAGwkCfzEzqhsAAAAASUVORK5CYII=';
  try {
    return nativeImage.createFromDataURL(`data:image/png;base64,${b64}`);
  } catch {
    return nativeImage.createEmpty();
  }
}

function createTray() {
  tray = new Tray(buildTrayIcon());
  const menu = Menu.buildFromTemplate([
    {
      label: 'Mở Video Dubbing',
      click: () => {
        if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
        else createMain();
      },
    },
    { type: 'separator' },
    {
      label: 'Thoát',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);
  tray.setToolTip('Video Dubbing — AI Dubbing System');
  tray.setContextMenu(menu);
  tray.on('double-click', () => {
    if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
    else createMain();
  });
}

// ─── Setup check ─────────────────────────────────────────────────────────────

function checkSetup() {
  // The venv site-packages must exist (services import from it via PYTHONPATH),
  // regardless of which interpreter PYTHON resolved to.
  const venvSite = process.platform === 'win32'
    ? path.join(PROJECT_ROOT, 'venv', 'Lib', 'site-packages')
    : path.join(PROJECT_ROOT, 'venv', 'lib');
  if (!fs.existsSync(PYTHON) || !fs.existsSync(venvSite)) {
    const msg = [
      'Không tìm thấy môi trường Python (venv) đầy đủ:',
      `  Python        : ${PYTHON}`,
      `  Site-packages : ${venvSite}`,
      '',
      'Vui lòng chạy setup_native.ps1 (hoặc setup_offline.ps1) trước khi mở ứng dụng.',
    ].join('\n');
    dialog.showErrorBox('Chưa cài đặt môi trường', msg);
    return false;
  }
  return true;
}

// ─── App lifecycle ────────────────────────────────────────────────────────────

app.setAppUserModelId('com.videodubbing.app');

app.whenReady().then(async () => {
  if (!checkSetup()) { app.quit(); return; }

  createTray();
  createSplash();
  startAllServices();
  const stopPoll = pollHealthToSplash(splashWin);

  try {
    await waitForPort(8000, 120_000);
    console.log('[Electron] Orchestrator ready on :8000');
  } catch (e) {
    console.error('[Electron]', e.message);
    // Services may still come up — open window anyway, UI will show errors
  }

  stopPoll();
  createMain();
});

// Keep app alive when all windows are closed (tray mode)
app.on('window-all-closed', () => {
  if (process.platform === 'darwin') app.quit();
  // On Windows/Linux: stay in tray
});

app.on('activate', () => {
  if (!mainWindow) createMain();
  else mainWindow.show();
});

app.on('before-quit', () => {
  isQuitting = true;
  killAllServices();
});

// IPC handlers
ipcMain.handle('app:quit', () => { isQuitting = true; app.quit(); });
ipcMain.handle('app:version', () => app.getVersion());
ipcMain.handle('dialog:selectFolder', async () => {
  const res = await dialog.showOpenDialog(mainWindow, {
    title: 'Chọn thư mục theo dõi video',
    properties: ['openDirectory'],
  });
  return res.canceled || !res.filePaths.length ? null : res.filePaths[0];
});
ipcMain.handle('open-logs', () => shell.openPath(path.join(PROJECT_ROOT, 'data')));
