"""Apple Music -- a now-playing widget, and a tray home for Apple Music itself.

* The face (surface.py) is drawn by us and handed to Windows as a per-pixel alpha layered
  window, the same way as the clock: glass tinted by the cover, or clear on the wallpaper.
* What is playing comes from Windows' media session (media.py); no Apple account, no API.
* The keeper (keeper.py) turns Apple Music's X and minimize into "hide to tray", so the music
  keeps going with no window open.  The tray icon brings Apple Music back; Shift+X quits it.

    python app.py                   the widget
    python app.py --render out.png  the face as a PNG, from what is playing now
    python app.py --debug           also print the log
"""

from __future__ import annotations

import argparse
import dataclasses
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import pystray
from PIL import Image

import surface
import track
import win
from keeper import Keeper
from media import MediaWatcher
from seeker import Seeker
from win import gdi32, user32

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.json"
LOG_FILE = HERE / "widget.log"

WINDOW_TITLE = "Apple Music Widget"
CLASS_NAME = "AppleMusicNowPlayingWidget"
TRAY_TITLE = "Apple Music"
SHORTCUT_NAME = "Apple Music Widget.lnk"

TICK_MS = 250
#: Width limits in design pixels; the height follows the width.
MIN_WIDTH, MAX_WIDTH = 260, 720
DESKTOP_TICKS = 2
DESKTOP_CLASSES = {"Progman", "WorkerW", "SysListView32", "SHELLDLL_DefView"}

WM_APP_REDRAW = win.WM_APP + 1
WM_APP_COMMAND = win.WM_APP + 2
#: How long a seek is shown as done before the player has caught up with it.
SEEK_HOLD = 3.0
RESIZE_CURSORS = {"n": 32645, "s": 32645, "e": 32644, "w": 32644,
                  "nw": 32642, "se": 32642, "ne": 32643, "sw": 32643}
WM_SETCURSOR, WM_MOUSEWHEEL, WM_CAPTURECHANGED, MK_CONTROL = 0x20, 0x20A, 0x215, 0x8

(MENU_SHOW_AM, MENU_HIDE_AM, MENU_QUIT_AM, MENU_GLASS, MENU_CLEAR, MENU_CLOSE_TRAY,
 MENU_MIN_TRAY, MENU_LAUNCH, MENU_ANY_PLAYER, MENU_ON_TOP, MENU_AUTOSTART, MENU_FOLDER,
 MENU_HIDE, MENU_QUIT) = range(1, 15)
#: Size presets: menu id -> (label, width in design pixels).
SIZES = {15: ("Small", 280), 16: ("Medium", 360), 17: ("Large", 460), 18: ("Extra large", 600)}
SEPARATOR = (0, "", None)

DEBUG = False


def log(message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if DEBUG:
        print(f"{stamp}  {message}", flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}  {message}\n")
    except OSError:
        pass


def install_excepthook() -> None:
    def handler(kind, value, tb):
        log("unhandled error:\n" + "".join(traceback.format_exception(kind, value, tb)))

    sys.excepthook = handler
    threading.excepthook = lambda args: handler(args.exc_type, args.exc_value,
                                                args.exc_traceback)


def load_config() -> dict:
    config = {
        "style": "glass",
        "on_top": False,
        "stay_on_desktop": True,
        "close_to_tray": True,
        "minimize_to_tray": True,
        "launch_with_widget": False,
        "any_player": False,
        "window": None,
    }
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            config.update(saved)
    except (OSError, ValueError):
        pass
    return config


def save_config(config: dict) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        log(f"could not write {CONFIG_FILE.name}: {error}")


def startup_shortcut() -> Path:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    return appdata / "Microsoft/Windows/Start Menu/Programs/Startup" / SHORTCUT_NAME


def set_autostart(enabled: bool) -> bool:
    link = startup_shortcut()
    if not enabled:
        link.unlink(missing_ok=True)
        return True
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
        "$s.TargetPath='{exe}';$s.Arguments='\"{script}\"';$s.WorkingDirectory='{cwd}';$s.Save()"
    ).format(link=link, exe=exe, script=HERE / "app.py", cwd=HERE)
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, timeout=30, check=False, creationflags=0x08000000)
    except (OSError, subprocess.SubprocessError) as error:
        log(f"could not create the startup shortcut: {error}")
    return link.exists()


