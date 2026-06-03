# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

datas = [
    (os.path.join(ROOT, 'config', 'config_default.yaml'), 'config'),
]
binaries = []
hiddenimports = ['yaml', 'sqlite3', 'requests', 'socket']

tmp = collect_all('PyQt6')
datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

tmp = collect_all('pyqtgraph')
datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='CyberMon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'assets', 'icon.ico'),
)
