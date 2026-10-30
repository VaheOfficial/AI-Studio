"""Credential storage backed by Windows DPAPI, macOS Keychain or Secret Service."""
from __future__ import annotations
import ctypes
import json
import shutil
import subprocess
import sys
import uuid
from .. import db
from ..osenv import NO_WINDOW

PREFIX = 'vault:'


def available() -> bool:
    return sys.platform in ('win32', 'darwin') or bool(shutil.which('secret-tool'))


def init() -> None:
    db.execute('CREATE TABLE IF NOT EXISTS agent_credentials (id TEXT PRIMARY KEY, value BLOB NOT NULL)')


def dpapi(value: bytes, decrypt: bool = False) -> bytes:
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    source, dest = Blob(len(value), buffer), Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest)):
        raise ValueError('Operating system credential protection failed')
    try:
        return ctypes.string_at(dest.data, dest.size)
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(dest.data, ctypes.c_void_p))


def protect(value: str) -> str:
    if value.startswith(PREFIX):
        return value
    if not available():
        raise ValueError('Credential storage requires the OS keychain (install secret-tool on Linux)')
    key = uuid.uuid4().hex
    if sys.platform == 'win32':
        db.execute('INSERT INTO agent_credentials VALUES(?,?)', (key, dpapi(value.encode())))
    elif sys.platform == 'darwin':
        # security's password argument would expose the secret in argv; use the OS Python keyring bridge instead.
        try:
            import keyring
            keyring.set_password('Grom AI Studio', key, value)
        except (ImportError, Exception) as exc:
            raise ValueError('macOS credential storage requires the keyring package and an unlocked Keychain') from exc
        db.execute('INSERT INTO agent_credentials VALUES(?,?)', (key, b'keychain'))
    else:
        proc = subprocess.run(['secret-tool', 'store', '--label=Grom AI Studio', 'application', 'grom-studio', 'id', key],
            input=value, text=True, capture_output=True, timeout=20, creationflags=NO_WINDOW)
        if proc.returncode:
            raise ValueError('Secret Service refused credential storage')
        db.execute('INSERT INTO agent_credentials VALUES(?,?)', (key, b'secret-service'))
    return PREFIX + key


def reveal(reference: str) -> str:
    if not reference.startswith(PREFIX):
        return reference  # Existing configuration can be migrated without changing connector semantics.
    key = reference[len(PREFIX):]
    row = db.query_one('SELECT value FROM agent_credentials WHERE id=?', (key,))
    if not row:
        raise ValueError('Credential reference is unavailable')
    if sys.platform == 'win32':
        return dpapi(bytes(row['value']), True).decode()
    if sys.platform == 'darwin':
        import keyring
        value = keyring.get_password('Grom AI Studio', key)
    else:
        proc = subprocess.run(['secret-tool', 'lookup', 'application', 'grom-studio', 'id', key],
            text=True, capture_output=True, timeout=20, creationflags=NO_WINDOW)
        value = proc.stdout.rstrip('\n') if proc.returncode == 0 else None
    if value is None:
        raise ValueError('The operating system keychain is locked or the credential is unavailable')
    return value


def resolve_map(values: dict[str, str]) -> dict[str, str]:
    return {k: reveal(v) for k, v in values.items()}
