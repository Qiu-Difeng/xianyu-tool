# -*- coding: utf-8 -*-
"""QueueMixin —— 从 xianyu_gui.Api 拆出来的一个职责

方法实现原样搬过来，没改逻辑。Api 通过多重继承把它合起来。
"""
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


class QueueMixin:
    def queue_add(self, text):
        """把多行文本里的链接加入队列"""
        try:
            raw = (text or '').replace('\r', '\n')
            lines = [ln.strip() for ln in raw.split('\n') if ln.strip()]
            urls = [u for u in lines if 'http' in u.lower()]
            if not urls:
                return {'success': False, 'error': '没有识别到链接，请每行粘贴一条'}
            added = self._queue.add(urls)
            snap = self._queue.snapshot()
            # skipped 按用户实际粘贴的行数算，包含「非链接文字」与「重复链接」，
            # 这样界面能解释「我粘了 4 行为什么只进 2 条」
            return {'success': True, 'added': added, 'total': snap['total'],
                    'skipped': len(lines) - added}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def queue_start(self, search_max=15):
        """启动队列（串行执行）"""
        try:
            if self._running:
                return {'success': False, 'error': '当前有单条任务在执行，请等它结束'}
            snap = self._queue.snapshot()
            if snap['active']:
                return {'success': False, 'error': '队列已在运行中'}

            from xianyu_tool import run as _run
            max_imgs = int(search_max or 15)

            def runner(url):
                # 队列跑在独立线程，需要自己的事件循环
                loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(loop)
                    # 不等文案：实测 V2/V3 单次调用可能超过 100 秒（免费模型排队），
                    # 等它会把单条从 22 秒拖到 140 秒。文案交给后台线程，
                    # 并发数由 xianyu_tool 的信号量限制，界面可稍后刷新查看。
                    return loop.run_until_complete(_run(url, search_max=max_imgs))
                finally:
                    try:
                        loop.close()
                    except Exception:
                        pass

            if not self._queue.start(runner):
                return {'success': False, 'error': '队列为空，或已全部处理完'}
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def queue_stop(self):
        try:
            self._queue.stop()
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def queue_status(self):
        try:
            snap = self._queue.snapshot()
            snap['success'] = True
            # 让界面知道单条任务是否占用着浏览器
            snap['single_running'] = bool(self._running)
            return snap
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def queue_retry_failed(self):
        """把批队列里失败的条目放回待处理"""
        try:
            if self._queue.snapshot().get('active'):
                return {'success': False, 'error': '队列正在运行，请先停止再重试'}
            n = self._queue.retry_failed()
            if n == 0:
                return {'success': False, 'error': '没有失败的条目'}
            return {'success': True, 'count': n}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def queue_clear(self):
        try:
            self._queue.clear_finished()
            return {'success': True, 'total': self._queue.snapshot()['total']}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def queue_reset(self):
        try:
            ok = self._queue.reset()
            return {'success': ok,
                    'error': '' if ok else '队列运行中，请先停止'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def queue_open_output(self, output_dir):
        """打开某个任务的结果目录"""
        try:
            if not output_dir or not os.path.isdir(output_dir):
                return {'success': False, 'error': '结果目录不存在'}
            return self.open_file(output_dir)
        except Exception as e:
            return {'success': False, 'error': str(e)}
