"""Keeps Apple Music running in the background, out of the taskbar.

Apple Music for Windows has no "close to tray" of its own: its X quits the app, and the music
stops with it.  So the keeper does it from outside:

* A low-level mouse hook watches for a left press on Apple Music's close button -- asked of
  Apple Music itself with WM_NCHITTEST, which answers HTCLOSE there -- swallows the press and
  hides the window instead.  Only the press: if the hook is ever too slow, Windows delivers
  the press anyway, and a swallowed release would then leave the left button stuck down for
  the whole desktop (it happened).  A release with no press before it does nothing.  The app keeps playing and the taskbar button
  goes; the widget's tray icon brings it back.  Shift+click the X to really quit.
* A WinEvent hook does the same for minimize.
* If Apple Music is not running, it can be started hidden.

Alt+F4 and File > Exit still quit Apple Music: those arrive as WM_CLOSE inside its process,
which nothing outside the process can refuse.  The widget's Play starts it again, hidden.
"""

from __future__ import annotations

import ctypes
import subprocess
import threading
import time
import traceback
from ctypes import wintypes
from typing import Callable

import track
import win
from win import user32

WINDOW_CLASS = "WinUIDesktopWin32WindowClass"
WINDOW_TITLE = "Apple Music"
EXE_NAME = "applemusic.exe"
#: How long a just-launched Apple Music is watched and re-hidden: it can show itself again
#: while it finishes loading.
LAUNCH_TIMEOUT = 25.0
LAUNCH_SETTLE = 4.0


