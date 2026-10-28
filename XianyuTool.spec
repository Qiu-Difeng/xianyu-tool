# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

# 只打包程序真正需要的运行时资源。
# 注意：
#  1. 不再打包 api_config.json —— 里面有开发者自己的智谱 Key，
#     分发出去等于把 Key 送给每个下载者。用户 Key 改为运行时从
#     %LOCALAPPDATA%\XianyuTool\api_config.json 读取（见 module3_copywriter）。
#  2. 不再打包各个 .py 源文件 —— PyInstaller 已把它们编译进 pyz，
#     datas 里再放一份只是把源码明文暴露给最终用户。
datas = [
    ('gui_embed.html', '.'),
    ('wallpaper.jpg', '.'),
    ('cacert.pem', '.'),
    ('xianyu_icon.ico', '.'),
]
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
    # matplotlib / PyQt* 均未被本程序使用（界面是 pywebview + EdgeChromium），
    # 此前被打进包体，是 811MB 体积的主要来源之一。
    # 注意不要排除 tkinter：保存图片/视频的文件选择框用的就是 tkinter。
    excludes=['matplotlib', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6'],
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
    # 关闭 UPX：UPX 压缩过的 PyInstaller 产物在国内杀软里误报率很高，
    # 用户下载即被删或隔离，得不偿失
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name='XianyuTool',
)
