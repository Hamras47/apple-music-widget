"""Seeking Apple Music, which Windows' media session cannot do.

Apple Music ignores position changes sent through the media session (it reports
IsPlaybackPositionEnabled = false), so seek.ps1 moves its own progress slider through UI
Automation.  PowerShell already ships with Windows and with UI Automation, so this costs no
new Python dependency; the helper is started once and kept alive, because starting PowerShell
takes longer than the seek itself.  Requests coalesce: while one seek runs, only the newest
waiting target is kept.
"""

from __future__ import annotations

import subprocess
import threading
import traceback
from pathlib import Path
from typing import Callable

SCRIPT = Path(__file__).resolve().parent / "seek.ps1"
CREATE_NO_WINDOW = 0x08000000


class Seeker:
    def __init__(self, log: Callable[[str], None],
                 on_busy: Callable[[], None] = lambda: None) -> None:
        self.log = log
        self.on_busy = on_busy
        self._process: subprocess.Popen | None = None
        self._target: float | None = None
        self._wake = threading.Condition()
        self._stopped = False

    def start(self) -> None:
        threading.Thread(target=self._run, name="seeker", daemon=True).start()

    def stop(self) -> None:
        with self._wake:
            self._stopped = True
            self._wake.notify()
        process = self._process
        if process and process.poll() is None:
            try:
                process.stdin.write("quit\n")
                process.stdin.flush()
            except OSError:
                pass

    def seek(self, seconds: float) -> None:
        with self._wake:
            self._target = max(0.0, seconds)
            self._wake.notify()

    def _spawn(self) -> subprocess.Popen:
        process = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(SCRIPT)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", creationflags=CREATE_NO_WINDOW,
        )
        ready = process.stdout.readline().strip()
        self.log(f"seek helper {'ready' if ready == 'ready' else 'did not start: ' + ready}")
        return process

    def _run(self) -> None:
        try:
            self._process = self._spawn()  # warm, so the first seek is not the slow one
        except Exception:
            self.log("seek helper failed to start:\n" + traceback.format_exc())
        while True:
            with self._wake:
                while self._target is None and not self._stopped:
                    self._wake.wait()
                if self._stopped:
                    return
                target, self._target = self._target, None
            try:
                if self._process is None or self._process.poll() is not None:
                    self._process = self._spawn()
                self.on_busy()
                self._process.stdin.write(f"seek {target:.2f}\n")
                self._process.stdin.flush()
                answer = self._process.stdout.readline().strip()
                self.log(f"seek {target:.1f}s -> {answer or 'no answer'}")
            except Exception:
                self.log("seek failed:\n" + traceback.format_exc())
                self._process = None
