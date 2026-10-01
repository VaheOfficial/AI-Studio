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

Start-up problems show on the splash screen with the end of the log; the full log is `logs/desktop.log` in the
data folder.

## Where data lives

| Build | Data folder |
|---|---|
| Windows portable exe | `AI Studio Data` next to the exe |
| Windows installer | `%APPDATA%\AI Studio\data` |
| macOS | `~/Library/Application Support/AI Studio/data` |
| Linux AppImage | `~/.config/AI Studio/data` |

On any system, a folder named `AI Studio Data` next to the app (the `.app` bundle or the AppImage) is used instead
when it exists, and `STUDIO_DATA_DIR` overrides everything. The folder holds the Python environment, settings,
chats, models and outputs; deleting it resets the app.

## Run and build

```bash
pnpm install
pnpm desktop          # build the web app and open the desktop shell from source
pnpm desktop:pack     # unpacked build in apps/desktop/release (fast; for checking a build)
pnpm desktop:dist     # distributables for the system you are on
```

| Built on | Produces |
|---|---|
| Windows | `AI-Studio-<version>-portable.exe`, `AI-Studio-<version>-setup.exe` |
| macOS | `AI-Studio-<version>-mac-<arch>.dmg` |
| Linux | `AI-Studio-<version>-linux-<arch>.AppImage` |

Each system builds its own package (a macOS build has to be made on macOS). Building needs Node 22+ and pnpm;
nothing else, since `pnpm desktop:dist` fetches the pinned `uv` for the build machine. From source, `pnpm desktop`
uses `server/.venv` when it exists and attaches to a server already running on port 8765.

### All platforms at once: GitHub Actions

`.github/workflows/desktop.yml` builds on a macOS, a Windows and a Linux runner. Start it from the repository's
Actions tab ("Desktop app" → Run workflow) or push a tag such as `v0.1.0`; each job attaches its packages to the
run as an artifact (`AI-Studio-macOS` holds the Apple silicon and the Intel `.dmg`).

### Signing

The builds carry no Developer ID. The macOS app is signed ad hoc, so it runs, but a downloaded copy is
quarantined: the first time, allow it under System Settings → Privacy & Security → Open Anyway, or clear the flag
with `xattr -dr com.apple.quarantine "/Applications/AI Studio.app"`. On Windows, SmartScreen may ask once.
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

Without the desktop shell the server runs the same way everywhere: `pnpm server` on Windows, `server/run.sh` on
macOS and Linux; with the web app built (`pnpm --filter studio build`) it serves the UI itself at its own port.
