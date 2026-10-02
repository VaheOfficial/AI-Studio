// Grom AI Studio desktop shell. One window: it starts the local server (the same Python server as `pnpm server`), waits
// for it, and shows the web app that server serves. On first launch it builds the server's Python environment with
// the bundled `uv`, so the machine needs nothing installed. What the studio can do on the machine (GPU features,
// cloud-only areas) is decided by the server's capability report, not here.
import { app, BrowserWindow, clipboard, ipcMain, Menu, Notification, screen, session, shell, WebContentsView } from 'electron'
import { execFile, spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { installKind, replaceApp } from './shell-update.js'
import { createUpdater } from './updates.js'

const here = path.dirname(fileURLToPath(import.meta.url))
const packaged = app.isPackaged
const repo = path.resolve(here, '..', '..', '..')
const isWin = process.platform === 'win32'
// The server and web app this build was installed with; a downloaded update takes their place (see updates.js)
const BUNDLED = {
  version: app.getVersion(),
  server: packaged ? path.join(process.resourcesPath, 'server') : path.join(repo, 'server'),
  web: packaged ? path.join(process.resourcesPath, 'web') : path.join(repo, 'apps', 'studio', 'dist'),
}
const SHELL = JSON.parse(fs.readFileSync(path.join(here, 'shell.json'), 'utf8'))
// Stamped into a build by scripts/shell-id.mjs; a run from source has none and never matches a release
const SHELL_ID = (() => {
  try {
    return String(JSON.parse(fs.readFileSync(path.join(here, 'shell-id.json'), 'utf8')).shell)
  } catch {
    return 'dev'
  }
})()
const INSTALL = installKind(packaged)
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
let python = '' // the interpreter running the server; also unpacks updates

/* ------------------------------- folders ------------------------------- */

/** The folder the app itself (portable exe, .app bundle, AppImage) sits in. */
function appFolder() {
  if (process.env.PORTABLE_EXECUTABLE_DIR) return process.env.PORTABLE_EXECUTABLE_DIR
  if (process.env.APPIMAGE) return path.dirname(process.env.APPIMAGE)
  // …/Grom AI Studio.app/Contents/MacOS/Grom AI Studio
  if (process.platform === 'darwin') return path.resolve(process.execPath, '..', '..', '..', '..')
  return path.dirname(process.execPath)
}

// Portable data folder names, newest first ("AI Studio Data" is from before the app was renamed)
const DATA_FOLDERS = ['Grom AI Studio Data', 'AI Studio Data']

/**
 * Where models, chats, settings and the Python environment live. The Windows portable exe keeps them next to
 * itself; on any system a folder named "Grom AI Studio Data" next to the app does the same (a USB stick, say).
 * Otherwise it is the per-user application data folder.
 */
function dataDir() {
  if (process.env.STUDIO_DATA_DIR) return path.resolve(process.env.STUDIO_DATA_DIR)
  if (!packaged) return path.join(repo, 'data')
  // A folder next to the app wins; the names the app has had are all recognised, so renaming it loses nothing
  const folder = appFolder()
  for (const name of DATA_FOLDERS) {
    if (fs.existsSync(path.join(folder, name))) return path.join(folder, name)
  }
  if (process.env.PORTABLE_EXECUTABLE_DIR) return path.join(folder, DATA_FOLDERS[0])
  const current = path.join(app.getPath('userData'), 'data')
  const earlier = path.join(app.getPath('appData'), 'AI Studio', 'data')
  return !fs.existsSync(current) && fs.existsSync(earlier) ? earlier : current
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

// Updates are for installed builds; a run from source uses the working tree. For trying a feed out,
// STUDIO_UPDATE_FEED turns them on and STUDIO_SHELL_ID stands in for the id a build would carry.
const updater = createUpdater({
  dataDir,
  bundled: BUNDLED,
  shell: process.env.STUDIO_SHELL_ID || SHELL_ID,
  install: INSTALL,
  feed: process.env.STUDIO_UPDATE_FEED || (packaged ? SHELL.updates : null),
  log: (line) => {
    try {
      fs.appendFileSync(logFile(dataDir()), `${line}\n`)
    } catch {
      // the log folder doesn't exist yet
    }
  },
})

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

async function serverEnv(data, bundle) {
  const env = { ...process.env }
  const shellPath = await loginShellPath()
  if (shellPath) env.PATH = shellPath
  env.STUDIO_DATA_DIR = data
  env.STUDIO_WEB_DIR = bundle.web
  env.STUDIO_BROWSER_CDP = `http://127.0.0.1:${BROWSER_PORT}` // the agent's browser is this app's (see below)
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
async function ensurePython(data, env, status, serverDir) {
  const repoVenv = venvPython(path.join(BUNDLED.server, '.venv'))
  if (!packaged && !process.env.STUDIO_DESKTOP_BOOTSTRAP && fs.existsSync(repoVenv)) return repoVenv

  const venv = path.join(data, 'app', 'python')
  const interpreter = venvPython(venv)
  const pyproject = path.join(serverDir, 'pyproject.toml')
  const want = createHash('sha256').update(fs.readFileSync(pyproject)).digest('hex')
  const stamp = path.join(venv, '.studio-deps')
  if (fs.existsSync(interpreter) && readText(stamp) === want) return interpreter

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
  const first = !fs.existsSync(interpreter)
  if (first) {
    status('Setting up Python', `First launch only — downloading Python ${PYTHON_VERSION}`)
    await run(uv, ['venv', '--python', PYTHON_VERSION, venv], uvEnv, data, status)
  }
  status('Installing the server', first ? 'First launch only — this takes a minute or two' : 'Updating its packages')
  await run(uv, ['pip', 'install', '--python', interpreter, '-r', pyproject], uvEnv, data, status)
  fs.writeFileSync(stamp, want)
  return interpreter
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
  updater.prune()
  const bundle = updater.active()
  const update = bundle.downloaded ? `, update ${bundle.version}` : ''
  fs.appendFileSync(logFile(data), `\n--- ${new Date().toISOString()} Grom AI Studio ${app.getVersion()}${update} (${process.platform}-${process.arch}) ---\n`)
  if (!fs.existsSync(path.join(bundle.web, 'index.html'))) {
    throw new Error(packaged ? 'This build is missing the web app.' : 'The web app is not built: run `pnpm --filter studio build`.')
  }
  const env = await serverEnv(data, bundle)
  python = await ensurePython(data, env, status, bundle.server)
  const port = process.env.STUDIO_PORT ? Number(process.env.STUDIO_PORT) : await freePort()
  const url = `http://127.0.0.1:${port}`

  status('Starting Grom AI Studio', '')
  const out = fs.openSync(logFile(data), 'a')
  const child = spawn(python, ['-m', 'studio'], {
    cwd: bundle.server,
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

/* --------------------------- the agent's browser -------------------------- */

// The agent browses in this app's own browser. Its pages are drawn without a window (Electron's offscreen
// rendering): real pages of a real browser that are never a window on any system, so there is nothing to hide
// from the user and nothing of the kind a headless browser gives away to sites. They live in a session of their
// own, apart from the app's cookies and storage. The server drives them over the DevTools protocol, which the app
// opens on a local port for it (STUDIO_BROWSER_CDP). A page cannot be created from outside, so one page stays open
// as the anchor: the server opens each chat's page from it (window.open), and everything opened inside this
// session becomes another windowless page. The user sees a page through the app's browser panel, never directly.
const AGENT_SESSION = 'persist:agent-browser'
const AGENT_PAGE = {
  show: false,
  width: 1280,
  height: 800,
  webPreferences: { offscreen: true, partition: AGENT_SESSION, sandbox: true, contextIsolation: true },
}
const BROWSER_PORT = await freePort()

function startAgentBrowser() {
  const agent = session.fromPartition(AGENT_SESSION)
  // Pages the agent visits get no camera, microphone, location or notifications, and save nothing to disk
  agent.setPermissionRequestHandler((_contents, _permission, done) => done(false))
  agent.setPermissionCheckHandler(() => false)
  agent.on('will-download', (event) => event.preventDefault())
  app.on('web-contents-created', (_event, contents) => {
    if (contents.session === agent) contents.setWindowOpenHandler(() => ({ action: 'allow', overrideBrowserWindowOptions: AGENT_PAGE }))
  })
  // The title is how the server finds this page (browser.py ANCHOR_TITLE)
  void new BrowserWindow(AGENT_PAGE).loadURL('data:text/html,<title>grom-agent-browser</title>')
}

/* -------------------------------- window ------------------------------- */

const isApp = (url) => !!serverUrl && (url === serverUrl || url.startsWith(`${serverUrl}/`))

function openExternal(url) {
  if (/^(https?|mailto):/i.test(url)) void shell.openExternal(url)
}

// The splash screen is a view of its own, laid over the window. The web app loads underneath it; once the app is
// up, the splash moves its mark onto the home page's and lets the page show through, so one becomes the other
// without a cut.
/** @type {WebContentsView | null} */
let splash = null
/** @type {Promise<void> | null} */
let splashLoaded = null

function fitSplash() {
  if (!splash || !win) return
  const [width, height] = win.getContentSize()
  splash.setBounds({ x: 0, y: 0, width, height })
}

/** Puts the splash screen over the window, unless it is there already. Resolves once its page has loaded. */
function showSplash() {
  if (!win) return Promise.resolve()
  if (splash && splashLoaded) return splashLoaded
  const view = new WebContentsView({ webPreferences: { preload: path.join(here, 'preload.cjs'), contextIsolation: true, sandbox: true } })
  splash = view
  view.setBackgroundColor('#00000000') // the page paints its own background, and takes it away to leave
  win.contentView.addChildView(view)
  fitSplash()
  view.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  view.webContents.on('will-navigate', (event) => event.preventDefault())
  view.webContents.on('did-finish-load', applyZoom)
  splashLoaded = view.webContents.loadFile(path.join(here, 'splash.html'))
  return splashLoaded
}

function hideSplash() {
  if (!splash) return
  const view = splash
  splash = null
  splashLoaded = null
  if (win && !win.isDestroyed()) {
    win.contentView.removeChildView(view)
    win.webContents.focus()
  }
  view.webContents.close()
}

function status(title, detail) {
  splash?.webContents.send('desktop:status', { title, detail })
}

function fail(err) {
  const data = dataDir()
  serverUrl = ''
  void showSplash().then(() => splash?.webContents.send('desktop:error', { message: err.message, log: logTail(data), logFile: logFile(data) }))
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// The home page's own mark, where the splash screen's mark comes to rest
const FIND_MARK = `(() => {
  const mark = document.querySelector('[data-launch-mark] svg')
  if (!mark) return null
  const box = mark.getBoundingClientRect()
  return box.width ? { x: box.left, y: box.top, width: box.width, height: box.height } : null
})()`

/** Where the home page's mark is, once it has stopped moving (the page's entrance carries it for a moment). */
async function findMark() {
  let last = null
  for (let tries = 0; tries < 40 && win && !win.isDestroyed(); tries++) {
    const box = await win.webContents.executeJavaScript(FIND_MARK).catch(() => null)
    if (box && last && Math.abs(box.x - last.x) < 0.5 && Math.abs(box.y - last.y) < 0.5 && Math.abs(box.width - last.width) < 0.5) return box
    last = box
    await delay(120)
  }
  return null
}

// On every launch the splash screen plays its opening sequence through once before it leaves, however quickly
// the server comes up (STUDIO_SKIP_SPLASH=1: it leaves as soon as the app is ready). It says itself when it has
// gone; the limit is for a window that is not being drawn (minimized, hidden) and so never gets there.
const SPLASH_LIMIT = 12000
let launched = false

/** The app is up under the splash screen: tell the splash, wait for it to leave, take it away. */
async function handOver() {
  if (!splash) return
  const target = await findMark()
  if (!splash) return
  const gone = new Promise((resolve) => {
    const done = (event) => fromSplash(event) && finish()
    const finish = () => {
      clearTimeout(limit)
      ipcMain.removeListener('desktop:splash-done', done)
      resolve(undefined)
    }
    const limit = setTimeout(finish, SPLASH_LIMIT)
    ipcMain.on('desktop:splash-done', done)
  })
  splash.webContents.send('desktop:ready', { target, wait: !launched && !process.env.STUDIO_SKIP_SPLASH })
  launched = true
  await gone
  hideSplash()
}

async function boot() {
  if (starting) return
  starting = true
  try {
    status('Starting Grom AI Studio', '')
    serverUrl = await startServer(status)
    // "#launch" tells the home page it opens under the splash screen (see the web app's lib/desktop.ts)
    await win?.loadURL(`${serverUrl}/#launch`)
    await handOver()
  } catch (err) {
    await stopServer()
    if (updater.active().downloaded) {
      // A downloaded update that can't start must not lock the user out: go back to the installed version
      fs.appendFileSync(logFile(dataDir()), `update could not start (${/** @type {Error} */ (err).message}); using the installed version\n`)
      updater.discard()
      starting = false
      return boot()
    }
    fail(/** @type {Error} */ (err))
  } finally {
    starting = false
  }
}

/** An app update is downloaded: hand over to the helper that swaps the app, and quit (see shell-update.js). */
async function replaceSelf() {
  try {
    await replaceApp(INSTALL, updater.pending())
    app.quit()
  } catch (err) {
    updater.failed(/** @type {Error} */ (err).message)
    win?.webContents.send('desktop:updates:changed', updater.status())
  }
}

/** Stop the server and start again from the splash screen (after an update was installed). */
async function restart() {
  if (starting) return
  serverUrl = ''
  await showSplash()
  status('Restarting with the update', '')
  await stopServer()
  await boot()
}

/* ------------------------------ size and zoom ----------------------------- */

// The interface is drawn for a screen of about 1920 x 1080 logical pixels. Larger screens get everything scaled up
// to match, by whichever side has less room (a 4K screen at 100% scaling: 2x; at 150% scaling: 1.33x; an ultrawide
// 5120 x 1440: 1.33x, since its height is what limits it). Ctrl with + / - / 0 or the mouse wheel adjusts from
// there in steps the app remembers.
const DESIGN_WIDTH = 1920
const DESIGN_HEIGHT = 1040 // 1080 less a taskbar: sizes are those of the work area
const ZOOM_STEP = 1.1
let zoomSteps = 0

const clamp = (n, low, high) => Math.min(high, Math.max(low, n))
const windowPrefs = () => path.join(dataDir(), 'app', 'window.json')

function loadZoom() {
  try {
    zoomSteps = clamp(Math.round(Number(JSON.parse(fs.readFileSync(windowPrefs(), 'utf8')).zoomSteps) || 0), -8, 12)
  } catch {
    zoomSteps = 0
  }
}

function autoZoom() {
  const display = win ? screen.getDisplayMatching(win.getBounds()) : screen.getPrimaryDisplay()
  const { width, height } = display.workAreaSize
  return clamp(Math.min(width / DESIGN_WIDTH, height / DESIGN_HEIGHT), 1, 2.25)
}

function applyZoom() {
  if (!win || win.isDestroyed()) return
  const factor = clamp(autoZoom() * ZOOM_STEP ** zoomSteps, 0.5, 4)
  win.webContents.setZoomFactor(factor)
  // The splash screen at the same scale: it lands its mark on a spot measured in the app's page
  splash?.webContents.setZoomFactor(factor)
}

/** `delta`: +1 / -1 for one step in or out, 0 to go back to the automatic size. */
function zoomBy(delta) {
  zoomSteps = delta === 0 ? 0 : clamp(zoomSteps + delta, -8, 12)
  applyZoom()
  try {
    fs.mkdirSync(path.dirname(windowPrefs()), { recursive: true })
    fs.writeFileSync(windowPrefs(), JSON.stringify({ zoomSteps }))
  } catch {
    // the zoom still applies for this run
  }
}

/**
 * The right-click menu. Electron shows none of its own, so a right click did nothing but select the word under it.
 * What it offers depends on what was clicked: corrections for a misspelled word, what can be done with a link or a
 * picture, and the editing commands that apply.
 */
function contextMenu(contents, params) {
  /** @type {Electron.MenuItemConstructorOptions[]} */
  const items = []
  const group = (...entries) => {
    if (items.length) items.push({ type: 'separator' })
    items.push(...entries)
  }
  if (params.misspelledWord) {
    const fixes = params.dictionarySuggestions.slice(0, 6)
    group(
      ...(fixes.length ? fixes.map((word) => ({ label: word, click: () => contents.replaceMisspelling(word) })) : [{ label: 'No suggestions', enabled: false }]),
      { label: 'Add to dictionary', click: () => contents.session.addWordToSpellCheckerDictionary(params.misspelledWord) },
    )
  }
  if (params.linkURL && !isApp(params.linkURL)) {
    group(
      { label: 'Open link in browser', click: () => openExternal(params.linkURL) },
      { label: 'Copy link address', click: () => clipboard.writeText(params.linkURL) },
    )
  }
  if (params.mediaType === 'image') {
    group(
      { label: 'Copy image', click: () => contents.copyImageAt(params.x, params.y) },
      { label: 'Save image as…', click: () => contents.downloadURL(params.srcURL) },
    )
  }
  const can = params.editFlags
  if (params.isEditable) {
    group(
      { role: 'undo', enabled: can.canUndo },
      { role: 'redo', enabled: can.canRedo },
      { type: 'separator' },
      { role: 'cut', enabled: can.canCut },
      { role: 'copy', enabled: can.canCopy },
      { role: 'paste', enabled: can.canPaste },
      { role: 'selectAll', enabled: can.canSelectAll },
    )
  } else if (params.selectionText.trim()) {
    group({ role: 'copy' }, { role: 'selectAll' })
  }
  if (items.length) Menu.buildFromTemplate(items).popup({ window: win ?? undefined })
}

// A packaged app carries its icon in the executable. Run from the source tree, the window would show Electron's
// own, so it is given the artwork the packages are built from.
const DEV_ICON = path.join(here, '..', 'build', 'icon.png')
const devIcon = !packaged && fs.existsSync(DEV_ICON) ? DEV_ICON : null

function createWindow() {
  // Most of the screen, whatever its size; on an ultrawide one, no wider than 16:9
  const area = screen.getPrimaryDisplay().workAreaSize
  const height = Math.round(clamp(area.height * 0.88, 700, area.height))
  loadZoom()
  win = new BrowserWindow({
    width: Math.round(clamp(Math.min(area.width * 0.82, (height * 16) / 9), 1100, area.width)),
    height,
    minWidth: 900,
    minHeight: 600,
    show: false,
    title: 'Grom AI Studio',
    backgroundColor: '#080808', // the web app's --bg-0, so there is no white flash before it paints
    autoHideMenuBar: true,
    ...(devIcon ? { icon: devIcon } : {}),
    webPreferences: { preload: path.join(here, 'preload.cjs'), contextIsolation: true, sandbox: true },
  })
  // The window is the whole app: closing it quits, on macOS too, so no server keeps running unseen. (The agent's
  // windowless pages are windows to Electron, so "all windows closed" never comes.)
  win.on('closed', () => {
    win = null
    app.quit()
  })
  win.on('resize', fitSplash)
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
  // Zoom: set again on every load (it is kept per address, and the server's port changes between runs) and
  // when the window lands on another screen
  win.webContents.on('did-finish-load', applyZoom)
  win.on('moved', applyZoom)
  win.webContents.on('zoom-changed', (_event, direction) => zoomBy(direction === 'in' ? 1 : -1)) // Ctrl + wheel
  win.webContents.on('context-menu', (_event, params) => win && contextMenu(win.webContents, params))
  win.webContents.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown' || !(input.control || input.meta) || input.alt) return
    const delta = { '=': 1, '+': 1, '-': -1, _: -1, 0: 0 }[input.key]
    if (delta === undefined) return
    event.preventDefault()
    zoomBy(delta)
  })
  // The window appears with the splash screen in it; the app loads behind that
  void showSplash()
    .catch(() => {})
    .then(() => {
      win?.show()
      return boot()
    })
}

// The splash screen's mark has come down on the home page's: the page shows its own from here
ipcMain.on('desktop:splash-landed', (event) => fromSplash(event) && win?.webContents.send('desktop:landed'))

// The splash screen's buttons (it is the only file: page the app ever loads)
const fromSplash = (event) => event.senderFrame?.url.startsWith('file:') ?? false
ipcMain.on('desktop:retry', (event) => fromSplash(event) && void boot())
ipcMain.on('desktop:open-logs', (event) => fromSplash(event) && void shell.openPath(path.dirname(logFile(dataDir()))))
ipcMain.on('desktop:quit', (event) => fromSplash(event) && app.quit())

const fromApp = (event) => isApp(event.senderFrame?.url ?? '')

// The app wants the user while its window is not in front (the agent asks something, waits for an approval, or
// finished a long piece of work): a system notification, and the taskbar button flashes (the dock icon bounces)
// until the window is looked at. A click brings the window forward on the chat the note is about.
const notes = new Map() // by tag: a newer note about the same thing replaces the older one (and none is collected)
function comeForward() {
  if (!win || win.isDestroyed()) return
  if (win.isMinimized()) win.restore()
  win.show()
  win.focus()
}
ipcMain.on('desktop:notify', (event, note) => {
  if (!fromApp(event) || !win || win.isDestroyed()) return
  if (win.isFocused() && !win.isMinimized()) return
  const title = String(note?.title ?? '').slice(0, 120)
  if (!title) return
  const tag = String(note?.tag ?? title)
  const target = typeof note?.path === 'string' && note.path.startsWith('/') ? note.path : null
  notes.get(tag)?.close()
  if (Notification.isSupported()) {
    const shown = new Notification({ title, body: String(note?.body ?? '').slice(0, 300), ...(devIcon ? { icon: devIcon } : {}) })
    shown.on('click', () => {
      comeForward()
      if (target) win?.webContents.send('desktop:open', target)
    })
    shown.on('close', () => notes.get(tag) === shown && notes.delete(tag))
    notes.set(tag, shown)
    shown.show()
  }
  if (process.platform === 'darwin') app.dock?.bounce('informational')
  else {
    win.flashFrame(true)
    win.once('focus', () => win?.flashFrame(false))
  }
})

// Updates, driven from the studio's Settings page (only the studio's own pages may ask)
ipcMain.handle('desktop:updates:check', (event) => (fromApp(event) ? updater.check() : null))
ipcMain.handle('desktop:updates:install', async (event) => {
  if (!fromApp(event)) return null
  const result = await updater.install(python, (fraction) => win?.webContents.send('desktop:updates:progress', fraction))
  // Let the page show "restarting" first
  if (result.state === 'ready') setTimeout(() => void (result.kind === 'app' ? replaceSelf() : restart()), 400)
  return result
})

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (!win) return
    if (win.isMinimized()) win.restore()
    win.focus()
  })

  // Windows groups taskbar buttons by this id and shows the window's icon for it rather than the executable's
  if (process.platform === 'win32') app.setAppUserModelId('com.grom.aistudio')
  // Where the server reaches the agent's browser; has to be said before the app is ready
  app.commandLine.appendSwitch('remote-debugging-port', String(BROWSER_PORT))

  void app.whenReady().then(() => {
    if (devIcon && process.platform === 'darwin') app.dock?.setIcon(devIcon)
    // Dictation and voice recording use the microphone; nothing outside the studio gets any permission
    const allowed = new Set(['media', 'clipboard-read', 'clipboard-sanitized-write', 'fullscreen', 'notifications'])
    session.defaultSession.setPermissionRequestHandler((wc, permission, done) => done(isApp(wc.getURL()) && allowed.has(permission)))
    session.defaultSession.setPermissionCheckHandler((_wc, permission, origin) => isApp(origin.replace(/\/$/, '')) && allowed.has(permission))
    startAgentBrowser()
    createWindow()
  })


  app.on('before-quit', (event) => {
    if (!server) return
    event.preventDefault()
    void stopServer().finally(() => app.quit())
  })
}
