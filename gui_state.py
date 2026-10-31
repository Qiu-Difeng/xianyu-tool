# -*- coding: utf-8 -*-
"""StateMixin —— 从 xianyu_gui.Api 拆出来的一个职责

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


class StateMixin:
    def _ui_state_path(self):
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'XianyuTool', 'ui_state.json')

    def get_ui_state(self):
        """读取界面状态"""
        state = {'guide_seen': False, 'theme': 'system', 'skip_version': ''}
        try:
            path = self._ui_state_path()
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for k in list(state.keys()):
                        if k in data:
                            state[k] = data[k]
        except Exception:
            pass
        return state

    def save_ui_state(self, patch):
        """合并保存界面状态"""
        try:
            state = self.get_ui_state()
            if isinstance(patch, dict):
                for k in ('guide_seen', 'theme', 'skip_version'):
                    if k in patch:
                        state[k] = patch[k]
            path = self._ui_state_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            return {'success': True, 'state': state}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_system_theme(self):
        """读注册表判断 Windows 当前是深色还是浅色"""
        try:
            import winreg
            path = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                light, _ = winreg.QueryValueEx(k, 'AppsUseLightTheme')
            return {'theme': 'light' if light else 'dark'}
        except Exception:
            return {'theme': 'dark'}

    def export_config(self):
        """把大模型配置与主题导出成 JSON 文本

        含明文 API Key，界面侧必须提示用户妥善保管、不要外发。
        """
        try:
            import llm_provider as lp
            cfg = lp.load_config()
            ui = self.get_ui_state()
            data = {
                '_tool': 'XianyuTool',
                '_format': 1,
                '_exported_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                'llm': {
                    'text': cfg['text'],
                    'vision': cfg['vision'],
                },
                'ui': {'theme': ui.get('theme', 'system')},
            }
            return {'success': True,
                    'json': json.dumps(data, ensure_ascii=False, indent=2)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def import_config(self, text):
        """从 JSON 文本恢复配置，校验后复用 save_llm_config 落盘"""
        try:
            if not text or not text.strip():
                return {'success': False, 'error': '请先粘贴配置内容'}
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                return {'success': False, 'error': 'JSON 格式错误：%s' % e}
            if not isinstance(data, dict):
                return {'success': False, 'error': '内容不是有效的配置对象'}
            if data.get('_tool') != 'XianyuTool':
                return {'success': False, 'error': '这不是本工具的配置文件'}

            llm = data.get('llm') or {}
            text_sec = llm.get('text') or {}
            vision_sec = llm.get('vision') or {}
            if not text_sec.get('api_key') and not vision_sec.get('api_key'):
                return {'success': False, 'error': '配置里没有找到可用的 API Key'}

            result = self.save_llm_config(text_sec, vision_sec)
            if not result.get('success'):
                return result

            ui = data.get('ui') or {}
            if ui.get('theme') in ('system', 'dark', 'light'):
                self.save_ui_state({'theme': ui['theme']})

            return {'success': True,
                    'text_ready': result.get('text_ready'),
                    'vision_ready': result.get('vision_ready')}
        except Exception as e:
            return {'success': False, 'error': str(e)}