def tray_image(size: int = 64) -> Image.Image:
    art = surface.placeholder_art(size * 4).resize((size, size), Image.LANCZOS).convert("RGBA")
    art.putalpha(surface._rounded_mask(size, size, round(size * 0.24)))
    return art


class Widget:
    def __init__(self) -> None:
        self.config = load_config()
        self.hwnd = 0
        self.hover: str | None = None
        self.picture: surface.Render | None = None
        self.painter = surface.Painter()
        self.icon: pystray.Icon | None = None
        self._wndproc = win.WNDPROC(self._handle_message)
        self._last_frame: tuple = ()
        self._dirty = True
        self._desktop_tick = 0
        self._desktop_front = False
        self._desktop_streak = 0
        self.keeper = Keeper(log, lambda: bool(self.config["close_to_tray"]),
                             lambda: bool(self.config["minimize_to_tray"]))
        self.seeker = Seeker(log, lambda: self.keeper.quiet(4.0))
        self._pending_seek: tuple[float, float] | None = None
        self._scrub: float | None = None
        #: The press being dragged: ("scrub",) or ("resize", edge, start cursor, start rect).
        self._gesture: tuple | None = None
        self.media = MediaWatcher(log, self._media_changed,
                                  lambda: bool(self.config["any_player"]))

    # -------------------------------------------------------------- basics

    @property
    def scale(self) -> float:
        dpi = user32.GetDpiForWindow(self.hwnd) if self.hwnd else 96
        return (dpi or 96) / 96.0

    def rect(self) -> tuple[int, int, int, int]:
        box = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(box))
        return box.left, box.top, box.right - box.left, box.bottom - box.top

    def save_geometry(self) -> None:
        left, top, width, _ = self.rect()
        scale = self.scale
        self.config["window"] = {"x": round(left / scale), "y": round(top / scale),
                                 "width": round(width / scale)}
        save_config(self.config)

    def start_geometry(self) -> tuple[int, int, int]:
        saved = self.config.get("window")
        if isinstance(saved, dict) and all(k in saved for k in ("x", "y", "width")):
            width = max(MIN_WIDTH, min(MAX_WIDTH, int(saved["width"])))
            return int(saved["x"]), int(saved["y"]), width
        # The work area is in physical pixels; the window has to exist to know the scale.
        scale = self.scale
        left, _, _, bottom = win.monitor_work_area(self.hwnd)
        width = int(surface.WINDOW_W)
        return (int(left / scale + 40), int(bottom / scale - surface.WINDOW_H - 40), width)

    def place(self, x_css: int, y_css: int, width_css: int) -> None:
        scale = self.scale
        width = max(1, int(width_css * scale))
        user32.SetWindowPos(self.hwnd, None, int(x_css * scale), int(y_css * scale), width,
                            surface.height_for(width), win.SWP_NOZORDER | win.SWP_NOACTIVATE)

    # ------------------------------------------------------------- drawing

    def _media_changed(self) -> None:
        self._dirty = True
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_APP_REDRAW, 0, 0)

    def draw(self, force: bool = False) -> None:
        _, _, width, height = self.rect()
        if width <= 0 or height <= 0:
            return
        now = self.media.snapshot
        view = surface.view_of(now, self.keeper.running(), time.time())
        view = dataclasses.replace(view, position=self.displayed_position(view, now))
        style = self.config["style"]
        # Skip identical frames: while paused nothing moves, and the bar only needs a new frame
        # when the second it shows, or the pixel it reaches, changes.
        bar_px = int(view.position / view.duration * width) if view.duration > 0 else 0
        frame = (view.title, view.artist, view.playing, id(view.art), int(view.position), bar_px,
                 self.hover, style, width, height)
        if not force and not self._dirty and frame == self._last_frame:
            return
        self._dirty = False
        self._last_frame = frame
        picture = self.painter.render(view, width, height, style, self.hover)
        self.picture = picture
        self.paint(picture)

    def paint(self, picture: surface.Render) -> None:
        left, top, _, _ = self.rect()
        screen = user32.GetDC(None)
        memory = gdi32.CreateCompatibleDC(screen)
        header = win.BITMAPINFO()
        header.bmiHeader.biSize = ctypes.sizeof(win.BITMAPINFOHEADER)
        header.bmiHeader.biWidth = picture.width
        header.bmiHeader.biHeight = -picture.height
        header.bmiHeader.biPlanes = 1
        header.bmiHeader.biBitCount = 32
        header.bmiHeader.biCompression = win.BI_RGB
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(memory, ctypes.byref(header), win.DIB_RGB_COLORS,
                                        ctypes.byref(bits), None, 0)
        if not bitmap or not bits:
            gdi32.DeleteDC(memory)
            user32.ReleaseDC(None, screen)
            log("could not create a bitmap for the face")
            return
        previous = gdi32.SelectObject(memory, bitmap)
        ctypes.memmove(bits, picture.pixels, len(picture.pixels))
        size = wintypes.SIZE(picture.width, picture.height)
        source = wintypes.POINT(0, 0)
        destination = wintypes.POINT(left, top)
        blend = win.BLENDFUNCTION(win.AC_SRC_OVER, 0, 255, win.AC_SRC_ALPHA)
        if not user32.UpdateLayeredWindow(self.hwnd, screen, ctypes.byref(destination),
                                          ctypes.byref(size), memory, ctypes.byref(source), 0,
                                          ctypes.byref(blend), win.ULW_ALPHA):
            log(f"UpdateLayeredWindow failed ({ctypes.get_last_error()})")
        gdi32.SelectObject(memory, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(None, screen)

    # --------------------------------------------------------------- mouse

    def local(self, screen_x: int, screen_y: int) -> tuple[int, int]:
        left, top, _, _ = self.rect()
        return screen_x - left, screen_y - top

    def _hit_test(self, screen_x: int, screen_y: int) -> int:
        picture = self.picture
        if picture is None:
            return win.HTTRANSPARENT
        x, y = self.local(screen_x, screen_y)
        if picture.edge_at(x, y) or picture.button_at(x, y):
            return win.HTCLIENT
        if picture.in_card(x, y):
            return win.HTCAPTION
        return win.HTTRANSPARENT

    def pointer_target(self) -> str | None:
        """What the pointer is over: a button, "seek", "edge:<zone>", "card" or None."""
        picture = self.picture
        if picture is None:
            return None
        x, y = self.local(*win.cursor_position())
        if not (0 <= x < picture.width and 0 <= y < picture.height):
            return None
        edge = picture.edge_at(x, y)
        if edge:
            return f"edge:{edge}"
        return picture.button_at(x, y) or ("card" if picture.in_card(x, y) else None)

    def set_hover(self, target: str | None) -> None:
        if target != self.hover:
            self.hover = target
            self.draw()

    def set_cursor(self) -> bool:
        target = self.pointer_target() or ""
        if target.startswith("edge:"):
            shape = RESIZE_CURSORS[target[5:]]
        elif target in ("prev", "play", "next", "seek"):
            shape = win.IDC_HAND
        else:
            return False
        user32.SetCursor(user32.LoadCursorW(None, ctypes.c_void_p(shape)))
        return True

    def click(self, x: int, y: int) -> None:
        picture = self.picture
        if picture is None:
            return
        edge = picture.edge_at(x, y)
        if edge:
            self.start_resize(edge)
            return
        button = picture.button_at(x, y)
        now = self.media.snapshot
        if button == "play":
            if now.idle and not self.keeper.running():
                self.keeper.launch(hidden=True, then=self._play_when_ready)
            elif now.idle:
                self._play_when_ready()
            else:
                self.media.command("toggle")
        elif button in ("prev", "next"):
            self._pending_seek = None
            self.media.command(button)
        elif button == "seek" and now.duration > 0:
            self.start_scrub(x)

    def _play_when_ready(self) -> None:
        def wait() -> None:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not self.media.has_apple_session():
                time.sleep(0.25)
            self.media.command("play")

        threading.Thread(target=wait, name="play", daemon=True).start()

    # ----------------------------------------------------------------- seek

    def start_scrub(self, x: int) -> None:
        """Press on the bar and drag: the bar follows the pointer, and the seek happens on
        release -- one seek, not one per pixel."""
        self._gesture = ("scrub",)
        user32.SetCapture(self.hwnd)
        self.track_scrub(x)

    def track_scrub(self, x: int) -> None:
        picture = self.picture
        duration = self.media.snapshot.duration
        self._scrub = picture.seek_fraction(x) * duration if picture else 0.0
        self.hover = "seek"
        self.draw()

    def end_gesture(self) -> None:
        """Button up, or capture taken away: finish whatever the press started."""
        gesture, self._gesture = self._gesture, None
        if gesture is None:
            return
        user32.ReleaseCapture()
        if gesture[0] == "scrub":
            target, self._scrub = self._scrub, None
            if target is not None:
                self.seek(target)
        else:
            self.draw(force=True)
            self.save_geometry()

    def seek(self, seconds: float) -> None:
        now = self.media.snapshot
        # Shown at once, and held until the player's own reports catch up with it.
        self._pending_seek = (seconds, time.time())
        if now.is_apple:
            self.seeker.seek(seconds)
        else:
            self.media.command("seek", seconds)
        self.draw(force=True)

    def displayed_position(self, view: surface.View, now: track.NowPlaying) -> float:
        if self._scrub is not None:
            return self._scrub
        if self._pending_seek is not None:
            target, stamp = self._pending_seek
            elapsed = time.time() - stamp
            guess = target + (elapsed if now.playing else 0.0)
            if elapsed < SEEK_HOLD and abs(view.position - guess) > 2.0:
                return min(guess, view.duration) if view.duration else guess
            self._pending_seek = None
        return view.position

    # --------------------------------------------------------------- resize

    def resize_to(self, width: float, edge: str = "se",
                  origin: tuple[int, int, int, int] | None = None) -> None:
        """Resize to a physical width (height follows), keeping the side opposite `edge`."""
        left, top, old_width, old_height = origin or self.rect()
        low, high = int(MIN_WIDTH * self.scale), int(MAX_WIDTH * self.scale)
        width = max(low, min(high, int(width)))
        height = surface.height_for(width)
        new_left = left + (old_width - width) if "w" in edge else left
        new_top = top + (old_height - height) if "n" in edge else top
        user32.SetWindowPos(self.hwnd, None, new_left, new_top, width, height,
                            win.SWP_NOZORDER | win.SWP_NOACTIVATE)

    def start_resize(self, edge: str) -> None:
        """Drag any edge or corner; the face keeps its proportions and scales as a whole."""
        self._gesture = ("resize", edge, win.cursor_position(), self.rect())
        user32.SetCapture(self.hwnd)

    def track_resize(self) -> None:
        _, edge, (start_x, start_y), origin = self._gesture
        x, y = win.cursor_position()
        dx = (x - start_x) * (1 if "e" in edge else -1 if "w" in edge else 0)
        dy = (y - start_y) * (1 if "s" in edge else -1 if "n" in edge else 0)
        aspect = surface.WINDOW_W / surface.WINDOW_H
        grow = dx if abs(dx) >= abs(dy * aspect) else dy * aspect
        width = origin[2] + int(grow)
        if width != self.rect()[2]:
            self.resize_to(width, edge, origin)
            self.draw()

    def wheel_resize(self, delta: int) -> None:
        _, _, width, _ = self.rect()
        self.resize_to(width * (1.06 if delta > 0 else 1 / 1.06))
        self.draw(force=True)
        self.save_geometry()

    # ---------------------------------------------------------------- menu

    def menu_items(self) -> list[tuple[int, str, bool | None]]:
        running = self.keeper.running()
        visible = self.keeper.visible()
        c = self.config
        items: list[tuple[int, str, bool | None]] = []
        if running and visible:
            items.append((MENU_HIDE_AM, "Hide Apple Music to tray", None))
        else:
            items.append((MENU_SHOW_AM, "Open Apple Music" if not running
                          else "Show Apple Music", None))
        if running:
            items.append((MENU_QUIT_AM, "Quit Apple Music", None))
        items += [
            SEPARATOR,
            (MENU_GLASS, "Glass style", c["style"] == "glass"),
            (MENU_CLEAR, "Clear style", c["style"] == "clear"),
            SEPARATOR,
            (MENU_CLOSE_TRAY, "Apple Music's X hides to tray", bool(c["close_to_tray"])),
            (MENU_MIN_TRAY, "Minimizing Apple Music hides to tray",
             bool(c["minimize_to_tray"])),
            (MENU_LAUNCH, "Start Apple Music hidden with the widget",
             bool(c["launch_with_widget"])),
            (MENU_ANY_PLAYER, "Show other players too", bool(c["any_player"])),
            SEPARATOR,
            *self.size_items(),
            SEPARATOR,
            (MENU_ON_TOP, "Always on top", bool(c["on_top"])),
            (MENU_AUTOSTART, "Start with Windows", startup_shortcut().exists()),
            (MENU_FOLDER, "Open folder", None),
            SEPARATOR,
            (MENU_HIDE, "Hide widget", None),
            (MENU_QUIT, "Quit widget", None),
        ]
        return items

    def size_items(self) -> list[tuple[int, str, bool | None]]:
        width = round(self.rect()[2] / self.scale) if self.hwnd else 0
        return [(ident, f"Size: {label}", abs(width - size) <= 2)
                for ident, (label, size) in SIZES.items()]

    def open_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        for ident, label, checked in self.menu_items():
            if not ident:
                user32.AppendMenuW(menu, win.MF_SEPARATOR, 0, None)
            else:
                user32.AppendMenuW(menu, win.MF_STRING | (win.MF_CHECKED if checked else 0),
                                   ident, label)
        x, y = win.cursor_position()
        user32.SetForegroundWindow(self.hwnd)
        chosen = user32.TrackPopupMenu(menu, win.TPM_RIGHTBUTTON | win.TPM_RETURNCMD
                                       | win.TPM_NONOTIFY, x, y, 0, self.hwnd, None)
        user32.DestroyMenu(menu)
        user32.PostMessageW(self.hwnd, win.WM_NULL, 0, 0)
        if chosen:
            self.apply_choice(chosen)

    def apply_choice(self, ident: int) -> None:
        c = self.config
        if ident == MENU_SHOW_AM:
            self.keeper.show()
        elif ident == MENU_HIDE_AM:
            self.keeper.hide("menu")
        elif ident == MENU_QUIT_AM:
            self.keeper.quit_app()
        elif ident in (MENU_GLASS, MENU_CLEAR):
            c["style"] = "glass" if ident == MENU_GLASS else "clear"
            self.draw(force=True)
        elif ident == MENU_CLOSE_TRAY:
            c["close_to_tray"] = not c["close_to_tray"]
        elif ident == MENU_MIN_TRAY:
            c["minimize_to_tray"] = not c["minimize_to_tray"]
        elif ident == MENU_LAUNCH:
            c["launch_with_widget"] = not c["launch_with_widget"]
        elif ident == MENU_ANY_PLAYER:
            c["any_player"] = not c["any_player"]
        elif ident in SIZES:
            self.resize_to(SIZES[ident][1] * self.scale)
            self.draw(force=True)
            self.save_geometry()
        elif ident == MENU_ON_TOP:
            c["on_top"] = not c["on_top"]
            self.apply_layer()
        elif ident == MENU_AUTOSTART:
            set_autostart(not startup_shortcut().exists())
        elif ident == MENU_FOLDER:
            os.startfile(HERE)
        elif ident == MENU_HIDE:
            user32.ShowWindow(self.hwnd, win.SW_HIDE)
        elif ident == MENU_QUIT:
            user32.PostMessageW(self.hwnd, win.WM_CLOSE, 0, 0)
        save_config(c)
        self.refresh_tray()

    # ---------------------------------------------------------- the layer

    def apply_layer(self, borrow: bool = False) -> None:
        on_top = bool(self.config["on_top"])
        user32.SetWindowPos(self.hwnd, win.hwnd(win.HWND_TOPMOST if (on_top or borrow)
                                                else win.HWND_NOTOPMOST),
                            0, 0, 0, 0, win.SWP_NOMOVE | win.SWP_NOSIZE | win.SWP_NOACTIVATE)
        if not on_top and not borrow:
            user32.SetWindowPos(self.hwnd, win.hwnd(win.HWND_BOTTOM), 0, 0, 0, 0,
                                win.SWP_NOMOVE | win.SWP_NOSIZE | win.SWP_NOACTIVATE)

    def desktop_in_front(self) -> bool:
        """The clock's test: is the shell's desktop what is showing at most sample points."""
        left, top, right, bottom = win.monitor_work_area(self.hwnd)
        width, height = right - left, bottom - top
        votes = asked = 0
        for fx, fy in ((0.17, 0.2), (0.5, 0.5), (0.83, 0.8), (0.17, 0.8), (0.83, 0.2)):
            root = win.root_at(int(left + width * fx), int(top + height * fy))
            if not root or root == self.hwnd:
                continue
            asked += 1
            votes += win.class_of(root) in DESKTOP_CLASSES
        return asked >= 3 and votes * 2 > asked

    def watch_desktop(self) -> None:
        """Borrow topmost while Show Desktop is up, so the widget stays on the desktop."""
        front = self.desktop_in_front()
        if front == self._desktop_front:
            self._desktop_streak = 0
            return
        self._desktop_streak += 1
        if self._desktop_streak >= 2:
            self._desktop_streak = 0
            self._desktop_front = front
            self.apply_layer(borrow=front)

    # ------------------------------------------------------------- message

    def _handle_message(self, hwnd, message, wparam, lparam):  # noqa: C901 - a window proc
        try:
            if message == win.WM_SYSCOMMAND and (wparam & win.SC_MASK) == win.SC_MINIMIZE:
                return 0  # part of the desktop: Show Desktop does not minimize it
            if message == win.WM_SIZE and wparam == win.SIZE_MINIMIZED:
                user32.ShowWindow(self.hwnd, win.SW_RESTORE)
                return 0
            if message == win.WM_NCHITTEST:
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                return self._hit_test(x, y)
            if message == win.WM_LBUTTONDOWN:
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                self.click(x, y)
                return 0
            if message == win.WM_NCLBUTTONDBLCLK:
                self.keeper.toggle()
                return 0
            if message in (win.WM_RBUTTONUP, win.WM_NCRBUTTONUP):
                self.open_menu()
                return 0
            if message == WM_SETCURSOR and self.set_cursor():
                return 1
            if message == WM_MOUSEWHEEL:
                if wparam & MK_CONTROL:
                    self.wheel_resize(ctypes.c_short((wparam >> 16) & 0xFFFF).value)
                return 0
            if message == win.WM_CONTEXTMENU:
                return 0
            if message == win.WM_MOUSEMOVE and self._gesture:
                if self._gesture[0] == "scrub":
                    self.track_scrub(ctypes.c_short(lparam & 0xFFFF).value)
                else:
                    self.track_resize()
                return 0
            if message in (win.WM_LBUTTONUP, WM_CAPTURECHANGED) and self._gesture:
                self.end_gesture()
                return 0
            if message in (win.WM_MOUSEMOVE, win.WM_NCMOUSEMOVE):
                self.set_hover(self.pointer_target())
                return 0
            if message == win.WM_EXITSIZEMOVE:
                self.draw(force=True)
                self.save_geometry()
                return 0
            if message == WM_APP_REDRAW:
                self.draw()
                return 0
            if message == WM_APP_COMMAND:
                self.apply_choice(int(wparam))
                return 0
            if message == win.WM_TIMER:
                if not self._gesture:
                    self.set_hover(self.pointer_target())
                self.draw()
                self._desktop_tick = (self._desktop_tick + 1) % DESKTOP_TICKS
                if not self._desktop_tick and self.config.get("stay_on_desktop", True):
                    self.watch_desktop()
                return 0
            if message == win.WM_CLOSE:
                user32.DestroyWindow(self.hwnd)
                return 0
            if message == win.WM_DESTROY:
                self.save_geometry()
                self.quit()
                return 0
        except Exception:
            log("window procedure error:\n" + traceback.format_exc())
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    # ---------------------------------------------------------------- tray

    def tray_menu(self) -> pystray.Menu:
        def post(ident: int):
            return lambda icon, item: user32.PostMessageW(self.hwnd, WM_APP_COMMAND, ident, 0)

        def toggle_apple(icon, item) -> None:
            self.keeper.toggle()
            self.refresh_tray()

        def show_widget(icon, item) -> None:
            user32.ShowWindow(self.hwnd, win.SW_SHOWNA)
            self.apply_layer()
            user32.PostMessageW(self.hwnd, WM_APP_REDRAW, 0, 0)

        entries = [
            pystray.MenuItem(
                lambda item: "Hide Apple Music" if self.keeper.visible() else "Show Apple Music",
                toggle_apple, default=True),
            pystray.MenuItem("Show widget", show_widget),
            pystray.Menu.SEPARATOR,
        ]
        for ident, label, checked in self.menu_items():
            if ident in (MENU_SHOW_AM, MENU_HIDE_AM, MENU_HIDE):
                continue
            if not ident:
                entries.append(pystray.Menu.SEPARATOR)
            else:
                entries.append(pystray.MenuItem(
                    label, post(ident),
                    checked=None if checked is None else (lambda item, on=checked: on)))
        return pystray.Menu(*entries)

    def start_tray(self) -> None:
        self.icon = pystray.Icon("apple-music-widget", tray_image(), TRAY_TITLE,
                                 self.tray_menu())
        threading.Thread(target=self.icon.run, name="tray", daemon=True).start()

    def refresh_tray(self) -> None:
        if self.icon is not None:
            try:
                self.icon.menu = self.tray_menu()
                self.icon.update_menu()
            except Exception:
                log("could not refresh the tray menu:\n" + traceback.format_exc())

    # ----------------------------------------------------------------- run

    def create_window(self, x: int, y: int, width_css: int) -> bool:
        instance = win.kernel32.GetModuleHandleW(None)
        window_class = win.WNDCLASS()
        window_class.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p).value
        window_class.hInstance = instance
        window_class.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(win.IDC_ARROW))
        window_class.lpszClassName = CLASS_NAME
        if not user32.RegisterClassW(ctypes.byref(window_class)):
            if ctypes.get_last_error() != win.ERROR_CLASS_ALREADY_EXISTS:
                log(f"could not register the window class: {ctypes.get_last_error()}")
                return False
        style = win.WS_EX_LAYERED | win.WS_EX_TOOLWINDOW | win.WS_EX_NOACTIVATE
        if self.config["on_top"]:
            style |= win.WS_EX_TOPMOST
        self.hwnd = int(user32.CreateWindowExW(
            style, CLASS_NAME, WINDOW_TITLE, win.WS_POPUP | win.WS_VISIBLE,
            x, y, width_css, surface.height_for(width_css), None, None, instance, None) or 0)
        if not self.hwnd:
            log(f"could not create the window: {ctypes.get_last_error()}")
            return False
        return True

    def quit(self) -> None:
        self.media.stop()
        self.keeper.stop()
        self.seeker.stop()
        self.keeper.release()
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
        user32.KillTimer(self.hwnd, 1)
        user32.PostQuitMessage(0)

    def run(self) -> int:
        if not self.create_window(0, 0, int(surface.WINDOW_W)):
            return 1
        # Placed once the window exists: the scale comes from the monitor it is on.
        self.place(*self.start_geometry())
        self.media.start()
        self.keeper.start()
        self.seeker.start()
        if self.config["launch_with_widget"] and not self.keeper.running():
            self.keeper.launch(hidden=True)
        self.draw(force=True)
        self.apply_layer()
        user32.SetTimer(self.hwnd, 1, TICK_MS, None)
        self.start_tray()
        log(f"widget up ({self.rect()[2]}x{self.rect()[3]} px, scale {self.scale:.2f})")
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        log("widget closed")
        return 0


