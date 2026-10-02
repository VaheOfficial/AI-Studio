// The shell's identity: a hash over everything a release bakes into the installed app and an in-place update
// cannot change — the Electron main-process sources, the Electron version, the bundled uv and the packaging
// config. Two builds with the same id can exchange update bundles; a different id means the app itself has to be
// replaced (see ../src/updates.js).
//
//   node scripts/shell-id.mjs            print the id
//   node scripts/shell-id.mjs --stamp    also write it to src/shell-id.json, which the packaged app reads
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const desktop = path.join(path.dirname(fileURLToPath(import.meta.url)), '..')
const STAMP = 'shell-id.json'

const hash = createHash('sha256')
// Line endings differ between checkouts (Windows runners check out CRLF); the id must not
const add = (label, text) => hash.update(`${label}\n${String(text).replace(/\r\n/g, '\n')}\n`)

for (const name of fs.readdirSync(path.join(desktop, 'src')).filter((n) => n !== STAMP).sort()) {
  add(`src/${name}`, fs.readFileSync(path.join(desktop, 'src', name), 'utf8'))
}
for (const name of ['electron-builder.yml', 'scripts/fetch-uv.mjs']) add(name, fs.readFileSync(path.join(desktop, name), 'utf8'))
add('electron', JSON.parse(fs.readFileSync(path.join(desktop, 'node_modules', 'electron', 'package.json'), 'utf8')).version)

const id = hash.digest('hex').slice(0, 16)
if (process.argv.includes('--stamp')) fs.writeFileSync(path.join(desktop, 'src', STAMP), `${JSON.stringify({ shell: id })}\n`)
console.log(id)
