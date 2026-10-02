// Bridge between the window's pages and the main process. (CommonJS: sandboxed preloads can't be ES modules.)
// The splash screen gets start-up progress and its three buttons; the studio's pages get in-app updates. The main
// process checks which page a message comes from.
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('desktop', {
  onStatus: (handler) => ipcRenderer.on('desktop:status', (_event, status) => handler(status)),
  onError: (handler) => ipcRenderer.on('desktop:error', (_event, error) => handler(error)),
  retry: () => ipcRenderer.send('desktop:retry'),
  openLogs: () => ipcRenderer.send('desktop:open-logs'),
  quit: () => ipcRenderer.send('desktop:quit'),
  /** The app is up underneath the splash screen: { target: where the home page's mark is, wait: play through first }. */
  onReady: (handler) => ipcRenderer.on('desktop:ready', (_event, info) => handler(info)),
  /** The splash screen's mark has landed on the home page's. */
  landed: () => ipcRenderer.send('desktop:splash-landed'),
  /** The splash screen has left the window to the app. */
  done: () => ipcRenderer.send('desktop:splash-done'),
  /** For the app's page: the splash screen's mark has landed on the page's own. */
  onLanded: (handler) => ipcRenderer.once('desktop:landed', () => handler()),
  /** Something wants the user while the window is not in front: { title, body, tag, path }. */
  notify: (note) => ipcRenderer.send('desktop:notify', note),
  /** A notification was clicked: the in-app path it leads to. */
  onOpen: (handler) => ipcRenderer.on('desktop:open', (_event, path) => handler(path)),
  updates: {
    /** Ask the release feed; resolves with { enabled, current, latest, available, kind, size, needsInstaller, notes, state, error }. */
    check: () => ipcRenderer.invoke('desktop:updates:check'),
    /** Download and apply the newest update; the app restarts itself when it is ready. */
    install: () => ipcRenderer.invoke('desktop:updates:install'),
    /** The state changed without being asked (an app update could not be applied). Returns a function that stops listening. */
    onChanged: (handler) => {
      const listener = (_event, status) => handler(status)
      ipcRenderer.on('desktop:updates:changed', listener)
      return () => ipcRenderer.removeListener('desktop:updates:changed', listener)
    },
    /** Download progress, 0..1. Returns a function that stops listening. */
    onProgress: (handler) => {
      const listener = (_event, fraction) => handler(fraction)
      ipcRenderer.on('desktop:updates:progress', listener)
      return () => ipcRenderer.removeListener('desktop:updates:progress', listener)
    },
  },
})
