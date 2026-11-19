"""Small OS adapters for locks, owned process trees, and executable discovery."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys


def windows():
    return os.name == 'nt'


def platform_id():
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {'amd64':'x86_64', 'x64':'x86_64', 'arm64':'aarch64'}.get(machine, machine)
    if system not in ('linux', 'windows') or arch not in ('x86_64', 'aarch64'):
        raise ValueError(f'Automatic Strata preparation supports Linux and Windows on x86_64/aarch64, not {system}/{arch}.')
    return system, arch


def executable(name='strata'):
    return name + ('.exe' if windows() else '')


def python_in(folder):
    folder = Path(folder)
    return folder / ('Scripts/python.exe' if windows() else 'bin/python')


def find_python(source=None, explicit=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise ValueError('The selected Python executable does not exist.')
        return str(path)
    if source:
        for base in (Path(source),Path(source) / 'terminal'):
            path = python_in(base / '.venv')
            if path.is_file():
                return str(path.resolve())
    # pythonw can hide the launcher; workers need an interpreter with standard streams.
    sibling = Path(sys.executable).with_name('python.exe') if windows() else Path(sys.executable)
    return str(sibling if sibling.is_file() else Path(sys.executable))


def process_options(detached=False):
    if windows():
        return {'creationflags': getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0x200) | getattr(subprocess,'CREATE_NO_WINDOW',0x08000000)}
    return {'start_new_session': True}


def quiet_options():
    return {'creationflags':getattr(subprocess,'CREATE_NO_WINDOW',0x08000000)} if windows() else {}


def lock_file(stream, unlock=False):
    stream.seek(0)
    if windows():
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB)


def is_locked(path):
    try:
        with Path(path).open('r+b') as stream:
            try:
                lock_file(stream)
            except OSError:
                return True
            lock_file(stream, unlock=True)
    except FileNotFoundError:
        return False
    return False


def stop_tree(proc, interrupt=False):
    """Stop only the child tree created by this app. Completed answer rows are durable."""
    if proc.poll() is not None:
        return
    if windows():
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0x08000000), check=False)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGINT if interrupt else signal.SIGTERM)
        if interrupt:
            return
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if windows():
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
    if not windows():
        # The parent may exit before a child that ignored TERM; its owned group still needs cleanup.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=5)
