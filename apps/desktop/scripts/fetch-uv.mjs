// Downloads the pinned `uv` binary the desktop app ships with. On first launch the app uses it to create the
// server's Python environment, so the machine needs neither Python nor pip installed.
//
//   node scripts/fetch-uv.mjs                      this machine's platform and CPU
//   node scripts/fetch-uv.mjs darwin-arm64 ...     other targets (when packaging for them)
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const VERSION = '0.12.21'
// <node platform>-<node arch> → [release asset, sha256]
const ASSETS = {
  'win32-x64': ['uv-x86_64-pc-windows-msvc.zip', '5d223efa0bf00208c3853246af09420419dfbd352536aa6bb8163d6170e23890'],
  'win32-arm64': ['uv-aarch64-pc-windows-msvc.zip', '93ed53b94e9cec000cacdfd18ca67bc4cb2b6a5f5ec041edd7f2a3dae365ce79'],
  'darwin-arm64': ['uv-aarch64-apple-darwin.tar.gz', 'b88bda573e566ef9bced66b155fe0408626fbbc053aee1c30ba686f0728c9447'],
  'darwin-x64': ['uv-x86_64-apple-darwin.tar.gz', '2b336763b396ec6afa20c5a8b083538ca7402445b868311979d740a4344c17d8'],
  'linux-x64': ['uv-x86_64-unknown-linux-gnu.tar.gz', '23f02075b652bb1df64178cfae41b5caf160822e720e2663568f3f5d63bc52c0'],
  'linux-arm64': ['uv-aarch64-unknown-linux-gnu.tar.gz', '030b69227b40af8c1981b7301793dc66e71ed3c796ea8688209dd268bd91ec51'],
}

const vendor = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'vendor', 'uv')
// Windows ships bsdtar, which also reads zip; a `tar` found on PATH there may be Git's GNU tar, which doesn't
const tar = process.platform === 'win32' ? path.join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'tar.exe') : 'tar'

async function fetchTarget(target) {
  const entry = ASSETS[target]
  if (!entry) throw new Error(`No uv build for ${target} (known: ${Object.keys(ASSETS).join(', ')})`)
  const [asset, sha256] = entry
  const dir = path.join(vendor, target)
  const exe = path.join(dir, target.startsWith('win32') ? 'uv.exe' : 'uv')
  const marker = path.join(dir, '.version')
  if (fs.existsSync(exe) && fs.existsSync(marker) && fs.readFileSync(marker, 'utf8').trim() === VERSION) {
    console.log(`uv ${VERSION} for ${target}: already there`)
    return
  }
  const url = `https://github.com/astral-sh/uv/releases/download/${VERSION}/${asset}`
  console.log(`uv ${VERSION} for ${target}: downloading ${asset}`)
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`)
  const bytes = Buffer.from(await res.arrayBuffer())
  const got = createHash('sha256').update(bytes).digest('hex')
  if (got !== sha256) throw new Error(`${asset}: checksum mismatch (got ${got})`)
  fs.mkdirSync(dir, { recursive: true })
  const archive = path.join(dir, asset)
  fs.writeFileSync(archive, bytes)
  // The tar.gz archives hold one top-level folder; the Windows zips are flat
  execFileSync(tar, ['-xf', archive, '-C', dir, ...(asset.endsWith('.tar.gz') ? ['--strip-components=1'] : [])])
  fs.unlinkSync(archive)
  if (!fs.existsSync(exe)) throw new Error(`${asset} did not contain ${path.basename(exe)}`)
  if (!target.startsWith('win32')) fs.chmodSync(exe, 0o755)
  fs.writeFileSync(marker, VERSION)
}

const targets = process.argv.slice(2)
for (const target of targets.length ? targets : [`${process.platform}-${process.arch}`]) await fetchTarget(target)
