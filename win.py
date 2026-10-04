"""The Win32 surface both the widget and the Apple Music keeper use, declared once.

Pointers to structs are declared as c_void_p on purpose: passing ctypes structures by reference
works, and the alternative is a paragraph of argtypes for every function.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000

SW_HIDE, SW_SHOWNORMAL, SW_SHOWMINNOACTIVE, SW_SHOWNA, SW_RESTORE, SW_SHOW = 0, 1, 7, 8, 9, 5
HWND_TOPMOST, HWND_NOTOPMOST, HWND_BOTTOM = -1, -2, 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10

HTTRANSPARENT, HTCLIENT, HTCAPTION, HTCLOSE = -1, 1, 2, 20

WM_NULL, WM_DESTROY, WM_CLOSE, WM_QUIT = 0x0, 0x2, 0x10, 0x12
WM_SIZE, WM_CONTEXTMENU, WM_NCHITTEST = 0x5, 0x7B, 0x84
WM_NCMOUSEMOVE, WM_NCLBUTTONDOWN, WM_NCLBUTTONDBLCLK, WM_NCRBUTTONUP = 0xA0, 0xA1, 0xA3, 0xA5
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONUP = 0x200, 0x201, 0x202, 0x205
WM_TIMER, WM_SYSCOMMAND, WM_EXITSIZEMOVE = 0x113, 0x112, 0x232
WM_APP = 0x8000
SC_MINIMIZE, SC_MASK = 0xF020, 0xFFF0
SIZE_MINIMIZED = 1
GA_ROOT = 2

AC_SRC_OVER, AC_SRC_ALPHA, ULW_ALPHA = 0, 1, 2
DIB_RGB_COLORS, BI_RGB = 0, 0
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
MF_STRING, MF_GRAYED, MF_CHECKED, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x800
EVENT_SYSTEM_MINIMIZESTART = 0x16
WINEVENT_OUTOFCONTEXT = 0x0
WH_MOUSE_LL = 14
SMTO_ABORTIFHUNG = 0x2
VK_SHIFT, VK_LBUTTON = 0x10, 0x01
MONITOR_DEFAULTTONEAREST = 2
IDC_ARROW, IDC_HAND = 32512, 32649
ERROR_CLASS_ALREADY_EXISTS = 1410
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                             wintypes.LPARAM)
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                  ctypes.c_long, ctypes.c_long, wintypes.DWORD, wintypes.DWORD)

_H, _U, _I, _P = wintypes.HWND, wintypes.UINT, ctypes.c_int, ctypes.c_void_p
for _dll, _name, _args, _res in (
    (user32, "GetDC", [_H], wintypes.HDC),
    (user32, "ReleaseDC", [_H, wintypes.HDC], _I),
    (user32, "GetDpiForWindow", [_H], _U),
    (user32, "MonitorFromWindow", [_H, wintypes.DWORD], _P),
    (user32, "GetMonitorInfoW", [_P, _P], wintypes.BOOL),
    (user32, "GetCursorPos", [_P], wintypes.BOOL),
    (user32, "SetCapture", [_H], _H),
    (user32, "ReleaseCapture", [], wintypes.BOOL),
    (user32, "GetAsyncKeyState", [_I], ctypes.c_short),
    (user32, "GetKeyState", [_I], ctypes.c_short),
    (user32, "ShowWindow", [_H, _I], wintypes.BOOL),
    (user32, "ShowWindowAsync", [_H, _I], wintypes.BOOL),
    (user32, "IsIconic", [_H], wintypes.BOOL),
    (user32, "IsWindow", [_H], wintypes.BOOL),
    (user32, "IsWindowVisible", [_H], wintypes.BOOL),
    (user32, "GetAncestor", [_H, _U], _H),
    (user32, "GetClassNameW", [_H, wintypes.LPWSTR, _I], _I),
    (user32, "WindowFromPoint", [wintypes.POINT], _H),
    (user32, "GetWindowThreadProcessId", [_H, _P], wintypes.DWORD),
    (user32, "GetMessageW", [_P, _H, _U, _U], _I),
    (user32, "TranslateMessage", [_P], wintypes.BOOL),
    (user32, "DispatchMessageW", [_P], LRESULT),
    (user32, "PostQuitMessage", [_I], None),
    (user32, "PostMessageW", [_H, _U, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
    (user32, "PostThreadMessageW", [wintypes.DWORD, _U, wintypes.WPARAM, wintypes.LPARAM],
     wintypes.BOOL),
    (user32, "SendMessageTimeoutW", [_H, _U, wintypes.WPARAM, wintypes.LPARAM, _U, _U, _P],
     LRESULT),
    (user32, "SetWindowPos", [_H, _H, _I, _I, _I, _I, _U], wintypes.BOOL),
    (user32, "GetWindowRect", [_H, _P], wintypes.BOOL),
    (user32, "SetTimer", [_H, ctypes.c_size_t, _U, _P], ctypes.c_size_t),
    (user32, "KillTimer", [_H, ctypes.c_size_t], wintypes.BOOL),
    (user32, "SetForegroundWindow", [_H], wintypes.BOOL),
    (user32, "CreatePopupMenu", [], wintypes.HMENU),
    (user32, "DestroyMenu", [wintypes.HMENU], wintypes.BOOL),
    (user32, "AppendMenuW", [wintypes.HMENU, _U, ctypes.c_size_t, wintypes.LPCWSTR],
     wintypes.BOOL),
    (user32, "TrackPopupMenu", [wintypes.HMENU, _U, _I, _I, _I, _H, _P], _I),
    (user32, "LoadCursorW", [wintypes.HINSTANCE, _P], wintypes.HANDLE),
    (user32, "SetCursor", [wintypes.HANDLE], wintypes.HANDLE),
    (user32, "UpdateLayeredWindow", [_H, wintypes.HDC, _P, _P, wintypes.HDC, _P,
                                     wintypes.DWORD, _P, wintypes.DWORD], wintypes.BOOL),
    (user32, "DefWindowProcW", [_H, _U, wintypes.WPARAM, wintypes.LPARAM], LRESULT),
    (user32, "SetWinEventHook", [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, _P,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.DWORD],
     wintypes.HANDLE),
    (user32, "UnhookWinEvent", [wintypes.HANDLE], wintypes.BOOL),
    (user32, "SetWindowsHookExW", [_I, _P, wintypes.HINSTANCE, wintypes.DWORD],
     wintypes.HHOOK),
    (user32, "UnhookWindowsHookEx", [wintypes.HHOOK], wintypes.BOOL),
    (user32, "CallNextHookEx", [wintypes.HHOOK, _I, wintypes.WPARAM, wintypes.LPARAM],
     LRESULT),
    (user32, "RegisterClassW", [_P], wintypes.WORD),
    (user32, "CreateWindowExW", [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                 wintypes.DWORD, _I, _I, _I, _I, _H, wintypes.HMENU,
                                 wintypes.HINSTANCE, _P], _H),
    (user32, "DestroyWindow", [_H], wintypes.BOOL),
    (user32, "FindWindowW", [wintypes.LPCWSTR, wintypes.LPCWSTR], _H),
    (user32, "GetSystemMetrics", [_I], _I),
    (gdi32, "CreateCompatibleDC", [wintypes.HDC], wintypes.HDC),
    (gdi32, "CreateDIBSection", [wintypes.HDC, _P, _U, _P, wintypes.HANDLE, wintypes.DWORD],
     wintypes.HBITMAP),
    (gdi32, "SelectObject", [wintypes.HDC, wintypes.HANDLE], wintypes.HANDLE),
    (gdi32, "DeleteObject", [wintypes.HANDLE], wintypes.BOOL),
    (gdi32, "DeleteDC", [wintypes.HDC], wintypes.BOOL),
    (kernel32, "GetModuleHandleW", [wintypes.LPCWSTR], wintypes.HINSTANCE),
    (kernel32, "GetCurrentThreadId", [], wintypes.DWORD),
    (kernel32, "OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
    (kernel32, "CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
    (kernel32, "QueryFullProcessImageNameW", [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                              _P], wintypes.BOOL),
):
    _func = getattr(_dll, _name)
    _func.argtypes = _args
    _func.restype = _res


def hwnd(value: int) -> wintypes.HWND:
    return wintypes.HWND(value or 0)


def class_of(window: int) -> str:
    name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd(window), name, 256)
    return name.value


def process_path(window: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd(window), ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def cursor_position() -> tuple[int, int]:
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def left_button_down() -> bool:
    return bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)


def shift_down() -> bool:
    return bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)


def root_at(x: int, y: int) -> int:
    found = user32.WindowFromPoint(wintypes.POINT(x, y))
    if not found:
        return 0
    return int(user32.GetAncestor(found, GA_ROOT) or found)


def monitor_work_area(window: int = 0) -> tuple[int, int, int, int]:
    monitor = user32.MonitorFromWindow(hwnd(window), MONITOR_DEFAULTTONEAREST)
    if monitor:
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            work = info.rcWork
            return work.left, work.top, work.right, work.bottom
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def make_dpi_aware() -> None:
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass
