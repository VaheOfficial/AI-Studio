// AI Studio desktop shell. One window: it starts the local server (the same Python server as `pnpm server`), waits
// for it, and shows the web app that server serves. On first launch it builds the server's Python environment with
// the bundled `uv`, so the machine needs nothing installed. What the studio can do on the machine (GPU features,
// cloud-only areas) is decided by the server's capability report, not here.
import { app, BrowserWindow, ipcMain, session, shell } from 'electron'
import { execFile, spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const packaged = app.isPackaged
const repo = path.resolve(here, '..', '..', '..')
const isWin = process.platform === 'win32'
const SERVER_DIR = packaged ? path.join(process.resourcesPath, 'server') : path.join(repo, 'server')
const WEB_DIR = packaged ? path.join(process.resourcesPath, 'web') : path.join(repo, 'apps', 'studio', 'dist')
const PYTHON_VERSION = '3.13'
const DEV_SERVER = 'http://127.0.0.1:8765' // `pnpm server`: a dev run attaches to it instead of starting a second one
const STARTUP_TIMEOUT_MS = 240_000 // first start imports everything from a cold disk
const SHUTDOWN_GRACE_MS = 12_000

/** @type {BrowserWindow | null} */
let win = null
/** @type {import('node:child_process').ChildProcess | null} */
let server = null
let serverUrl = ''
let starting = false

/* ------------------------------- folders ------------------------------- */

/** The folder the app itself (portable exe, .app bundle, AppImage) sits in. */
function appFolder() {
  if (process.env.PORTABLE_EXECUTABLE_DIR) return process.env.PORTABLE_EXECUTABLE_DIR
  if (process.env.APPIMAGE) return path.dirname(process.env.APPIMAGE)
  // …/AI Studio.app/Contents/MacOS/AI Studio
  if (process.platform === 'darwin') return path.resolve(process.execPath, '..', '..', '..', '..')
  return path.dirname(process.execPath)
}

/**
 * Where models, chats, settings and the Python environment live. The Windows portable exe keeps them next to
 * itself; on any system a folder named "AI Studio Data" next to the app does the same (a USB stick, say).
 * Otherwise it is the per-user application data folder.
 */
function dataDir() {
  if (process.env.STUDIO_DATA_DIR) return path.resolve(process.env.STUDIO_DATA_DIR)
  if (!packaged) return path.join(repo, 'data')
  const beside = path.join(appFolder(), 'AI Studio Data')
  if (process.env.PORTABLE_EXECUTABLE_DIR || fs.existsSync(beside)) return beside
  return path.join(app.getPath('userData'), 'data')
}

const venvPython = (venv) => (isWin ? path.join(venv, 'Scripts', 'python.exe') : path.join(venv, 'bin', 'python'))
const logFile = (data) => path.join(data, 'logs', 'desktop.log')

function readText(file) {
  try {
    return fs.readFileSync(file, 'utf8').trim()
  } catch {
    return ''
  }
}

function logTail(data, lines = 14) {
  return readText(logFile(data)).split(/\r?\n/).slice(-lines).join('\n')
}

/* ------------------------------ processes ------------------------------ */

/**
 * PATH as the user's terminal has it. Apps started from Finder or a Linux launcher get a bare PATH, without
 * Homebrew and the like, so the server would not find git, ffmpeg or Ollama.
 */
function loginShellPath() {
  return new Promise((resolve) => {
    if (isWin) return resolve(null)
    const sh = process.env.SHELL || (process.platform === 'darwin' ? '/bin/zsh' : '/bin/bash')
    execFile(sh, ['-ilc', 'printf "__PATH__%s__PATH__" "$PATH"'], { timeout: 6000 }, (_err, stdout) => {
      const found = /__PATH__(.*?)__PATH__/s.exec(String(stdout ?? ''))
      resolve(found ? found[1] : null)
    })
  })
}

async function serverEnv(data) {
  const env = { ...process.env }
  const shellPath = await loginShellPath()
  if (shellPath) env.PATH = shellPath
  env.STUDIO_DATA_DIR = data
  env.STUDIO_WEB_DIR = WEB_DIR
  env.PYTHONUTF8 = '1'
  env.PYTHONUNBUFFERED = '1'
  // The packaged server folder may be read-only (a signed .app, a mounted AppImage)
  env.PYTHONPYCACHEPREFIX = path.join(data, 'cache', 'pycache')
  return env
}

/** Run a setup command to the end; its output goes to the log and its latest line to the splash screen. */
function run(file, args, env, data, status) {
  return new Promise((resolve, reject) => {
    fs.appendFileSync(logFile(data), `\n$ ${path.basename(file)} ${args.join(' ')}\n`)
    const child = spawn(file, args, { env, windowsHide: true })
    const onData = (chunk) => {
      const text = String(chunk)
      fs.appendFileSync(logFile(data), text)
      const line = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).pop()
      if (line) status(undefined, line.slice(0, 160))
    }
    child.stdout.on('data', onData)
    child.stderr.on('data', onData)
    child.on('error', reject)
    child.on('exit', (code) => (code === 0 ? resolve() : reject(new Error(`${path.basename(file)} ${args[0]} failed (exit ${code})`))))
  })
}