class Keeper:
    def __init__(self, log: Callable[[str], None], close_to_tray: Callable[[], bool],
                 minimize_to_tray: Callable[[], bool]) -> None:
        self.log = log
        self.close_to_tray = close_to_tray
        self.minimize_to_tray = minimize_to_tray
        self.hidden_by_us = False
        self._cached = (0, False)
        self._quiet_until = 0.0
        self._thread_id = 0
        self._mouse_proc = win.HOOKPROC(self._on_mouse)
        self._event_proc = win.WINEVENTPROC(self._on_event)
        self._launching = threading.Lock()

    # -------------------------------------------------------------- window

    def window(self) -> int:
        """Apple Music's main window, or 0 when it is not running."""
        found = int(user32.FindWindowW(WINDOW_CLASS, WINDOW_TITLE) or 0)
        if not found:
            return 0
        cached, ok = self._cached
        if cached != found:
            ok = win.process_path(found).lower().endswith(EXE_NAME)
            self._cached = (found, ok)
        return found if ok else 0

    def quiet(self, seconds: float) -> None:
        """Ignore Apple Music minimizing for a while: the seek helper is moving it."""
        self._quiet_until = time.monotonic() + seconds

    def running(self) -> bool:
        return bool(self.window())

    def visible(self) -> bool:
        found = self.window()
        return bool(found and user32.IsWindowVisible(found) and not user32.IsIconic(found))

    def hide(self, why: str = "") -> None:
        found = self.window()
        if found:
            user32.ShowWindowAsync(found, win.SW_HIDE)
            self.hidden_by_us = True
            self.log(f"Apple Music -> tray{f' ({why})' if why else ''}")

    def show(self) -> None:
        found = self.window()
        if not found:
            self.launch(hidden=False)
            return
        user32.ShowWindowAsync(found, win.SW_RESTORE if user32.IsIconic(found) else win.SW_SHOW)
        user32.SetForegroundWindow(found)
        self.hidden_by_us = False
        self.log("Apple Music shown")

    def toggle(self) -> None:
        if self.visible():
            self.hide("toggle")
        else:
            self.show()

    def quit_app(self) -> None:
        found = self.window()
        if found:
            user32.PostMessageW(found, win.WM_CLOSE, 0, 0)
            self.hidden_by_us = False
            self.log("asked Apple Music to quit")

    def release(self) -> None:
        """On the widget's way out: never leave Apple Music running with no way back to it."""
        found = self.window()
        if found and self.hidden_by_us and not user32.IsWindowVisible(found):
            user32.ShowWindowAsync(found, win.SW_SHOWMINNOACTIVE)
            self.log("Apple Music handed back to the taskbar")

    def launch(self, hidden: bool = True, then: Callable[[], None] | None = None) -> None:
        """Start Apple Music (hidden by default) on a worker thread, then call `then`."""
        threading.Thread(target=self._launch, args=(hidden, then), name="launch",
                         daemon=True).start()

    def _launch(self, hidden: bool, then: Callable[[], None] | None) -> None:
        if not self._launching.acquire(blocking=False):
            return
        try:
            if not self.running():
                self.log(f"starting Apple Music{' hidden' if hidden else ''}")
                subprocess.Popen(
                    ["explorer.exe", f"shell:AppsFolder\\{track.APPLE_MUSIC_AUMID}"],
                    creationflags=0x08000000,
                )
                deadline = time.monotonic() + LAUNCH_TIMEOUT
                seen_at = 0.0
                while time.monotonic() < deadline:
                    found = self.window()
                    if found and not seen_at:
                        seen_at = time.monotonic()
                    if hidden and found and user32.IsWindowVisible(found):
                        user32.ShowWindowAsync(found, win.SW_HIDE)
                        self.hidden_by_us = True
                    if seen_at and time.monotonic() - seen_at > (LAUNCH_SETTLE if hidden else 0):
                        break
                    time.sleep(0.05)
            if then is not None:
                then()
        except Exception:
            self.log("launch failed:\n" + traceback.format_exc())
        finally:
            self._launching.release()

    # --------------------------------------------------------------- hooks

    def start(self) -> None:
        threading.Thread(target=self._hook_thread, name="keeper", daemon=True).start()

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, win.WM_QUIT, 0, 0)

    def _hook_thread(self) -> None:
        """Both hooks live on this thread, whose only job is to pump their messages: a
        low-level mouse hook delays every click on the machine by however long its thread
        takes to answer, so it must never share a thread with drawing."""
        self._thread_id = win.kernel32.GetCurrentThreadId()
        module = win.kernel32.GetModuleHandleW(None)
        mouse = user32.SetWindowsHookExW(
            win.WH_MOUSE_LL, ctypes.cast(self._mouse_proc, ctypes.c_void_p), module, 0
        )
        event = user32.SetWinEventHook(
            win.EVENT_SYSTEM_MINIMIZESTART, win.EVENT_SYSTEM_MINIMIZESTART, None,
            ctypes.cast(self._event_proc, ctypes.c_void_p), 0, 0, win.WINEVENT_OUTOFCONTEXT,
        )
        self.log(f"keeper hooks: close={'on' if mouse else 'FAILED'}, "
                 f"minimize={'on' if event else 'FAILED'}")
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        if mouse:
            user32.UnhookWindowsHookEx(mouse)
        if event:
            user32.UnhookWinEvent(event)

    def _on_mouse(self, code: int, wparam: int, lparam: int) -> int:
        try:
            if code == 0 and wparam == win.WM_LBUTTONDOWN and self.close_to_tray():
                info = win.MSLLHOOKSTRUCT.from_address(lparam)
                x, y = info.pt.x, info.pt.y
                found = self.window()
                if found and not win.shift_down() and win.root_at(x, y) == found:
                    answer = ctypes.c_size_t()
                    point = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
                    ok = user32.SendMessageTimeoutW(
                        found, win.WM_NCHITTEST, 0, point, win.SMTO_ABORTIFHUNG, 50,
                        ctypes.byref(answer),
                    )
                    if ok and answer.value == win.HTCLOSE:
                        # Everything slow happens off the hook thread: the hook has to answer
                        # within Windows' timeout or the press goes through regardless.
                        threading.Thread(target=self.hide, args=("close button",),
                                         daemon=True).start()
                        return 1
        except Exception:
            self.log("mouse hook error:\n" + traceback.format_exc())
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _on_event(self, hook, event, window, id_object, id_child, thread, when) -> None:
        try:
            if id_object != 0 or not self.minimize_to_tray():
                return
            if time.monotonic() < self._quiet_until:
                return  # the seek helper putting a minimized window back, not the user
            if int(window or 0) and int(window) == self.window():
                # Deferred: hiding inside the event fights the shell's minimize animation.
                threading.Timer(0.3, self._hide_if_minimized).start()
        except Exception:
            self.log("minimize hook error:\n" + traceback.format_exc())

    def _hide_if_minimized(self) -> None:
        found = self.window()
        if found and user32.IsIconic(found):
            self.hide("minimized")
