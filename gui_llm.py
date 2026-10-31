# -*- coding: utf-8 -*-
"""LlmMixin —— 从 xianyu_gui.Api 拆出来的一个职责

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


class LlmMixin:
    def get_llm_config(self):
        """返回完整配置状态与预设，供界面渲染"""
        try:
            import llm_provider as lp
            cfg = lp.load_config()

            def pack(sec):
                return {
                    'provider': sec['provider'],
                    'base_url': sec['base_url'],
                    'model': sec['model'],
                    'api_key': sec['api_key'],
                    'key_masked': lp.mask_key(sec['api_key']),
                    'available': bool(sec['api_key'] and sec['model']),
                }

            text = pack(cfg['text'])
            vision = pack(cfg['vision'])
            return {
                'success': True,
                'presets': lp.PRESETS,
                'config_path': lp.config_path(),
                'text': text,
                'vision': vision,
                'same_key': text['api_key'] == vision['api_key'] if text['api_key'] and vision['api_key'] else True,
                'configured': text['available'],
            }
        except Exception as e:
            return {'success': False, 'error': str(e), 'configured': False}

    def get_key_status(self):
        """兼容旧接口：只关心文本模型是否可用"""
        info = self.get_llm_config()
        if not info.get('success'):
            return {"configured": False, "masked": "", "error": info.get('error')}
        return {
            "configured": info['text']['available'],
            "masked": info['text']['key_masked'],
            "source": info.get('config_path', ''),
        }

    def save_llm_config(self, text_sec, vision_sec):
        """保存文本/视觉两组模型配置，并立即生效"""
        try:
            import llm_provider as lp

            def clean(sec, kind):
                sec = sec or {}
                base = (sec.get('base_url') or '').strip().rstrip('/')
                key = (sec.get('api_key') or '').strip()
                model = (sec.get('model') or '').strip()
                if key and '在此填入' in key:
                    raise ValueError('请填写真实的 Key，不要用占位符')
                if key and any(c.isspace() for c in key):
                    raise ValueError('Key 里不能有空格或换行')
                if key and len(key) < 12:
                    raise ValueError('Key 太短，可能没复制完整')
                if base and not (base.startswith('http://') or base.startswith('https://')):
                    raise ValueError('API 地址要以 http:// 或 https:// 开头')
                if model and any(c.isspace() for c in model):
                    raise ValueError('模型名里不能有空格')
                return {
                    'provider': (sec.get('provider') or 'zhipu').strip(),
                    'base_url': base or lp.ZHIPU_BASE,
                    'api_key': key,
                    'model': model or (lp.DEFAULT_TEXT_MODEL if kind == 'text'
                                       else lp.DEFAULT_VISION_MODEL),
                }

            text = clean(text_sec, 'text')
            vision = clean(vision_sec, 'vision')

            # 视觉模型可以为空（比如用 DeepSeek 做文案、暂不配视觉）
            if not vision['api_key']:
                vision = {
                    'provider': 'zhipu',
                    'base_url': lp.ZHIPU_BASE,
                    'api_key': '',
                    'model': '',
                }

            path = lp.save_config(text, vision)
            return {
                'success': True,
                'path': path,
                'text_ready': bool(text['api_key']),
                'vision_ready': bool(vision['api_key']),
            }
        except ValueError as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def save_api_key(self, key):
        """兼容旧接口：单个 Key 同时作用于文本与视觉（智谱官方场景）"""
        key = (key or '').strip()
        if not key:
            return {"success": False, "error": "请填写 API Key"}
        import llm_provider as lp
        text = {'provider': 'zhipu', 'base_url': lp.ZHIPU_BASE,
                'api_key': key, 'model': lp.DEFAULT_TEXT_MODEL}
        vision = {'provider': 'zhipu', 'base_url': lp.ZHIPU_BASE,
                  'api_key': key, 'model': lp.DEFAULT_VISION_MODEL}
        return self.save_llm_config(text, vision)

    def test_llm(self, kind='text'):
        """测试指定模型：text 走纯文本请求，vision 走一张内置小图"""
        try:
            import llm_provider as lp
            llm = lp.get_llm(kind)
            if not llm.available():
                return {"success": False,
                        "error": ("未配置文本模型" if kind == 'text' else "未配置视觉模型")}

            if kind == 'text':
                reply = llm.ask('只回复两个字：可用', max_tokens=16,
                                temperature=0.1, timeout=40, retries=1)
                return {"success": True, "reply": reply[:20], "model": llm.model}

            # 视觉：生成一张 64x64 纯色小图让模型描述，验证它确实能处理图片
            import base64
            import io
            from PIL import Image
            buf = io.BytesIO()
            Image.new('RGB', (64, 64), (200, 40, 40)).save(buf, 'JPEG')
            b64 = base64.b64encode(buf.getvalue()).decode()
            reply = llm.ask_image(b64, '这张图是什么颜色？只回答颜色',
                                  max_tokens=16, temperature=0.1,
                                  timeout=40, retries=1)
            return {"success": True, "reply": reply[:20], "model": llm.model}
        except Exception as e:
            msg = str(e)
            if '401' in msg or '403' in msg or '鉴权' in msg:
                return {"success": False, "error": "Key 无效或无权限访问该模型"}
            return {"success": False, "error": msg[:180]}

    def test_api_key(self):
        """兼容旧接口"""
        return self.test_llm('text')