function uvBinary() {
  const name = isWin ? 'uv.exe' : 'uv'
  const file = packaged
    ? path.join(process.resourcesPath, 'uv', name)
    : path.join(here, '..', 'vendor', 'uv', `${process.platform}-${process.arch}`, name)
  if (!fs.existsSync(file)) {
    throw new Error(packaged ? 'This build is missing its bundled uv.' : 'uv is missing: run `pnpm --filter studio-desktop fetch-uv`.')
  }
  return file
}

/**
 * The Python that runs the server. A dev run uses the repo's own `server/.venv`; the packaged app builds one in
 * the data folder on first launch and again whenever the server's dependencies change.
 */
async function ensurePython(data, env, status) {
  const repoVenv = venvPython(path.join(SERVER_DIR, '.venv'))
  if (!packaged && !process.env.STUDIO_DESKTOP_BOOTSTRAP && fs.existsSync(repoVenv)) return repoVenv

  const venv = path.join(data, 'app', 'python')
  const python = venvPython(venv)
  const pyproject = path.join(SERVER_DIR, 'pyproject.toml')
  const want = createHash('sha256').update(fs.readFileSync(pyproject)).digest('hex')
  const stamp = path.join(venv, '.studio-deps')
  if (fs.existsSync(python) && readText(stamp) === want) return python

  const uv = uvBinary()
  const uvEnv = {
    ...env,
    UV_CACHE_DIR: path.join(data, 'cache', 'uv'),
    UV_PYTHON_INSTALL_DIR: path.join(data, 'envs', '.python'), // shared with the model runtimes' environments
    UV_PYTHON_PREFERENCE: 'only-managed', // never a system Python that an OS update could take away
    UV_NATIVE_TLS: '1', // verify downloads against the system certificate store
    UV_NO_PROGRESS: '1',
    NO_COLOR: '1',
  }
  if (!fs.existsSync(python)) {
    status('Setting up Python', `First launch only — downloading Python ${PYTHON_VERSION}`)
    await run(uv, ['venv', '--python', PYTHON_VERSION, venv], uvEnv, data, status)
  }
  status('Installing the server', 'First launch only — this takes a minute or two')
  await run(uv, ['pip', 'install', '--python', python, '-r', pyproject], uvEnv, data, status)
  fs.writeFileSync(stamp, want)
  return python
}

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer()
    probe.once('error', reject)
    probe.listen(0, '127.0.0.1', () => {
      const { port } = /** @type {import('node:net').AddressInfo} */ (probe.address())
      probe.close(() => resolve(port))
    })
  })
}

async function healthy(url) {
  try {
    const res = await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(2000) })
    return res.ok
  } catch {
    return false
  }
}

function killTree(pid) {
  try {
    if (isWin) spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { windowsHide: true })
    else process.kill(-pid, 'SIGKILL') // the server leads its own process group
  } catch {
    // already gone
  }
}

/** Start the server and resolve with its URL once it answers. */
async function startServer(status) {
  if (!packaged && !process.env.STUDIO_PORT && !process.env.STUDIO_DATA_DIR && (await healthy(DEV_SERVER))) return DEV_SERVER

  const data = dataDir()
  fs.mkdirSync(path.dirname(logFile(data)), { recursive: true })
  fs.appendFileSync(logFile(data), `\n--- ${new Date().toISOString()} AI Studio ${app.getVersion()} (${process.platform}-${process.arch}) ---\n`)
  if (!fs.existsSync(path.join(WEB_DIR, 'index.html'))) {
    throw new Error(packaged ? 'This build is missing the web app.' : 'The web app is not built: run `pnpm --filter studio build`.')
  }
  const env = await serverEnv(data)
  const python = await ensurePython(data, env, status)
  const port = process.env.STUDIO_PORT ? Number(process.env.STUDIO_PORT) : await freePort()
  const url = `http://127.0.0.1:${port}`

  status('Starting AI Studio', '')
  const out = fs.openSync(logFile(data), 'a')
  const child = spawn(python, ['-m', 'studio'], {
    cwd: SERVER_DIR,
    // The server shuts down when this stdin pipe closes, so it can't outlive the app (see studio/__main__.py)
    env: { ...env, STUDIO_PORT: String(port), STUDIO_WATCH_PARENT: '1' },
    stdio: ['pipe', out, out],
    windowsHide: true,
    detached: !isWin,
  })
  fs.closeSync(out)
  server = child
  child.on('exit', (code) => {
    if (server !== child) return // stopped on purpose
    server = null
    if (!starting) fail(new Error(`The server stopped unexpectedly (exit ${code}).`))
  })

  const deadline = Date.now() + STARTUP_TIMEOUT_MS
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`The server could not start (exit ${child.exitCode}).`)
    if (await healthy(url)) return url
    await new Promise((r) => setTimeout(r, 300))
  }
  throw new Error('The server did not answer in time.')
}

