# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('gui_embed.html', '.'), ('wallpaper.jpg', '.'), ('cacert.pem', '.')]
datas += collect_data_files('certifi')


a = Analysis(
    ['xianyu_gui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['playwright.async_api', 'anti_detect', 'watermark_cleaner', 'simple_lama_inpainting', 'certifi'],
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
    name='XianyuTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['xianyu_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='XianyuTool',
)