def render_png(path: Path) -> int:
    """Write the face for what is playing now, over a dusk gradient, in both styles."""
    watcher = MediaWatcher(log, lambda: None, lambda: False)
    watcher.start()
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline and (watcher.snapshot.idle or watcher.snapshot.art is None):
        time.sleep(0.1)
    now = watcher.snapshot
    width = int(surface.WINDOW_W * 1.5)
    height = surface.height_for(width)
    corners = Image.new("RGB", (2, 2))
    corners.putdata([(30, 40, 80), (70, 40, 90), (15, 20, 40), (40, 25, 50)])
    board = corners.resize((width + 40, height * 2 + 50), Image.BICUBIC).convert("RGBA")
    painter = surface.Painter()
    for index, style in enumerate(surface.STYLES):
        view = surface.view_of(now, True, time.time())
        picture = painter.render(view, width, height, style, None)
        board.alpha_composite(surface.straight(picture), (20, 20 + index * (height + 10)))
    board.save(path)
    print(f"wrote {path} ({'idle' if now.idle else now.title})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apple Music now-playing widget")
    parser.add_argument("--render", type=Path, help="write the face as a PNG and exit")
    parser.add_argument("--debug", action="store_true", help="also print the log")
    args = parser.parse_args(argv)

    global DEBUG
    DEBUG = bool(args.debug)
    win.make_dpi_aware()
    install_excepthook()
    if args.render:
        return render_png(args.render)
    if user32.FindWindowW(CLASS_NAME, WINDOW_TITLE):
        print("The Apple Music widget is already running.")
        return 0
    log("starting")
    try:
        return Widget().run()
    except Exception:
        log("widget failed:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    raise SystemExit(main())
