# -*- mode: python ; coding: utf-8 -*-
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

a = Analysis(
    [os.path.join(ROOT, 'agent_main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=['yaml', 'requests', 'socket'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt6', 'pyqtgraph'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CyberMonAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'assets', 'icon.ico'),
)
