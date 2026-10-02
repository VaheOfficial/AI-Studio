// Replacing the app itself. A running app can't overwrite its own files (Windows locks the exe; a Mac bundle must
// be swapped whole), so the app downloads the new package, starts a small helper that outlives it, and quits; the
// helper waits for the app to be gone, puts the new one in its place and starts it. How that is done depends on
// how the app was installed:
//
//   Windows portable exe   a batch file moves the new exe over the old one and starts it
//   Windows installer      the new installer runs silently and restarts the app
//   macOS .app bundle      a shell script swaps the bundle (unpacked from the release's zip) and opens it
//   Linux AppImage         the file is replaced in place (Linux allows it) and started
import { execFile, spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const writable = (dir) => {
  try {
    fs.accessSync(dir, fs.constants.W_OK)
    return true
  } catch {
    return false
  }
}

/**
 * How this copy of the app can be replaced: `key` names its package in the release's `update.json`, `target` is
 * what gets replaced. Null when it can't replace itself (a run from source, a folder it may not write to, a Mac
 * app that macOS runs from a read-only copy because it was never moved out of the download folder).
 */
export function installKind(packaged) {
  if (!packaged) return null
  const arch = process.arch
  if (process.platform === 'win32') {
    const portable = process.env.PORTABLE_EXECUTABLE_FILE
    if (!portable) return { key: `win32-${arch}-setup`, target: null }
    return writable(path.dirname(portable)) ? { key: `win32-${arch}-portable`, target: portable } : null
  }
  if (process.platform === 'darwin') {
    const bundle = path.resolve(process.execPath, '..', '..', '..') // …/Grom AI Studio.app/Contents/MacOS/Grom AI Studio
    if (!bundle.endsWith('.app') || bundle.includes('/AppTranslocation/') || !writable(path.dirname(bundle))) return null
    return { key: `darwin-${arch}`, target: bundle }
  }
  const appImage = process.env.APPIMAGE
  return appImage && writable(path.dirname(appImage)) ? { key: `linux-${arch}`, target: appImage } : null
}

const detach = (file, args, options = {}) => spawn(file, args, { detached: true, stdio: 'ignore', windowsHide: true, ...options }).unref()

// Retries the move until the old exe is released (the portable launcher exits a moment after the app)
const WINDOWS_SWAP = `@echo off
set tries=0
:again
move /y "%~1" "%~2" >nul 2>&1 && goto start
set /a tries+=1
if %tries% geq 90 exit /b 1
ping -n 2 127.0.0.1 >nul
goto again
:start
start "" "%~2"
(goto) 2>nul & del "%~f0"
`

// $1: the app's process id, $2: the new bundle, $3: the installed bundle. Puts the old one back if the swap fails.
const MAC_SWAP = `#!/bin/sh
while kill -0 "$1" 2>/dev/null; do sleep 0.3; done
old="$3.previous"
rm -rf "$old"
if mv "$3" "$old" && mv "$2" "$3"; then
  rm -rf "$old"
  xattr -dr com.apple.quarantine "$3" 2>/dev/null
elif [ -d "$old" ] && [ ! -d "$3" ]; then
  mv "$old" "$3"
fi
open "$3"
rm -f "$0"
`

/**
 * Put the downloaded package `file` in place of this app and start it. Resolves once everything is prepared;
 * the caller then quits the app (the helpers wait for that).
 * @param {{ key: string, target: string | null }} kind from `installKind`
 */
export async function replaceApp(kind, file) {
  if (process.platform === 'win32') {
    if (!kind.target) {
      // The installer closes the app if it is still running, installs over it and starts it again
      detach(file, ['--updated', '/S', '--force-run'])
      return
    }
    const script = path.join(os.tmpdir(), `ai-studio-update-${process.pid}.cmd`)
    fs.writeFileSync(script, WINDOWS_SWAP.replace(/\n/g, '\r\n'))
    // One verbatim command line: cmd's own quoting rules mangle several quoted arguments otherwise
    detach('cmd.exe', ['/d', '/s', '/c', `""${script}" "${file}" "${kind.target}""`], { windowsVerbatimArguments: true })
    return
  }
  if (process.platform === 'darwin') {
    const staging = path.join(path.dirname(file), 'bundle')
    fs.rmSync(staging, { recursive: true, force: true })
    await new Promise((resolve, reject) => execFile('/usr/bin/ditto', ['-x', '-k', file, staging], (e) => (e ? reject(e) : resolve())))
    const bundle = fs.readdirSync(staging).find((name) => name.endsWith('.app'))
    if (!bundle) throw new Error('The update does not contain the app')
    const script = path.join(os.tmpdir(), `ai-studio-update-${process.pid}.sh`)
    fs.writeFileSync(script, MAC_SWAP, { mode: 0o700 })
    detach('/bin/sh', [script, String(process.pid), path.join(staging, bundle), kind.target])
    return
  }
  // Linux: a running AppImage can be replaced; rename within its folder so the swap is atomic
  const next = `${kind.target}.update`
  fs.copyFileSync(file, next)
  fs.chmodSync(next, 0o755)
  fs.renameSync(next, kind.target)
  detach('/bin/sh', ['-c', `while kill -0 ${process.pid} 2>/dev/null; do sleep 0.3; done; exec "$0"`, kind.target])
}
