# -*- coding: utf-8 -*-
"""HistoryMixin —— 从 xianyu_gui.Api 拆出来的一个职责

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


class HistoryMixin:
    def list_history(self, limit=50):
        """扫描输出目录，列出处理过的商品（按时间倒序）"""
        try:
            from xianyu_tool import OUTPUT_ROOT
            root = os.path.join(OUTPUT_ROOT, 'output')
            if not os.path.isdir(root):
                return {'success': True, 'items': [], 'total': 0}

            items = []
            for name in os.listdir(root):
                d = os.path.join(root, name)
                if not os.path.isdir(d):
                    continue
                rj = os.path.join(d, 'result.json')
                if not os.path.exists(rj):
                    continue
                try:
                    with open(rj, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    continue

                copies = data.get('copies') or {}
                items.append({
                    'product_id': name,
                    'title': data.get('title') or '(无标题)',
                    'price': data.get('price') or '',
                    'seller': data.get('seller') or '',
                    'desc': data.get('original_desc') or '',
                    'images': len(data.get('original_images') or []),
                    'clean': len(data.get('clean_images') or []),
                    # 历史记录加载后视频 tab 要显示"有/无视频"，缺这个字段就是空白
                    'video_url': data.get('video_url') or '',
                    'output_dir': d,
                    'mtime': os.path.getmtime(rj),
                    'mtime_text': time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(rj))),
                    'elapsed': data.get('elapsed_seconds') or 0,
                    'has_copies': bool(copies.get('v1') or copies.get('v2') or copies.get('v3')),
                })

            items.sort(key=lambda x: x['mtime'], reverse=True)
            total = len(items)
            return {'success': True, 'items': items[:max(1, int(limit))], 'total': total}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def delete_history_item(self, output_dir):
        """删除某条历史记录的结果目录"""
        try:
            from xianyu_tool import OUTPUT_ROOT
            root = os.path.realpath(os.path.join(OUTPUT_ROOT, 'output'))
            target = os.path.realpath(output_dir or '')
            # 只允许删 output 下的子目录，避免误删任意路径
            if not target.startswith(root + os.sep):
                return {'success': False, 'error': '路径不在结果目录内，已拒绝'}
            if not os.path.isdir(target):
                return {'success': False, 'error': '目录不存在'}
            shutil.rmtree(target, ignore_errors=True)
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}
