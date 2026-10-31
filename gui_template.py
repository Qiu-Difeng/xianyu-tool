# -*- coding: utf-8 -*-
"""TemplateMixin —— 从 xianyu_gui.Api 拆出来的一个职责

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


class TemplateMixin:
    def _tpl_path(self):
        import llm_provider as lp
        return os.path.join(lp.user_config_dir(), 'prompt_templates.json')

    def list_prompt_templates(self):
        """读取已保存的提示词模板"""
        try:
            path = self._tpl_path()
            if not os.path.exists(path):
                return {'success': True, 'items': []}
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            items = data.get('templates') if isinstance(data, dict) else None
            return {'success': True, 'items': items or []}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def save_prompt_template(self, name, prompt):
        """保存模板，同名覆盖；最多保留 30 条"""
        try:
            name = (name or '').strip()
            prompt = (prompt or '').strip()
            if not name:
                return {'success': False, 'error': '请填写模板名称'}
            if not prompt:
                return {'success': False, 'error': '请填写提示词内容'}
            if len(name) > 20:
                return {'success': False, 'error': '模板名不要超过 20 个字'}
            if len(prompt) > 500:
                return {'success': False, 'error': '提示词不要超过 500 字'}

            items = self.list_prompt_templates().get('items') or []
            items = [it for it in items if it.get('name') != name]
            items.append({'name': name, 'prompt': prompt})
            items = items[-30:]

            path = self._tpl_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'templates': items}, f, ensure_ascii=False, indent=2)
            return {'success': True, 'items': items}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def delete_prompt_template(self, name):
        """删除指定模板"""
        try:
            name = (name or '').strip()
            items = self.list_prompt_templates().get('items') or []
            left = [it for it in items if it.get('name') != name]
            if len(left) == len(items):
                return {'success': False, 'error': '模板不存在'}
            path = self._tpl_path()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'templates': left}, f, ensure_ascii=False, indent=2)
            return {'success': True, 'items': left}
        except Exception as e:
            return {'success': False, 'error': str(e)}
