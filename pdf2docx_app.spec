# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds a standalone app on Windows, macOS, and Linux.

PyInstaller cannot cross-compile, so build on each target OS:

    pip install pyinstaller
    pyinstaller pdf2docx_app.spec

Outputs (one-file):
    Windows -> dist/pdf2docx_app.exe
    Linux   -> dist/pdf2docx_app
    macOS   -> dist/PDF Converter.app   (a real bundle with an Info.plist + icon)

The `__main__` guard plus `multiprocessing.freeze_support()` in pdf2docx_app.py
are what make the spawn-based process pool safe when frozen.
"""
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas, binaries, hiddenimports = [], [], []

# pdf2docx, fitz (PyMuPDF), customtkinter and pikepdf ship data files and/or
# dynamically-imported submodules that PyInstaller must be told about.
for pkg in ("pdf2docx", "fitz", "customtkinter", "pikepdf"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# Bundle our own package data (the icon assets under pdfconv/assets) and make
# sure the spawn workers can re-import the app package.
datas += collect_data_files("pdfconv")
hiddenimports += collect_submodules("pdfconv")

# Per-OS application icon. Linux executables don't embed an icon (that's done via
# a .desktop file), so it's left unset there.
if sys.platform.startswith("win"):
    app_icon = "pdfconv/assets/icon.ico"
elif sys.platform == "darwin":
    app_icon = "pdfconv/assets/icon.icns"
else:
    app_icon = None

block_cipher = None

a = Analysis(
    ["pdf2docx_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="pdf2docx_app",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # GUI app: no console window. In CLI mode the entry point
                     # attaches to the parent terminal (AttachConsole) so CLI
                     # output is visible when launched from a console.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=app_icon,
)

# macOS: wrap the one-file executable in a proper .app bundle so it gets a Dock
# icon, Retina support and a sensible identity. (Distribution to other Macs also
# needs signing + notarization — see the README; not required for personal use.)
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="PDF Converter.app",
        icon=app_icon,
        bundle_identifier="com.pdfconverter.app",
        info_plist={
            "CFBundleName": "PDF Converter",
            "CFBundleDisplayName": "PDF Converter",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.13.0",
        },
    )
