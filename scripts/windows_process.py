"""Windows-friendly subprocess helpers (hidden consoles)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

# Win32: hide console windows so the desktop stays usable.
CREATE_NO_WINDOW = 0x08000000
STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE = 0


def is_windows() -> bool:
    return os.name == "nt"


def python_executable(*, prefer_pythonw: bool = True) -> str:
    """Prefer pythonw.exe on Windows so child processes have no console."""
    exe = Path(sys.executable)
    if is_windows() and prefer_pythonw:
        candidate = exe.with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    return str(exe)


def hidden_popen_kwargs() -> dict[str, Any]:
    """Kwargs for subprocess.Popen that suppress console windows on Windows."""
    if not is_windows():
        return {}
    kwargs: dict[str, Any] = {"creationflags": CREATE_NO_WINDOW}
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = SW_HIDE
        kwargs["startupinfo"] = startupinfo
    except Exception:
        pass
    return kwargs


def popen_hidden(
    cmd: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    stdout: Any = subprocess.DEVNULL,
    stderr: Any = subprocess.DEVNULL,
) -> subprocess.Popen[Any]:
    return subprocess.Popen(
        list(cmd),
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
        **hidden_popen_kwargs(),
    )


def run_hidden(
    cmd: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        timeout=timeout,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        **hidden_popen_kwargs(),
    )
