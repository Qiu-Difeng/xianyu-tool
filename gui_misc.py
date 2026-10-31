# -*- coding: utf-8 -*-
"""MiscMixin —— 从 xianyu_gui.Api 拆出来的一个职责

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


class MiscMixin:
    def open_url(self, url):
        """用默认浏览器打开链接（去申请 Key）"""
        try:
            import webbrowser
            webbrowser.open(url)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_log_info(self, tail=200):
        """返回日志路径与最近内容，方便用户把现场发回来排查"""
        try:
            import app_logger
            # install 是幂等的：正常启动时已在 __main__ 装过，
            # 这里兜底，避免未走标准启动路径时接口报「无日志」
            try:
                app_logger.install()
            except Exception:
                pass
            path = app_logger.current_path()
            if not path or not os.path.exists(path):
                return {'success': False, 'error': '本次运行还没有产生日志'}
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            return {
                'success': True,
                'path': path,
                'dir': os.path.dirname(path),
                'size': os.path.getsize(path),
                'content': ''.join(lines[-max(1, int(tail)):]),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def run_tool(self, url, search_max=15):
        # 同一时间只允许一个采集任务，避免超时后前后台两个 Chromium 抢用户数据目录
        with self._run_lock:
            if self._running:
                return {"success": False,
                        "error": "已有任务正在执行，请等当前任务完成后再试"}
            # 队列与单条任务共用同一个浏览器用户目录，不能并行
            if self._queue.snapshot().get('active'):
                return {"success": False,
                        "error": "批量队列正在运行，请先停止队列再单条处理"}
            self._running = True

        in_flight = False
        try:
            from xianyu_tool import run
            result_holder = {}
            def run_in_thread():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(run(url, search_max=search_max))
                    result_holder['result'] = result
                except Exception as e:
                    result_holder['error'] = str(e)
                    result_holder['traceback'] = traceback.format_exc()
                    # 打印到 stdout，经 app_logger 的 tee 落盘，便于事后定位
                    print('[GUI] 任务线程异常: %s' % e)
                    print(result_holder['traceback'])
                finally:
                    loop.close()
                    # 线程真正结束后才放开运行锁（覆盖 join 超时的情况）
                    self._running = False
            t = threading.Thread(target=run_in_thread, daemon=True)
            t.start()
            in_flight = True
            t.join(timeout=600)
            if t.is_alive():
                # 后台仍在跑，保持 _running 为 True，由线程自身结束后复位
                return {"success": False,
                        "error": "处理超时（超过10分钟），后台仍在运行，请稍后查看输出目录"}
            in_flight = False
            self._running = False
            if 'error' in result_holder:
                return {"success": False, "error": result_holder['error']}
            result = result_holder.get('result', {})
            if not result:
                return {"success": False, "error": "无返回结果"}
            self._last_result = result  # 缓存
            return {
                "success": True,
                "title": result.get("title", ""),
                "price": result.get("price", ""),
                "seller": result.get("seller", ""),
                "item_id": str(result.get("product_id", "")),
                "desc": result.get("original_desc", ""),
                "desc_len": len(result.get("original_desc", "")),
                "elapsed": result.get("elapsed_seconds", 0),
                "timings": result.get("timings", {}),
                "output_dir": result.get("output_dir", ""),
                "video_url": result.get("video_url", ""),
            }
        except Exception as e:
            self._running = False
            return {"success": False, "error": str(e)}
        finally:
            # 线程没有真正跑起来（启动失败前就已退出）时才在这里复位；
            # 若 in_flight 为 True 说明跑了但超时，锁要留到线程结束
            if not in_flight:
                self._running = False

    def submit_feedback(self, content, contact=""):
        """用户提交问题反馈"""
        try:
            import time, os, json, platform
            feedback_dir = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'XianyuTool_Feedback')
            os.makedirs(feedback_dir, exist_ok=True)
            feedback = {
                'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                'content': content,
                'contact': contact,
                'machine': platform.node(),
            }
            filename = f'feedback_{int(time.time())}.json'
            with open(os.path.join(feedback_dir, filename), 'w', encoding='utf-8') as f:
                json.dump(feedback, f, ensure_ascii=False, indent=2)
            return {'success': True, 'message': '反馈已保存，感谢！'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
