// In-app updates. A release carries two things for installed apps, described by its `update.json`:
//
// - an update bundle: the server's source and the built web app (a couple of MB; everything the studio is, except
//   the shell around it). The app unpacks it into its data folder and runs from there instead of from the files it
//   was installed with. Nothing executable changes, so this works for every kind of install.
// - the packages themselves (portable exe, installer, Mac zip, AppImage), for when the shell changed too: Electron,
//   the main-process code, the bundled uv. Then the app replaces itself (see shell-update.js).
//
// Which one applies is decided by the shell id (scripts/shell-id.mjs): the same id as the release means the bundle
// fits this shell; a different one means the app has to be replaced.
import { execFile } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

const CHECK_TIMEOUT_MS = 10_000

/** -1, 0 or 1 for two dotted versions ("0.9.0" < "0.10.0"). */
export function compareVersions(a, b) {
  const pa = String(a).split('.').map((n) => parseInt(n, 10) || 0)
  const pb = String(b).split('.').map((n) => parseInt(n, 10) || 0)
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0)
    if (d) return d < 0 ? -1 : 1
  }
  return 0
}

const hasBundle = (dir) => fs.existsSync(path.join(dir, 'server', 'studio', '__main__.py')) && fs.existsSync(path.join(dir, 'web', 'index.html'))
const isFile = (f) => !!f && typeof f.url === 'string' && /^[0-9a-f]{64}$/.test(f.sha256) && Number.isInteger(f.size)

/**
 * @param {{ dataDir: () => string, bundled: { version: string, server: string, web: string }, shell: string,
 *           install: { key: string, target: string | null } | null, feed: string | null,
 *           log: (line: string) => void }} options
 *   `install`: how this app can replace itself (shell-update.js), null when it can't.
 *   `feed`: null turns updates off (a run from source).
 */
