'use strict';
/**
 * Preload script — exposes a minimal, typed API to the renderer process.
 * contextIsolation=true means renderer cannot access Node.js directly.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  quit:         ()  => ipcRenderer.invoke('app:quit'),
  getVersion:   ()  => ipcRenderer.invoke('app:version'),
  selectFolder: ()  => ipcRenderer.invoke('dialog:selectFolder'),
});

// Splash-screen service dashboard API (contextIsolation-safe).
contextBridge.exposeInMainWorld('vd', {
  onServiceStatus: (cb) => ipcRenderer.on('service-status', (_e, data) => cb(data)),
  openLogs: () => ipcRenderer.invoke('open-logs'),
});
