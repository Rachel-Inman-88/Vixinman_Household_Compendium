# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build recipe for Compendium Desktop.

Run from the repository root:  pyinstaller desktop/compendium.spec
Produces dist/Compendium/ — a self-contained folder (Compendium.exe on Windows)
that needs no Python installed to run.

datas bundles the non-code assets the app reads at runtime: the Jinja
templates and schema.sql. The pure-Python modules (app, loads_seed,
nm_directory, bpmn_export) are picked up automatically as imports of the
run_compendium entry point; they're also listed as hiddenimports for safety.
"""

import os

block_cipher = None

# Paths are resolved relative to this spec file (in \desktop), so the build
# works no matter which folder PyInstaller is launched from.
ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))   # repo root

a = Analysis(
    [os.path.join(SPECPATH, 'run_compendium.py')],
    pathex=[ROOT],                      # so `import app` (and friends) resolve
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'templates'), 'templates'),   # -> _MEIPASS/templates
        (os.path.join(ROOT, 'schema.sql'), '.'),          # -> _MEIPASS/schema.sql
    ],
    hiddenimports=['app', 'loads_seed', 'nm_directory', 'bpmn_export'],
    hookspath=[],
    runtime_hooks=[],
    # Compendium is pure Flask + SQLite and imports none of these; excluding
    # them keeps the build slim and avoids PyInstaller running their hooks
    # against a possibly-broken system install of a package we never use.
    excludes=['cryptography', 'numpy', 'pandas', 'tkinter'],
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
    name='Compendium',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,          # the console window IS the app; close it to quit
    disable_windowed_traceback=False,
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
    upx=True,
    upx_exclude=[],
    name='Compendium',
)
