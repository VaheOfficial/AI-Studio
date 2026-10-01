"""Subprocess entry point for Hugging Face downloads (killable, so cancel really stops I/O).

Usage: python -m studio._hf_fetch '<json: {repo, dest, revision, allow_patterns}>'
The token, if any, comes from the HF_TOKEN environment variable.
"""

from __future__ import annotations

import json
import sys

from huggingface_hub import snapshot_download


def main() -> int:
    args = json.loads(sys.argv[1])
    snapshot_download(
        repo_id=args["repo"],
        revision=args.get("revision"),
        local_dir=args["dest"],
        allow_patterns=args.get("allow_patterns"),
        max_workers=8,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
