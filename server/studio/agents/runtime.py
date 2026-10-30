"""Single-owner host runtime, optional device gateway and explicit service installation."""
from __future__ import annotations
import asyncio
import hashlib
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from .. import config, db
from ..osenv import NO_WINDOW

_lock_file = None
_gateway = None
_gateway_task = None


def acquire():
    global _lock_file
    path = config.DATA_DIR / 'host.lock'
    handle = path.open('a+b')
    try:
        if sys.platform == 'win32':
            import msvcrt
            if path.stat().st_size == 0:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise RuntimeError('Another Studio host already owns this data directory') from exc
    _lock_file = handle


def release():
    global _lock_file
    if _lock_file:
        _lock_file.close()
        _lock_file = None


def status():
    secure = bool(db.get_setting_values().get('agents.gateway_tls'))
    return {'service': os.environ.get('STUDIO_SERVICE') == '1',
            'data_identity': hashlib.sha256(str(config.DATA_DIR).lower().encode()).hexdigest(),
            'gateway_running': bool(_gateway_task and not _gateway_task.done()),
            'gateway_url': f'{"https://localhost" if secure else "http://127.0.0.1"}:{os.environ.get("STUDIO_GATEWAY_PORT", "8767")}',
            'gateway_tls': secure,
            'supports_service_install': sys.platform in ('win32', 'linux', 'darwin')}


async def start_gateway():
    global _gateway, _gateway_task
    if _gateway_task and not _gateway_task.done():
        return status()
    import uvicorn
    from .gateway import app
    class GatewayServer(uvicorn.Server):
        @contextmanager
        def capture_signals(self):
            yield
    port = int(os.environ.get('STUDIO_GATEWAY_PORT', '8767'))
    if not 1024 <= port <= 65535 or port == config.PORT:
        raise ValueError('Choose a separate valid gateway port')
    from .gateway_tls import options
    _gateway = GatewayServer(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', access_log=False, **options()))
    async def serve():
        try:
            await _gateway.serve()
        except SystemExit as exc:
            raise RuntimeError('Device gateway could not bind its port') from exc
    _gateway_task = asyncio.create_task(serve(), name='agent-device-gateway')
    for _ in range(100):
        if _gateway.started:
            db.set_setting_value('agents.gateway_enabled', True)
            return status()
        if _gateway_task.done():
            try:
                await _gateway_task
            except RuntimeError as exc:
                raise ValueError(str(exc)) from exc
            raise ValueError('Device gateway stopped before startup')
        await asyncio.sleep(0.05)
    await stop_gateway()
    raise ValueError('Device gateway startup timed out')


async def stop_gateway():
    global _gateway, _gateway_task
    if _gateway:
        _gateway.should_exit = True
    if _gateway_task:
        try:
            await asyncio.wait_for(asyncio.shield(_gateway_task), 5)
        except (RuntimeError, OSError):
            pass  # A failed listener must not prevent the main host from shutting down.
        except TimeoutError:
            _gateway_task.cancel()
            await asyncio.gather(_gateway_task, return_exceptions=True)
    _gateway, _gateway_task = None, None


def install_service():
    """Register at sign-in; never launch another owner against the active database."""
    folder = config.DATA_DIR / 'services'
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'win32':
        launcher = folder / 'agents-host.ps1'
        quote = lambda v: "'" + str(v).replace("'", "''") + "'"
        launcher.write_text("$env:STUDIO_DATA_DIR = " + quote(config.DATA_DIR) + "\n$env:STUDIO_SERVICE = '1'\n"
            "$env:STUDIO_PORT = '8765'\n$env:STUDIO_WATCH_PARENT = '0'\n$env:STUDIO_WEB_DIR = " + quote(config.WEB_DIR) + "\nSet-Location -LiteralPath " + quote(config.SERVER_DIR) +
            '\n& ' + quote(config.SERVER_PYTHON) + " -m studio --service\n", encoding='utf-8')
        command = subprocess.list2cmdline(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', str(launcher)])
        proc = subprocess.run(['schtasks.exe', '/Create', '/TN', 'Grom Agents Host', '/SC', 'ONLOGON', '/RL', 'LIMITED', '/TR', command, '/F'],
            capture_output=True, text=True, creationflags=NO_WINDOW, timeout=30)
    elif sys.platform == 'linux':
        target = Path.home() / '.config' / 'systemd' / 'user' / 'grom-agents.service'
        target.parent.mkdir(parents=True, exist_ok=True)
        quoted = lambda v: '"' + str(v).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
        target.write_text('[Unit]\nDescription=Grom Agents Host\nAfter=network-online.target\n[Service]\nType=simple\n'
            'WorkingDirectory=' + quoted(config.SERVER_DIR) + '\nEnvironment="STUDIO_SERVICE=1" "STUDIO_WATCH_PARENT=0" "STUDIO_PORT=8765"\n'
            'Environment=' + quoted('STUDIO_DATA_DIR=' + str(config.DATA_DIR)) + ' ' + quoted('STUDIO_WEB_DIR=' + str(config.WEB_DIR)) + '\nExecStart=' + quoted(config.SERVER_PYTHON) +
            ' -m studio --service\nRestart=on-failure\n[Install]\nWantedBy=default.target\n', encoding='utf-8')
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True, capture_output=True, timeout=20)
        proc = subprocess.run(['systemctl', '--user', 'enable', 'grom-agents.service'], capture_output=True, text=True, timeout=20)
    elif sys.platform == 'darwin':
        import plistlib
        target = Path.home() / 'Library' / 'LaunchAgents' / 'com.grom.agents.plist'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(plistlib.dumps({'Label': 'com.grom.agents', 'ProgramArguments': [str(config.SERVER_PYTHON), '-m', 'studio', '--service'],
            'WorkingDirectory': str(config.SERVER_DIR), 'RunAtLoad': True, 'KeepAlive': {'SuccessfulExit': False},
            'EnvironmentVariables': {'STUDIO_SERVICE': '1', 'STUDIO_WATCH_PARENT': '0', 'STUDIO_PORT': '8765', 'STUDIO_DATA_DIR': str(config.DATA_DIR), 'STUDIO_WEB_DIR': str(config.WEB_DIR)}}))
        return {'registered': True, 'starts': 'next sign-in', 'path': str(target)}
    else:
        raise ValueError('Automatic service registration is unavailable on this platform')
    if proc.returncode:
        raise ValueError('Host registration failed: ' + (proc.stderr or proc.stdout)[-1000:])
    return {'registered': True, 'starts': 'next sign-in'}


def uninstall_service():
    if sys.platform == 'win32':
        command = ['schtasks.exe', '/Delete', '/TN', 'Grom Agents Host', '/F']
    elif sys.platform == 'linux':
        command = ['systemctl', '--user', 'disable', 'grom-agents.service']
    elif sys.platform == 'darwin':
        path = Path.home() / 'Library' / 'LaunchAgents' / 'com.grom.agents.plist'
        path.unlink(missing_ok=True)
        return {'registered': False, 'current_host_running': True}
    else:
        raise ValueError('Service registration is unavailable')
    proc = subprocess.run(command, capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    if proc.returncode:
        raise ValueError('Could not remove host registration')
    return {'registered': False, 'current_host_running': True}
