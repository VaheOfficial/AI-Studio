# Desktop app

`apps/desktop` is an Electron shell around the same server and web app: one window, nothing to install first. It
runs on Windows, macOS and Linux; what the studio offers on a machine follows the server's capability report
(`GET /api/capabilities`), so the same build shows every area on a PC with an NVIDIA GPU and the chat/agent side
(plus cloud image and voice models, if a key is set) on a machine without one.

## What happens on launch

1. **First launch only**: the bundled `uv` downloads Python 3.13 and installs the server's dependencies
   (`server/pyproject.toml`) into the data folder (about 300 MB, a minute or two; needs internet). It runs again
   only when a new version of the app changes the dependencies.
2. The app starts the server (`python -m studio`) on a free local port and waits for `/api/health`.
3. The window loads the web app from that server. Closing the window stops the server and everything it started.

The app also keeps a few pages of its own browser for the agent, drawn without a window; the server reaches them
over the DevTools protocol on a local port the app opens (see "Browser" in `docs/api/agent.md`).

The splash screen is a view laid over the window; the web app loads underneath it. Its opening sequence (about
six and a half seconds, and a finale of a little over one) plays through once on every launch, even when the server is ready sooner; `STUDIO_SKIP_SPLASH=1`
lets it leave as soon as the app is up. To leave, its mark dashes onto the home page's own mark and lands with
a blow that tears the splash open from that point, so the app appears through the tear, around the mark, instead
of replacing the splash in a cut. The
sequence is the web app's loader (`packages/ui/src/components/Logo/strike.js`); the splash runs a copy of it,
`apps/desktop/src/strike.js`, which `scripts/sync-splash.mjs` writes before the app is started or packaged.

Start-up problems show on the splash screen with the end of the log; the full log is `logs/desktop.log` in the
data folder.

## Where data lives

| Build | Data folder |
|---|---|
| Windows portable exe | `Grom AI Studio Data` next to the exe |
| Windows installer | `%APPDATA%\Grom AI Studio\data` |
| macOS | `~/Library/Application Support/Grom AI Studio/data` |
| Linux AppImage | `~/.config/Grom AI Studio/data` |

On any system, a folder named `Grom AI Studio Data` next to the app (the `.app` bundle or the AppImage) is used instead
when it exists, and `STUDIO_DATA_DIR` overrides everything. The folder holds the Python environment, settings,
chats, models and outputs; deleting it resets the app.

Two copies on one computer (an installed one and a portable one, or a run from source) each have their own data
folder. They can share one models folder: Settings → Storage → Use existing makes a folder that already holds models
the models folder as it is (nothing is moved). Every model's folder says what it holds (`studio-model.json`), and
Models → Rescan lists what the other copy installed there since. Keys and tokens are copied by hand: the eye next to
a saved one in Settings shows it.

The app was called "AI Studio" before. A data folder from then (`AI Studio Data` next to the app, or
`AI Studio/data` in the per-user application data folder) is still picked up when no folder with the new name
exists, so updating keeps settings, chats and the Python environment.

## Window size and zoom

The interface is drawn for a screen of about 1920 × 1080 logical pixels. On a larger screen the app scales
everything up to match, by whichever side has less room, between 1× and 2.25×:

| Screen (work area, logical pixels) | Scale |
|---|---|
| 1920 × 1080 | 1× |
| 3840 × 2160 at 100% display scaling | 2× |
| 3840 × 2160 at 150% display scaling | 1.33× |
| 5120 × 1440 ultrawide | 1.33× |

The scale follows the screen the window is on, so it changes when the window is moved to another monitor. The
window opens at most of the screen, no wider than 16:9.

`Ctrl` (`Cmd` on macOS) with `+` / `-` zooms in and out in 10% steps on top of that, `Ctrl` + mouse wheel does
the same, and `Ctrl` + `0` goes back to the automatic size. The chosen step is kept in `app/window.json` in the
data folder.

