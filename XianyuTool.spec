# -*- mode: python ; coding: utf-8 -*-
# 打包前先把 ui/ 源文件合并成单文件 gui_embed.html。
# pywebview 用 html= 加载时页面是 about:blank，无法引用外部 JS/CSS，
# 所以源码拆开维护、运行时必须是单文件。
import subprocess
import sys as _sys
subprocess.run([_sys.executable, 'build_ui.py'], check=True)
import os
import sys
from PyInstaller.utils.hooks import collect_data_files

# VC++ 运行库（app-local 部署）。
# cv2.pyd 和 python38.dll 都依赖 vcruntime140 / msvcp140，
# 没装 VC++ Redistributable 的电脑会直接报「缺少 vcruntime140.dll」启动失败。
# 微软允许随应用分发这些运行库，三个文件合计约 1MB。
binaries = []
for _dll in ('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll'):
    for _base in (r'C:\Windows\System32', os.path.dirname(sys.executable)):
        _p = os.path.join(_base, _dll)
        if os.path.exists(_p):
            binaries.append((_p, '.'))
            break

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
    binaries=binaries,
    datas=datas,
    # 项目内的模块必须显式列出来：它们在代码里是函数内 import（延迟导入，
    # 避免模块缺失时整个程序起不来），PyInstaller 的静态分析扫不到，
    # 结果就是打包版里没有这些模块，运行时才报 ImportError。
    # 注意不要加 simple_lama_inpainting：它依赖 torch，
    # PyInstaller 会把 torch 整个打进来，包体从 98MB 涨到 1GB 以上，
    # 打包时间也从 2 分钟变成十几分钟。去水印入口已经下掉了，
    # watermark_cleaner.get_lama() 拿不到会自己降级用 OpenCV，不影响主流程。
    hiddenimports=['playwright.async_api', 'anti_detect', 'watermark_cleaner',
                   'certifi',
                   'llm_provider', 'image_search', 'task_queue',
                   'module1_parser', 'module3_copywriter', 'app_logger',
                   # xianyu_gui 拆出来的 9 个 mixin
                   'gui_update', 'gui_template', 'gui_history', 'gui_image',
                   'gui_queue', 'gui_llm', 'gui_state', 'gui_copy', 'gui_misc'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # matplotlib / PyQt* 均未被本程序使用（界面是 pywebview + EdgeChromium），
    # 此前被打进包体，是 811MB 体积的主要来源之一。
    # jedi / IPython / jupyter 是交互式环境生态，Pythonwin 是 pywin32 的 IDE 组件，
    # 本程序都不使用，各占 6MB 以上。
    # 注意不要排除 tkinter：保存图片/视频的文件选择框用的就是 tkinter。
    excludes=['matplotlib', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
              'jedi', 'IPython', 'ipykernel', 'notebook',
              'jupyter', 'jupyter_client', 'jupyter_core',
              'nbformat', 'nbconvert', 'Pythonwin', 'win32ui',
              # torch 只被 simple_lama 用，去水印入口下线了，别打进包里
              'torch', 'torchvision', 'simple_lama_inpainting'],
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
