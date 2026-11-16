"""Camada Win32 minima e sem dependencias externas (ctypes puro)."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi

WM_COMMAND = 0x0111
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_CLOSE = 0x0010
WM_MDIACTIVATE = 0x0222
BM_CLICK = 0x00F5
SW_RESTORE = 9

user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowEnabled.argtypes = [wintypes.HWND]
user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


def get_text(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buf, n + 2)
    return buf.value


def get_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def get_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def is_alive(hwnd: int) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(wintypes.HWND(hwnd)))


def is_visible(hwnd: int) -> bool:
    return bool(user32.IsWindowVisible(wintypes.HWND(hwnd)))


def is_enabled(hwnd: int) -> bool:
    return bool(user32.IsWindowEnabled(wintypes.HWND(hwnd)))


def ctrl_id(hwnd: int) -> int:
    return user32.GetDlgCtrlID(wintypes.HWND(hwnd))


def enum_windows(pid: int | None = None, visible_only: bool = True) -> list[tuple[int, str, str]]:
    """Janelas top-level do processo (ou do desktop). Ordem: z-order."""
    out: list[tuple[int, str, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if pid is not None and get_pid(hwnd) != pid:
            return True
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True
        out.append((int(hwnd), get_class(hwnd), get_text(hwnd)))
        return True

    user32.EnumWindows(cb, 0)
    return out


def enum_children(hwnd: int, visible_only: bool = False) -> list[int]:
    out: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(child, _):
        if not visible_only or user32.IsWindowVisible(child):
            out.append(int(child))
        return True

    user32.EnumChildWindows(wintypes.HWND(hwnd), cb, 0)
    return out


def direct_children(hwnd: int) -> list[int]:
    out, child = [], user32.GetWindow(wintypes.HWND(hwnd), 5)  # GW_CHILD
    while child:
        out.append(int(child))
        child = user32.GetWindow(child, 2)  # GW_HWNDNEXT
    return out


def find_children(hwnd: int, cls: str | None = None, cid: int | None = None,
                  text: str | None = None) -> list[int]:
    res = []
    for c in enum_children(hwnd):
        if cls is not None and get_class(c) != cls:
            continue
        if cid is not None and ctrl_id(c) != cid:
            continue
        if text is not None and get_text(c).strip().lower() != text.strip().lower():
            continue
        res.append(c)
    return res


def first_child(hwnd: int, **kw) -> int | None:
    found = find_children(hwnd, **kw)
    return found[0] if found else None


def get_edit_text(hwnd: int, size: int = 2048) -> str:
    buf = ctypes.create_unicode_buffer(size)
    user32.SendMessageW(wintypes.HWND(hwnd), WM_GETTEXT, size,
                        ctypes.cast(buf, ctypes.c_void_p).value)
    return buf.value


def set_edit_text(hwnd: int, value: str) -> None:
    buf = ctypes.create_unicode_buffer(value)
    user32.SendMessageW(wintypes.HWND(hwnd), WM_SETTEXT, 0,
                        ctypes.cast(buf, ctypes.c_void_p).value)


def click(hwnd: int) -> None:
    user32.PostMessageW(wintypes.HWND(hwnd), BM_CLICK, 0, 0)


def close_window(hwnd: int) -> None:
    user32.PostMessageW(wintypes.HWND(hwnd), WM_CLOSE, 0, 0)


def post_command(frame: int, cmd_id: int) -> None:
    user32.PostMessageW(wintypes.HWND(frame), WM_COMMAND, cmd_id, 0)


def activate_mdi_child(mdi_client: int, child: int) -> None:
    user32.SendMessageW(wintypes.HWND(mdi_client), WM_MDIACTIVATE, 0, child)


def bring_to_front(hwnd: int) -> None:
    if user32.IsIconic(wintypes.HWND(hwnd)):
        user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
        time.sleep(0.5)
    user32.SetForegroundWindow(wintypes.HWND(hwnd))


def process_path(pid: int) -> str:
    h = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


# --------------------------------------------------- processos (task manager)
TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def find_process_ids(exe_name: str) -> list[int]:
    """PIDs de processos pelo nome do executavel (ex.: anms.exe)."""
    target = exe_name.lower()
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    out: list[int] = []
    try:
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            exe = ctypes.wstring_at(
                ctypes.addressof(entry) + PROCESSENTRY32W.szExeFile.offset)
            if exe.lower() == target:
                out.append(int(entry.th32ProcessID))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return out


def find_process_paths(exe_name: str) -> list[str]:
    """Caminhos completos dos processos com esse executavel."""
    return [p for p in (process_path(pid) for pid in find_process_ids(exe_name)) if p]
