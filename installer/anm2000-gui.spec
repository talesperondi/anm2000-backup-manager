# -*- mode: python ; coding: utf-8 -*-
"""Build da interface grafica (onedir) do ANM2000 Backup Manager."""

import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
comtypes_datas, comtypes_binaries, comtypes_hidden = collect_all("comtypes")

a = Analysis(
    [os.path.join(ROOT, "gui.py")],
    pathex=[ROOT],
    binaries=comtypes_binaries,
    datas=comtypes_datas + [(os.path.join(ROOT, "assets", "app.ico"), "assets")],
    hiddenimports=comtypes_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ANM2000 Backup Manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "assets", "app.ico"),
    version=os.path.join(ROOT, "installer", "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ANM2000 Backup Manager",
)
