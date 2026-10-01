#!/usr/bin/env bash
# macOS / Linux counterpart of run.ps1: creates server/.venv if needed, installs dependencies when pyproject.toml
# changes, then serves the Studio API on http://127.0.0.1:${STUDIO_PORT:-8765}. Needs `uv` or Python 3.11+ on PATH.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv="$root/.venv"
py="$venv/bin/python"

if [ ! -x "$py" ]; then
  echo "Creating server virtualenv..."
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.13 "$venv"
  else
    python3 -m venv "$venv"
    "$py" -m pip install --quiet --upgrade pip
  fi
fi

if command -v sha256sum >/dev/null 2>&1; then
  hash="$(sha256sum "$root/pyproject.toml" | cut -d' ' -f1)"
else
  hash="$(shasum -a 256 "$root/pyproject.toml" | cut -d' ' -f1)"
fi
stamp="$venv/.deps-stamp"
if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$hash" ]; then
  echo "Installing server dependencies..."
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$py" -e "$root"
  else
    "$py" -m pip install --quiet -e "$root"
  fi
  printf '%s' "$hash" > "$stamp"
fi

cd "$root"
args=(-m uvicorn studio.main:app --host 127.0.0.1 --port "${STUDIO_PORT:-8765}")
if [ "${1:-}" = "--reload" ]; then args+=(--reload --reload-dir "$root/studio"); fi
exec "$py" "${args[@]}"
