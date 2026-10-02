# Grom AI Studio

A local-first studio for running **text, image, voice, speech-to-text and music** models on your own GPU, with
a tool-using agent that can set everything up for you. One UI; every model runs on this machine.

```
apps/studio        React 19 + Vite app (the UI)
packages/ui        @studio/ui — the component library + design tokens
server/            FastAPI server: catalog, downloads, runtimes, agent
server/workers/    GPU worker processes, one per runtime family
apps/desktop       Electron shell: the studio as a desktop app (Windows, macOS, Linux)
docs/API.md        HTTP/SSE contract (types in apps/studio/src/api/types.ts)
data/              models, Python envs, outputs, voices, sqlite db (git-ignored)
```

## Run it

```powershell
pnpm install
pnpm server        # terminal 1 — creates server/.venv on first run, serves :8765
pnpm dev           # terminal 2 — UI on http://localhost:5173
```

On macOS and Linux the server starts with `server/run.sh`. As a desktop app (one window, no terminal; builds for
Windows, macOS and Linux): `pnpm desktop`, see [docs/DESKTOP.md](docs/DESKTOP.md). Areas that need an NVIDIA GPU
hide themselves on machines without one; chat and the agent work everywhere.

## How it fits together

- **Models page** — catalog with hardware-fit badges (computed from your VRAM/RAM), one-click install with
  resumable downloads, load/unload to free VRAM, delete from disk.
- **Runtimes** — each model family (diffusers, HunyuanImage 3, Kokoro, Chatterbox, faster-whisper, ACE-Step) gets
  its own isolated Python env under `data/envs/`, created with `uv` the first time it's needed, and runs as a
  separate worker process. Conflicting dependencies can't break each other, and stopping a worker frees its VRAM.
- **Text** runs through Ollama (auto-started), plus optionally OpenRouter or any OpenAI-compatible endpoint
  (vLLM/SGLang/LM Studio/hosted APIs) configured in Settings.
- **Agent** — tool-calling loop over the studio itself: inspect hardware, search/install/delete models, generate
  images/speech/music, and read/write files in `data/workspace`. Installs, deletes, file writes and shell commands
  ask for approval unless you allow them in Settings.
- **Live updates** — one SSE stream (`/api/events`) pushes job progress, model state and logs into the UI cache.

## Component library

`@studio/ui` is consumed as source (no build step). All color, spacing, radius, motion and z-index values are CSS
custom properties in `packages/ui/src/styles/tokens.css`; components use CSS Modules and Radix primitives for
accessibility, and `motion` for animation. Modality hues (`--hue-text/image/voice/stt/music`) tint each area.

## Hardware notes (RTX 4090 · 24 GB, 64 GB RAM)

- **MiMo-V2.6-Pro** is a 1.02T-parameter MoE — datacenter only. Use the 9B distill locally, or point the
  OpenAI-compatible provider at a server running Pro.
- **HunyuanImage 3.x** is an ~80B MoE (~160 GB bf16). It exceeds 24 GB VRAM + 64 GB RAM even at INT8, so it's
  listed with an honest "too large" badge. FLUX.1-schnell, Qwen-Image, SDXL and HunyuanImage 2.1 run well.
- `G:` is a spinning USB hard drive (~38 MB/s measured). A cold 7 GB model load takes ~3 minutes from it
  vs. seconds from NVMe. For speed, point the data folder at an NVMe drive: set `STUDIO_DATA_DIR` (e.g.
  `E:\ai-studio-data`) before `pnpm server` and move `data/` there. If the drive disconnects mid-download the job
  fails cleanly and a re-install resumes.
- VRAM is arbitrated: loading a model evicts other resident models (Ollama LLMs first) when free VRAM is short,
  because Windows otherwise spills into shared RAM and generation gets 5–10× slower.

## License

Grom AI Studio is free software under the GNU Affero General Public License v3.0 only; see [LICENSE](LICENSE). It
includes code ported from VoiceStudio (AGPL-3.0), OpenMuse (MIT) and OmniVoice (Apache-2.0), listed with their
notices in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). Models downloaded through the app keep their own
licenses.
