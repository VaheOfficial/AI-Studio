"""Read single values from a GGUF file's metadata header, without the ``gguf`` package (it lives only in the ML envs).

The header is: magic, version, tensor count, key/value count, then the key/value pairs; the pairs are walked in
order (arrays such as the tokenizer vocabulary are skipped, not decoded) until the wanted key turns up.
"""

from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO

# GGUF value types → struct format of a scalar; 8 = string, 9 = array
_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_STRING, _ARRAY = 8, 9


def _read(f: BinaryIO, fmt: str) -> Any:
    size = struct.calcsize(fmt)
    data = f.read(size)
    if len(data) != size:
        raise ValueError("truncated GGUF header")
    return struct.unpack(fmt, data)[0]


def _string(f: BinaryIO) -> str:
    return f.read(_read(f, "<Q")).decode("utf-8", errors="replace")


def _value(f: BinaryIO, vtype: int, keep: bool) -> Any:
    if vtype in _SCALARS:
        return _read(f, _SCALARS[vtype])
    if vtype == _STRING:
        n = _read(f, "<Q")
        if keep:
            return f.read(n).decode("utf-8", errors="replace")
        f.seek(n, 1)
        return None
    if vtype == _ARRAY:
        item, count = _read(f, "<I"), _read(f, "<Q")
        if item in _SCALARS:  # fixed-size items: jump over them
            f.seek(struct.calcsize(_SCALARS[item]) * count, 1)
        else:
            for _ in range(count):
                _value(f, item, keep=False)
        return None
    raise ValueError(f"unknown GGUF value type {vtype}")


def read_values(path: Path, wanted: set[str]) -> dict[str, Any]:
    """The requested scalar/string metadata values (missing keys are absent). ``{arch}`` in a key stands for
    the file's ``general.architecture``."""
    found: dict[str, Any] = {}
    with path.open("rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError(f"{path.name} is not a GGUF file")
        _read(f, "<I")  # version
        _read(f, "<Q")  # tensor count
        pending = set(wanted)
        arch = ""

        def resolved(w: str) -> str | None:
            return w.replace("{arch}", arch) if arch else (None if "{arch}" in w else w)

        for _ in range(_read(f, "<Q")):
            key = _string(f)
            vtype = _read(f, "<I")
            match = next((w for w in pending if resolved(w) == key), None)
            value = _value(f, vtype, keep=match is not None or key == "general.architecture")
            if key == "general.architecture":
                arch = str(value)
            if match is not None:
                found[match] = value
                pending.discard(match)
            if not pending:
                break
    return found


# Architectures of speculative-decoding drafters: they only run next to a target model, never on their own
DRAFT_ARCHITECTURES = frozenset({"dflash", "eagle3"})


@lru_cache(maxsize=64)
def _architecture(path: str, _size: int, _mtime: float) -> str:
    try:
        return str(read_values(Path(path), {"general.architecture"}).get("general.architecture") or "")
    except (OSError, ValueError, struct.error):
        return ""


def architecture(path: Path) -> str:
    """``general.architecture`` of a GGUF ("" when unreadable)."""
    try:
        st = path.stat()
    except OSError:
        return ""
    return _architecture(str(path), st.st_size, st.st_mtime)


@lru_cache(maxsize=32)
def _mtp_layers(path: str, _size: int, _mtime: float) -> int:
    try:
        return int(read_values(Path(path), {"{arch}.nextn_predict_layers"}).get("{arch}.nextn_predict_layers") or 0)
    except (OSError, ValueError, struct.error):
        return 0


def mtp_layers(path: Path) -> int:
    """How many multi-token-prediction ("nextn") layers the model carries; 0 when it has none (most GGUFs drop them)."""
    try:
        st = path.stat()
    except OSError:
        return 0
    return _mtp_layers(str(path), st.st_size, st.st_mtime)
