# -*- coding: utf-8 -*-
"""CopyMixin —— 从 xianyu_gui.Api 拆出来的一个职责

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


class CopyMixin:
    def get_copies(self, output_dir):
        copies_dir = os.path.join(output_dir, "copies")
        try:
            with open(os.path.join(copies_dir, "copies.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {"versions": []}

        try:
            from module3_copywriter import filter_banned
        except Exception:
            def filter_banned(t): return []

        versions = [
            {"key": "v1", "label": "V1 词典替换", "text": data.get("v1", ""), "banned": filter_banned(data.get("v1", ""))},
            {"key": "v2", "label": "V2 AI微调", "text": data.get("v2", ""), "banned": filter_banned(data.get("v2", ""))},
            {"key": "v3", "label": "V3 AI重写", "text": data.get("v3", ""), "banned": filter_banned(data.get("v3", ""))},
        ]
        # V1 改了哪些词，前端要显示明细（原词 / 新词 / 可选同义词）。
        # 老版本生成的 copies.json 里没存这个字段，这里按默认同义词补算一遍，
        # 免得用户打开看到「没有替换任何词」却也没法操作。
        changes = data.get("v1_changes")
        if not changes and data.get("original"):
            try:
                from module3_copywriter import v1_dict_replace
                _, changes = v1_dict_replace(data["original"])
            except Exception:
                changes = []
        return {"versions": versions, "title": data.get("title", ""),
                "v1_changes": changes or []}

    def check_copy_status(self, output_dir):
        """检查文案是否生成完成，完成后返回文案数据"""
        try:
            from xianyu_tool import _copy_result
            done = 'data' in _copy_result or 'error' in _copy_result
            if not done:
                return {"done": False}
            if 'error' in _copy_result:
                return {"done": True, "error": _copy_result['error']}
            # 完成了，读取保存的文案
            return self.get_copies(output_dir)
        except Exception:
            # fallback：直接检查文件是否存在
            copies_file = os.path.join(output_dir, "copies", "copies.json")
            if os.path.exists(copies_file):
                return self.get_copies(output_dir)
            return {"done": False}

    def regenerate_copy(self, output_dir, version, custom_prompt=None, v1_choices=None,
                        v1_randomize=False):
        """重新生成指定版本的文案

        三个版本都能独立控制：
          v1: v1_choices 控制每个词用第几个同义词，返回 changes 供前端显示明细
          v2/v3: custom_prompt，不填走默认流程
        """
        try:
            from xianyu_tool import regenerate_copy, save_single_copy

            # 读取原始数据
            copies_dir = os.path.join(output_dir, "copies")
            with open(os.path.join(copies_dir, "copies.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
            title = data.get("title", "")
            desc = data.get("original", "")

            result = regenerate_copy(title, desc, version,
                                     custom_prompt=custom_prompt,
                                     v1_choices=v1_choices,
                                     v1_randomize=v1_randomize)
            if not result:
                return {"success": False, "error": "生成失败"}

            save_single_copy(title, result["text"], version, copies_dir)

            # 更新 JSON（V1 的替换明细也一起存，下次打开还能看到）
            data[version] = result["text"]
            if result.get("changes") is not None:
                data["v1_changes"] = result["changes"]
            with open(os.path.join(copies_dir, "copies.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            out = {"success": True, "text": result["text"], "banned": result["banned"]}
            if result.get("changes") is not None:
                out["changes"] = result["changes"]
            return out
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_copy_history(self, output_dir, version):
        """列出某版本文案的历史备份"""
        try:
            from xianyu_tool import list_copy_history
            items = list_copy_history(output_dir, version)
            return {'success': True, 'items': items}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def restore_copy_history(self, output_dir, version, filename):
        """把历史版本恢复成当前版本"""
        try:
            from xianyu_tool import restore_copy_history
            return restore_copy_history(output_dir, version, filename)
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def delete_copy_history(self, output_dir, version, filename):
        """删除某条历史备份"""
        try:
            from xianyu_tool import delete_copy_history
            return delete_copy_history(output_dir, version, filename)
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def save_copies_to(self, output_dir):
        """弹窗选保存位置，把文案复制过去"""
        import tkinter as tk
        from tkinter import filedialog
        src_dir = os.path.join(output_dir, "copies")
        if not os.path.exists(src_dir):
            return {"success": False, "error": "文件夹不存在"}
        
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        dst_dir = filedialog.askdirectory(title="选择文案保存位置", initialdir=os.path.expanduser('~'))
        root.destroy()
        
        if not dst_dir:
            return {"success": False, "error": "已取消"}
        
        # 同样的 SameFileError 保护：用户可能选中源目录本身
        import shutil
        same_dir = os.path.normcase(os.path.abspath(src_dir)) == os.path.normcase(os.path.abspath(dst_dir))
        saved = 0
        failed = 0
        for f in sorted(os.listdir(src_dir)):
            if not f.endswith(('.txt', '.json')):
                continue
            try:
                shutil.copy2(os.path.join(src_dir, f), os.path.join(dst_dir, f))
                saved += 1
            except shutil.SameFileError:
                pass
            except Exception:
                failed += 1

        if same_dir:
            return {"success": True, "saved": 0, "path": dst_dir,
                    "message": "所选目录就是源目录，文件已在原处"}

        if sys.platform == 'win32':
            try:
                os.startfile(dst_dir)
            except Exception:
                pass
        if failed:
            return {"success": saved > 0, "saved": saved, "path": dst_dir,
                    "error": f"{failed} 个文件复制失败"}
        return {"success": True, "saved": saved, "path": dst_dir}
