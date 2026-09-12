# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the OmniTrade FastAPI backend (desktop sidecar).

Produces a self-contained one-directory bundle so the end user does not need
Python, pip, or a virtual environment installed.
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

# The backend uses many function-local imports (see api/main.py), so eagerly
# collect every submodule of the first-party packages plus uvicorn's dynamic
# protocol/loop modules.
hidden_imports: list[str] = []
for package in ("api", "application", "domain", "storage", "providers", "config"):
    hidden_imports += collect_submodules(package)
hidden_imports += collect_submodules("uvicorn")
hidden_imports += [
    "yfinance",
    "curl_cffi",
    "pandas",
    "numpy",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_core",
    "anyio",
    "peewee",
    "bs4",
    "lxml",
    "multitasking",
]

# Read-only data bundled next to the frozen modules (resolved via BASE_DIR).
datas = [
    (os.path.join(ROOT, "seed_data"), "seed_data"),
    (os.path.join(ROOT, "data_store", "demo_data.json"), "data_store"),
]
datas += collect_data_files("yfinance")
datas += collect_data_files("certifi")

# Keep the bundle lean: these heavy/unused deps are not needed by the API.
excludes = [
    "streamlit",
    "altair",
    "torch",
    "matplotlib",
    "tkinter",
    "PyQt5",
    "PySide6",
    "IPython",
    "notebook",
    "pytest",
]

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, "desktop", "backend", "omnitrade_backend.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="omnitrade-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="omnitrade-backend",
)
