# -*- coding: utf-8 -*-
"""闲鱼辅助工具 - 蜡笔小新冬夜壁纸主题 GUI"""
import os
import sys
import json
import time
import base64
import asyncio
import threading
import traceback
import warnings
import tempfile
import shutil
warnings.filterwarnings("ignore")

if getattr(sys, 'frozen', False):
    WORKSPACE = sys._MEIPASS
else:
    WORKSPACE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WORKSPACE)

import webview
import certifi

HTML_FILE = os.path.join(WORKSPACE, "gui_embed.html")

# PyInstaller打包后SSL证书路径修复
# 多重兜底：打包目录cacert.pem → certifi → sys.executable目录 → None(不验证)
_ca_bundle = None
_candidates = []
if getattr(sys, 'frozen', False):
    _candidates.append(os.path.join(sys._MEIPASS, 'cacert.pem'))
    _candidates.append(os.path.join(os.path.dirname(sys.executable), 'cacert.pem'))
else:
    _candidates.append(os.path.join(WORKSPACE, 'cacert.pem'))
for _p in _candidates:
    if _p and os.path.exists(_p):
        _ca_bundle = _p
        break
if not _ca_bundle:
    try:
        _ca_bundle = certifi.where()
    except Exception:
        _ca_bundle = None
if _ca_bundle and os.path.exists(_ca_bundle):
    os.environ['SSL_CERT_FILE'] = _ca_bundle
    os.environ['REQUESTS_CA_BUNDLE'] = _ca_bundle

# 说明：certifi.where() 可能返回打包后不存在的路径，统一以 _ca_bundle 为准，
# 需要证书路径的调用方直接读这个变量。



# ============================================================
# Api 由 9 个 mixin 组合而成，每个 mixin 管一个职责
# ============================================================
from gui_update import UpdateMixin
from gui_template import TemplateMixin
from gui_history import HistoryMixin
from gui_image import ImageMixin
from gui_queue import QueueMixin
from gui_llm import LlmMixin
from gui_state import StateMixin
from gui_copy import CopyMixin
from gui_misc import MiscMixin


class Api(UpdateMixin, TemplateMixin, HistoryMixin, ImageMixin,
          QueueMixin, LlmMixin, StateMixin, CopyMixin, MiscMixin):
    """给前端用的 API 汇总

    原来 51 个方法全塞在这一个类里（1300 行），改一处要翻半天。
    现在按职责拆成 9 个 mixin，每个文件 100-250 行。
    """

    def __init__(self, window_ref):
        self.window = window_ref
        self._last_result = None  # 缓存上次结果供刷新用
        self._update_info = None  # 缓存更新信息
        # 运行互斥：run_tool 的 join 超时后后台线程仍在操作浏览器，
        # 此时若用户再点"开始"，会启动第二个 Chromium 抢同一个 user_data_dir
        self._run_lock = threading.Lock()
        self._running = False
        # 批量队列：与单条任务共用同一个浏览器用户目录，必须互斥
        from task_queue import TaskQueue
        self._queue = TaskQueue()
        self._queue_search_max = 15


window_ref = {}

def build_html():
    if not os.path.exists(HTML_FILE):
        return "<h1>缺少 gui_embed.html</h1>"
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    # 在最早阶段接管 stdout/stderr：打包成 windowed 后 print 原本会被吞掉，
    # 装上 tee 之后所有输出同时落到 %LOCALAPPDATA%\XianyuTool\logs\ 下。
    import app_logger
    app_logger.install()
    app_logger.note('XianyuTool 启动')

    api = Api(window_ref)
    html_content = build_html()
    window = webview.create_window(
        title="闲鱼辅助工具 · 冬夜漫步",
        html=html_content,
        js_api=api,
        width=980,
        height=820,
        min_size=(800, 600),
        text_select=True,
    )
    window_ref['window'] = window

    # 启动时静默检查更新（不阻塞界面）
    def _silent_check_update():
        import time
        time.sleep(3)  # 等待界面加载完成
        try:
            result = api.check_update()
            if result.get('has_update'):
                latest = result.get('latest_version', '')
                window.evaluate_js(
                    'window._onSilentUpdateCheck && window._onSilentUpdateCheck(' +
                    json.dumps(result) + ')'
                )
        except Exception:
            pass

    t_update = threading.Thread(target=_silent_check_update, daemon=True)
    t_update.start()

    webview.start(debug=False)