When something wants the user while the window is not in front (the agent asks a question or waits for an approval,
a long reply or an automation's run finished), the app shows a system notification and flashes its taskbar button
(on macOS the dock icon bounces) until the window is looked at. Clicking the notification brings the window forward
on the chat it is about. On Windows the notification itself needs the installed app (its Start menu entry is what
Windows files notifications under); a portable copy or a run from source still flashes.

On Windows the installed app's taskbar button goes by the id of its Start menu shortcut (`com.grom.aistudio`), which
gives it the app's name and icon when pinned. A run from the source tree uses an id of its own
(`com.grom.aistudio.dev`) and tells Windows what pinning it should create ("Grom AI Studio (from source)", the
app's icon, a command that starts this app). With one shared id, a pin made from a source run was a shortcut to
`electron.exe`, and the installed app's window showed up under it as "Electron".

Right-clicking opens a menu that fits what was clicked: spelling corrections and "Add to dictionary" on a
misspelled word, the editing commands in a text field, copy on selected text, and open, copy or save for links and
pictures.

## Run and build

```bash
pnpm install
pnpm desktop          # build the web app and open the desktop shell from source
pnpm desktop:pack     # unpacked build in apps/desktop/release (fast; for checking a build)
pnpm desktop:dist     # distributables for the system you are on
```

| Built on | Produces |
|---|---|
| Windows | `Grom-AI-Studio-<version>-portable.exe`, `Grom-AI-Studio-<version>-setup.exe` |
| macOS | `Grom-AI-Studio-<version>-mac-<arch>.dmg`, and a `.zip` of the same app for in-app updates |
| Linux | `Grom-AI-Studio-<version>-linux-<arch>.AppImage` |

Each system builds its own package (a macOS build has to be made on macOS). Building needs Node 22+ and pnpm;
nothing else, since `pnpm desktop:dist` fetches the pinned `uv` for the build machine. From source, `pnpm desktop`
uses `server/.venv` when it exists and attaches to a server already running on port 8765.

### All platforms at once: GitHub Actions

`.github/workflows/desktop.yml` builds on a macOS, a Windows and a Linux runner. Start it from the repository's
Actions tab ("Desktop app" → Run workflow); each job attaches its packages to the run as an artifact
(`Grom-AI-Studio-macOS` holds the Apple silicon and the Intel `.dmg`).

To publish a release, push a tag: `git tag v0.2.0` then `git push origin v0.2.0`. The same builds run with the
tag as the version, and a GitHub release named after the tag is created with every package attached, so they
can be downloaded from the repository's Releases page.

Not every release builds the packages. They are built for an x.y.0, and for any release whose shell differs from
the latest release's (see "In-app updates": the shell is what an installed app cannot update in place). A small
release on the same shell (v0.2.1 after v0.2.0) builds only the update bundle, which takes a few minutes instead of
three systems' builds, and attaches the latest release's packages again unchanged. Installed apps apply the bundle
by themselves; someone installing from the carried-over packages gets the update on first start. The "Update
bundle" job decides and says which it is in its log.

### In-app updates

An installed app asks `releases/latest/download/update.json` on start and every few hours. When the version there
is newer, the top bar shows **Update** and Settings → Updates offers **Install and restart**. What that does
depends on whether the shell changed between the two versions:

- **Same shell: the update bundle.** `Grom-AI-Studio-<version>-update.zip` holds the server's source and the built web
  app (a couple of MB). The app downloads it, checks it against the SHA-256 in `update.json`, unpacks it into
  `app/update/<version>` in the data folder and restarts its server from there; the server's Python packages are
  brought up to date if the bundle's `pyproject.toml` changed. Nothing executable is replaced. An update that fails
  to start is dropped and the installed version runs again.
- **Different shell: the app replaces itself.** The app downloads its own kind of package from the release
  (checked the same way), starts a small helper and quits; the helper waits for the app to be gone, puts the new
  one in its place and opens it (`apps/desktop/src/shell-update.js`):

  | Install | What is downloaded | How it is replaced |
  |---|---|---|
  | Windows portable exe | the new portable exe | a batch file moves it over the old exe and starts it |
  | Windows installer | the new installer | it runs silently and restarts the app |
  | macOS | `Grom-AI-Studio-<version>-mac-<arch>.zip` | a shell script swaps the `.app` bundle (the old one is put back if that fails) and opens it |
  | Linux AppImage | the new AppImage | replaced in place and started |

  A copy that can't write to its own location (a Mac app still running from the download folder, an AppImage in a
  read-only folder) shows a link to the release page instead.

The shell is everything a build bakes into the installed app: the Electron main-process code in
`apps/desktop/src`, the Electron version, the bundled uv and the packaging config. `scripts/shell-id.mjs` hashes
those into an id that is stamped into each build (`src/shell-id.json`) and written to `update.json`; the app
compares the two, so nothing has to be bumped by hand.

`apps/desktop/src/shell.json` holds the feed address. `STUDIO_UPDATE_FEED` points a run at another feed, and
`apps/desktop/scripts/make-update.py` builds a bundle and its `update.json` by hand.

### Signing

The builds carry no Developer ID. The macOS app is signed ad hoc, so it runs, but a downloaded copy is
quarantined: the first time, allow it under System Settings → Privacy & Security → Open Anyway, or clear the flag
with `xattr -dr com.apple.quarantine "/Applications/Grom AI Studio.app"`. On Windows, SmartScreen may ask once.
A Developer ID certificate plus notarization (configured under `mac` in `apps/desktop/electron-builder.yml`)
removes the macOS step.

## What a machine gets

| | NVIDIA GPU | No NVIDIA GPU (Mac, laptop) |
|---|---|---|
| Chat and agent (workspace, terminal, browser, Python, automations, connectors, memory) | yes | yes |
| Chat models | local engines and any API | any API (OpenAI-compatible endpoint, OpenRouter); Ollama, llama.cpp (Metal on Apple silicon, CPU elsewhere) and LM Studio for local models |
| Image, Voice | local and cloud | cloud models, with an OpenRouter key |
| Music, Video, Dub, Audiobook, audio tools | yes | hidden |
| Game | yes | yes (scene art and narration need image/voice) |

The agent's tool list and system prompt follow the same report, so on a machine without a GPU it is never offered
generation tools it cannot run. The agent's terminal is the user's login shell (`zsh`, `bash`) on macOS and Linux
and PowerShell on Windows.

## Server environment variables

| Variable | Effect |
|---|---|
| `STUDIO_DATA_DIR` | Data folder (default: `data/` in the repo, or the table above for the desktop app) |
| `STUDIO_PORT` | Port to listen on (default 8765; the desktop app picks a free one) |
| `STUDIO_WEB_DIR` | Built web app to serve (default `apps/studio/dist` when it exists) |
| `STUDIO_NO_GPU=1` | Ignore the GPU: run as a machine without one |
| `STUDIO_WATCH_PARENT=1` | With `python -m studio`: shut down when standard input closes (how the desktop app stops it) |
| `STUDIO_BROWSER_CDP` | Set by the desktop app: where its browser answers the DevTools protocol, for the agent's pages (see `docs/api/agent.md`) |

Without the desktop shell the server runs the same way everywhere: `pnpm server` on Windows, `server/run.sh` on
macOS and Linux; with the web app built (`pnpm --filter studio build`) it serves the UI itself at its own port.
