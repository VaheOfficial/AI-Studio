"""Builds what installed apps update from (see ../src/updates.js).

    python make-update.py bundle <version> <out dir> --shell <id> (--repo owner/name | --base-url https://host/path/)
        Zips the server's source and the built web app (run `pnpm --filter studio build` first) and writes
        `update.json` next to it. `--shell` is the output of `node scripts/shell-id.mjs`.

    python make-update.py packages <dir>
        Adds the release's packages found in <dir> (portable exe, installer, Mac zips, AppImage) to
        <dir>/update.json with their sizes and checksums, for apps that have to replace themselves.

The download addresses are the release's on GitHub (`--repo`), or `--base-url` for a feed hosted elsewhere.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

DESKTOP = Path(__file__).resolve().parent.parent
REPO = DESKTOP.parent.parent
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc"}
# File name ending -> the key an app asks for (<node platform>-<arch>, plus the kind of install on Windows)
PACKAGES = {
    "-portable.exe": "win32-x64-portable",
    "-setup.exe": "win32-x64-setup",
    "-mac-arm64.zip": "darwin-arm64",
    "-mac-x64.zip": "darwin-x64",
    "-linux-x86_64.AppImage": "linux-x64",
    "-linux-arm64.AppImage": "linux-arm64",
}


def files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and not (SKIP_DIRS & set(path.relative_to(root).parts)) and path.suffix not in SKIP_SUFFIXES:
            yield path


def describe(path: Path, base: str) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return {"url": base + path.name, "sha256": digest.hexdigest(), "size": path.stat().st_size}


def bundle(args: argparse.Namespace) -> None:
    web = REPO / "apps" / "studio" / "dist"
    if not (web / "index.html").is_file():
        raise SystemExit("The web app is not built: run `pnpm --filter studio build` first.")
    name = f"Grom-AI-Studio-{args.version}-update.zip"
    args.out.mkdir(parents=True, exist_ok=True)
    archive = args.out / name
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for folder in ("studio", "workers"):
            for path in files(REPO / "server" / folder):
                z.write(path, f"server/{folder}/{path.relative_to(REPO / 'server' / folder).as_posix()}")
        z.write(REPO / "server" / "pyproject.toml", "server/pyproject.toml")
        for path in files(web):
            z.write(path, f"web/{path.relative_to(web).as_posix()}")
        z.writestr("update.json", json.dumps({"version": args.version, "shell": args.shell}))

    if args.repo:
        base = f"https://github.com/{args.repo}/releases/download/v{args.version}/"
        notes = f"https://github.com/{args.repo}/releases/tag/v{args.version}"
    else:
        base, notes = args.base_url.rstrip("/") + "/", None
    manifest = {"version": args.version, "shell": args.shell, **describe(archive, base), "notes": notes}
    (args.out / "update.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{name}: {archive.stat().st_size / 1e6:.1f} MB, shell {args.shell}")


def packages(args: argparse.Namespace) -> None:
    path = args.dir / "update.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    base = manifest["url"].rsplit("/", 1)[0] + "/"
    found = {}
    for file in sorted(args.dir.iterdir()):
        key = next((k for ending, k in PACKAGES.items() if file.name.endswith(ending)), None)
        if key:
            found[key] = describe(file, base)
            print(f"{key}: {file.name}")
    manifest["packages"] = found
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(required=True)
    b = commands.add_parser("bundle")
    b.add_argument("version")
    b.add_argument("out", type=Path)
    b.add_argument("--shell", required=True)
    where = b.add_mutually_exclusive_group(required=True)
    where.add_argument("--repo")
    where.add_argument("--base-url")
    b.set_defaults(run=bundle)
    p = commands.add_parser("packages")
    p.add_argument("dir", type=Path)
    p.set_defaults(run=packages)
    args = parser.parse_args()
    args.run(args)


main()
