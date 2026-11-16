"""Acesso MSAA (IAccessible) a arvore de objetos do ANM2000.

A SysTreeView32 do ANM nao implementa SelectionItem do UIA, mas expoe
SELFLAG_TAKEFOCUS/TAKESELECTION pelo MSAA, que funciona entre 32/64 bits.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

import comtypes
import comtypes.client

comtypes.client.GetModule("oleacc.dll")
from comtypes.gen import Accessibility  # noqa: E402

from . import winapi

oleacc = ctypes.oledll.oleacc
ole32 = ctypes.windll.ole32
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
ole32.CoInitializeEx.restype = ctypes.c_long

IID_IAccessible = comtypes.GUID("{618736E0-3C3D-11CF-810C-00AA00389B71}")
OBJID_CLIENT = 0xFFFFFFFC
SELFLAG_TAKEFOCUS = 0x1
SELFLAG_TAKESELECTION = 0x2
STATE_SELECTED = 0x2
STATE_FOCUSED = 0x4

COINIT_APARTMENTTHREADED = 0x2
S_OK = 0
S_FALSE = 1
RPC_E_CHANGED_MODE = -2147417850  # ja inicializado em outro modelo de apartamento

_com = threading.local()


def init_com() -> None:
    """Inicializa COM no thread atual (MSAA exige apartamento por thread).

    A GUI inicializa COM no thread principal; qualquer thread de trabalho
    (agendador, execucao, diagnostico) precisa fazer o mesmo.
    """
    if getattr(_com, "ready", False):
        return
    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    if hr not in (S_OK, S_FALSE) and hr != RPC_E_CHANGED_MODE:
        raise OSError(f"falha ao inicializar COM (0x{hr & 0xFFFFFFFF:08X})")
    _com.ready = True


def accessible_from_hwnd(hwnd: int):
    init_com()
    pacc = ctypes.POINTER(Accessibility.IAccessible)()
    hr = oleacc.AccessibleObjectFromWindow(
        wintypes.HWND(hwnd), wintypes.DWORD(OBJID_CLIENT),
        ctypes.byref(IID_IAccessible), ctypes.byref(pacc),
    )
    if hr != 0 or not pacc:
        return None
    return pacc


def child_count(acc) -> int:
    try:
        return int(acc.accChildCount)
    except Exception:
        return 0


def child_name(acc, index: int) -> str:
    try:
        return (acc.accName(index) or "").strip()
    except Exception:
        return ""


def child_state(acc, index: int) -> int:
    try:
        return int(acc.accState(index))
    except Exception:
        return 0


def items(acc) -> list[tuple[int, str, int]]:
    return [(i, child_name(acc, i), child_state(acc, i)) for i in range(1, child_count(acc) + 1)]


def find_item(acc, needle: str) -> tuple[int, str, int] | None:
    low = needle.strip().lower()
    for i, name, state in items(acc):
        if low and low in name.lower():
            return i, name, state
    return None


def select_item(acc, index: int) -> None:
    acc.accSelect(SELFLAG_TAKEFOCUS | SELFLAG_TAKESELECTION, index)


def selected_items(acc) -> list[tuple[int, str, int]]:
    return [(i, n, s) for i, n, s in items(acc) if s & STATE_SELECTED]


def texts(acc, limit: int | None = None) -> list[str]:
    out = []
    for _i, name, _s in items(acc)[: limit or None]:
        if name:
            out.append(name)
    return out


def window_texts(hwnd: int) -> list[str]:
    acc = accessible_from_hwnd(hwnd)
    return texts(acc) if acc else []
