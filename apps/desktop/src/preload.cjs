// Bridge for the splash screen: start-up progress in, three buttons out. (CommonJS: sandboxed preloads can't be
// ES modules.) The main process ignores these messages unless they come from the splash page.
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('desktop', {
  onStatus: (handler) => ipcRenderer.on('desktop:status', (_event, status) => handler(status)),
  onError: (handler) => ipcRenderer.on('desktop:error', (_event, error) => handler(error)),
  retry: () => ipcRenderer.send('desktop:retry'),
  openLogs: () => ipcRenderer.send('desktop:open-logs'),
  quit: () => ipcRenderer.send('desktop:quit'),
})
