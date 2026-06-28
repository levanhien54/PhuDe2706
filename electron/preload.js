'use strict';
/**
 * Preload script — exposes a minimal, typed API to the renderer process.
 * contextIsolation=true means renderer cannot access Node.js directly.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  quit:       ()  => ipcRenderer.invoke('app:quit'),
  getVersion: ()  => ipcRenderer.invoke('app:version'),
});
