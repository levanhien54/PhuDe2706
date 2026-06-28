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
  : path.dirname(process.execPath);           // prod: exe is AT project root

const PYTHON = process.platform === 'win32'
  ? path.join(PROJECT_ROOT, 'venv', 'Scripts', 'python.exe')
  : path.join(PROJECT_ROOT, 'venv', 'bin', 'python');

// In dev, frontend must be built first (frontend/dist/).
// In prod (asar), __dirname resolves inside the archive correctly.
const FRONTEND_DIST = path.join(__dirname, '..', 'frontend', 'dist');

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
  env.WHISPERX_API = 'http://127.0.0.1:8001';
  env.TTS_API      = 'http://127.0.0.1:9880';
  env.DEMUCS_API   = 'local';
  env.TTS_ENGINE   = env.TTS_ENGINE   || 'gpt_sovits';
  env.LLM_BACKEND  = env.LLM_BACKEND  || 'ollama';
  env.LLM_MODEL    = env.LLM_MODEL    || 'qwen2.5:14b';
  env.OLLAMA_HOST  = env.OLLAMA_HOST  || 'http://127.0.0.1:11434';
  return env;
}

// ─── Service management ───────────────────────────────────────────────────────

function startService(name, cwd, args) {
  const env = loadEnv();
  console.log(`[${name}] starting → ${PYTHON} ${args.join(' ')} (cwd: ${cwd})`);
  const proc = spawn(PYTHON, args, {
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

function startAllServices() {
  const root = PROJECT_ROOT;
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
    height: 300,
    frame: false,
    transparent: true,
    resizable: false,
    center: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  splashWin.loadFile(path.join(__dirname, 'splash.html'));
  return splashWin;
}

// ─── Main window ──────────────────────────────────────────────────────────────

function createMain() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    title: 'Video Dubbing',
    backgroundColor: '#0f172a',
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
    if (url.startsWith('http') || url.startsWith('https')) shell.openExternal(url);
    return { action: 'deny' };
  });

  // DevTools in dev mode
  if (IS_DEV) mainWindow.webContents.openDevTools({ mode: 'detach' });
}

// ─── System tray ─────────────────────────────────────────────────────────────

function buildTrayIcon() {
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
  if (!fs.existsSync(PYTHON)) {
    const msg = [
      `Không tìm thấy Python venv:\n${PYTHON}`,
      '',
      'Vui lòng chạy setup_native.ps1 trước khi mở ứng dụng.',
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

  try {
    await waitForPort(8000, 120_000);
    console.log('[Electron] Orchestrator ready on :8000');
  } catch (e) {
    console.error('[Electron]', e.message);
    // Services may still come up — open window anyway, UI will show errors
  }

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