/** Ask the server to shut down (it saves running chats and stops its workers); kill it if it doesn't. */
function stopServer() {
  const child = server
  server = null
  if (!child || child.exitCode !== null) return Promise.resolve()
  return new Promise((resolve) => {
    const force = setTimeout(() => killTree(child.pid), SHUTDOWN_GRACE_MS)
    child.once('exit', () => {
      clearTimeout(force)
      resolve()
    })
    child.stdin?.end()
  })
}

/* -------------------------------- window ------------------------------- */

const isApp = (url) => !!serverUrl && (url === serverUrl || url.startsWith(`${serverUrl}/`))

function openExternal(url) {
  if (/^(https?|mailto):/i.test(url)) void shell.openExternal(url)
}

function status(title, detail) {
  win?.webContents.send('desktop:status', { title, detail })
}

function fail(err) {
  const data = dataDir()
  const show = () => win?.webContents.send('desktop:error', { message: err.message, log: logTail(data), logFile: logFile(data) })
  if (!win) return
  if (win.webContents.getURL().startsWith('file:')) show()
  else {
    serverUrl = ''
    void win.loadFile(path.join(here, 'splash.html')).then(show)
  }
}

async function boot() {
  if (starting) return
  starting = true
  try {
    status('Starting AI Studio', '')
    serverUrl = await startServer(status)
    await win?.loadURL(serverUrl)
  } catch (err) {
    await stopServer()
    fail(/** @type {Error} */ (err))
  } finally {
    starting = false
  }
}

function createWindow() {
  win = new BrowserWindow({
    width: 1480,
    height: 940,
    minWidth: 900,
    minHeight: 600,
    show: false,
    title: 'AI Studio',
    backgroundColor: '#060609', // the web app's --bg-0, so there is no white flash before it paints
    autoHideMenuBar: true,
    webPreferences: { preload: path.join(here, 'preload.cjs'), contextIsolation: true, sandbox: true },
  })
  win.once('ready-to-show', () => win?.show())
  win.on('closed', () => (win = null))
  // Links to the web open in the user's browser; the window only ever shows the studio
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isApp(url)) return { action: 'allow', overrideBrowserWindowOptions: { autoHideMenuBar: true } }
    openExternal(url)
    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', (event, url) => {
    if (isApp(url)) return
    event.preventDefault()
    openExternal(url)
  })
  void win.loadFile(path.join(here, 'splash.html')).then(boot)
}

// The splash screen's buttons (it is the only file: page this window ever loads)
const fromSplash = (event) => event.senderFrame?.url.startsWith('file:') ?? false
ipcMain.on('desktop:retry', (event) => fromSplash(event) && void boot())
ipcMain.on('desktop:open-logs', (event) => fromSplash(event) && void shell.openPath(path.dirname(logFile(dataDir()))))
ipcMain.on('desktop:quit', (event) => fromSplash(event) && app.quit())

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (!win) return
    if (win.isMinimized()) win.restore()
    win.focus()
  })

  void app.whenReady().then(() => {
    // Dictation and voice recording use the microphone; nothing outside the studio gets any permission
    const allowed = new Set(['media', 'clipboard-read', 'clipboard-sanitized-write', 'fullscreen', 'notifications'])
    session.defaultSession.setPermissionRequestHandler((wc, permission, done) => done(isApp(wc.getURL()) && allowed.has(permission)))
    session.defaultSession.setPermissionCheckHandler((_wc, permission, origin) => isApp(origin.replace(/\/$/, '')) && allowed.has(permission))
    createWindow()
  })

  // One window is the whole app: closing it quits, on macOS too, so no server keeps running unseen
  app.on('window-all-closed', () => app.quit())

  app.on('before-quit', (event) => {
    if (!server) return
    event.preventDefault()
    void stopServer().finally(() => app.quit())
  })
}