export function createUpdater({ dataDir, bundled, shell, install: installKind, feed, log }) {
  const root = () => path.join(dataDir(), 'app', 'update')
  const pointer = () => path.join(root(), 'current.json')
  /** @type {{ version: string, shell: string, url: string, sha256: string, size: number, notes?: string,
   *           packages?: Record<string, { url: string, sha256: string, size: number }> } | null} */
  let manifest = null
  let state = 'idle'
  let error = null
  /** The downloaded package of an app update, ready to be put in place. */
  let pendingApp = null

  /** What the app runs: the downloaded bundle when it is newer than the installed files, else those. */
  function active() {
    try {
      const { version } = JSON.parse(fs.readFileSync(pointer(), 'utf8'))
      const dir = path.join(root(), String(version))
      if (/^[\w.-]+$/.test(String(version)) && compareVersions(version, bundled.version) > 0 && hasBundle(dir)) {
        return { version: String(version), server: path.join(dir, 'server'), web: path.join(dir, 'web'), downloaded: true }
      }
    } catch {
      // no download, or an unreadable pointer: the installed files
    }
    return { ...bundled, downloaded: false }
  }

  /** Remove what is no longer used: old bundles and downloaded packages (call while the server is not running). */
  function prune() {
    const keep = active()
    let names = []
    try {
      names = fs.readdirSync(root())
    } catch {
      return
    }
    for (const name of names) {
      if (keep.downloaded && (name === keep.version || name === 'current.json')) continue
      fs.rmSync(path.join(root(), name), { recursive: true, force: true })
    }
  }

  /** Forget the downloaded bundle (it failed to start); the installed files take over again. */
  function discard() {
    fs.rmSync(pointer(), { force: true })
  }

  /** What the newest release means for this app: nothing, a bundle to unpack, the app to replace, or a manual download. */
  function plan() {
    if (!manifest || compareVersions(manifest.version, active().version) <= 0) return { kind: null, file: null }
    if (manifest.shell === shell) return { kind: 'content', file: manifest }
    const pkg = installKind ? manifest.packages?.[installKind.key] : null
    return isFile(pkg) && trusted(pkg.url) ? { kind: 'app', file: pkg } : { kind: 'manual', file: null }
  }

  function status() {
    const { kind, file } = plan()
    return {
      enabled: !!feed,
      current: active().version,
      latest: manifest?.version ?? null,
      available: kind === 'content' || kind === 'app',
      /** 'content': applied in place. 'app': the app itself is replaced and restarted. */
      kind: kind === 'manual' ? null : kind,
      size: file?.size ?? null,
      // A newer release this app can't apply on its own: only a fresh download brings it
      needsInstaller: kind === 'manual',
      notes: manifest?.notes ?? null,
      state,
      error,
    }
  }

  /** Downloads must come from where the feed lives: the same repository's releases on GitHub, else the same origin. */
  function trusted(url) {
    try {
      const u = new URL(url)
      const f = new URL(feed)
      if (u.origin !== f.origin) return false
      if (f.hostname !== 'github.com') return true
      const repo = f.pathname.split('/').slice(1, 3).join('/')
      return u.protocol === 'https:' && u.pathname.startsWith(`/${repo}/releases/download/`)
    } catch {
      return false
    }
  }

  async function check() {
    if (!feed || state === 'downloading') return status()
    state = 'checking'
    error = null
    try {
      const res = await fetch(feed, { signal: AbortSignal.timeout(CHECK_TIMEOUT_MS), cache: 'no-store' })
      if (!res.ok) throw new Error(`The update feed answered ${res.status}`)
      const m = await res.json()
      const valid = typeof m.version === 'string' && /^\d+(\.\d+){1,3}$/.test(m.version) && typeof m.shell === 'string'
        && isFile(m) && trusted(m.url) && (m.packages == null || typeof m.packages === 'object')
      if (!valid) throw new Error('The update feed is not in the expected format')
      manifest = m
    } catch (err) {
      error = err.name === 'TimeoutError' ? 'Could not reach the update feed' : err.message
      log(`update check failed: ${error}`)
    }
    state = 'idle'
    return status()
  }

  /** Download `file` to `dest`, checking size and SHA-256. */
  async function download(file, dest, onProgress) {
    fs.mkdirSync(path.dirname(dest), { recursive: true })
    const res = await fetch(file.url)
    if (!res.ok || !res.body) throw new Error(`The download answered ${res.status}`)
    const hash = createHash('sha256')
    const out = fs.createWriteStream(dest)
    let received = 0
    try {
      for await (const chunk of res.body) {
        hash.update(chunk)
        received += chunk.length
        if (received > file.size) throw new Error('The download is larger than the release says')
        if (!out.write(chunk)) await new Promise((r) => out.once('drain', r))
        onProgress(received / file.size)
      }
    } finally {
      await new Promise((resolve) => out.end(resolve))
    }
    if (received !== file.size || hash.digest('hex') !== file.sha256) throw new Error('The download does not match its checksum')
  }

  /**
   * Download the newest release's update. A bundle is unpacked with the app's own Python and the caller restarts
   * the server; for an app update the package waits in `pending()` and the caller replaces the app.
   */
  async function install(python, onProgress) {
    const { kind, file } = plan()
    if (!file || state === 'downloading') return status()
    const version = manifest.version
    state = 'downloading'
    error = null
    const scratch = []
    try {
      if (kind === 'app') {
        const dest = path.join(root(), 'app', path.basename(new URL(file.url).pathname))
        fs.rmSync(path.dirname(dest), { recursive: true, force: true })
        await download(file, dest, onProgress)
        pendingApp = dest
      } else {
        const zip = path.join(root(), 'download.zip')
        const staging = path.join(root(), `${version}.partial`)
        const target = path.join(root(), version)
        scratch.push(zip, staging)
        await download(file, zip, onProgress)
        fs.rmSync(staging, { recursive: true, force: true })
        await new Promise((resolve, reject) =>
          execFile(python, ['-m', 'zipfile', '-e', zip, staging], { windowsHide: true }, (e) => (e ? reject(e) : resolve())),
        )
        if (!hasBundle(staging)) throw new Error('The update is missing files')
        fs.rmSync(target, { recursive: true, force: true })
        fs.renameSync(staging, target)
        fs.writeFileSync(pointer(), JSON.stringify({ version }))
      }
      log(`update ${version} downloaded (${kind})`)
      state = 'ready'
    } catch (err) {
      error = err.message
      state = 'idle'
      log(`update ${version} failed: ${error}`)
    } finally {
      for (const leftover of scratch) fs.rmSync(leftover, { recursive: true, force: true })
    }
    return { ...status(), kind: state === 'ready' ? kind : status().kind }
  }

  /** The app update failed to apply: back to idle with the reason. */
  function failed(message) {
    pendingApp = null
    state = 'idle'
    error = message
    log(`app update failed: ${message}`)
  }

  return { active, prune, discard, status, check, install, pending: () => pendingApp, failed }
}
