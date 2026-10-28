# -*- coding: utf-8 -*-
"""统一大模型调用层

支持任何 OpenAI 兼容接口：智谱官方、DeepSeek、魔搭 ModelScope、AIHubMix、
自建中转等。文本模型与视觉模型分开配置 —— 去水印必须用能看图的模型，
而写文案只需要文本模型，两者的最佳选择往往不是同一家。

配置读取优先级：
  1. 环境变量 ZHIPUAI_API_KEY（仅作为 api_key 的兜底）
  2. %LOCALAPPDATA%\\XianyuTool\\api_config.json（用户配置，打包版唯一来源）
  3. 程序目录 api_config.json（源码运行时的开发配置）

配置文件格式（旧版只有 zhipuai_key 也能正常读）：
{
  "zhipuai_key": "兜底 key",
  "text":   {"provider": "zhipu", "base_url": "", "api_key": "", "model": ""},
  "vision": {"provider": "zhipu", "base_url": "", "api_key": "", "model": ""}
}
空值一律回落到智谱官方默认，保证老用户升级后行为不变。
"""
import json
import os
import time

import httpx

CONFIG_FILENAME = 'api_config.json'

# 智谱官方地址（不填 base_url 时使用）
ZHIPU_BASE = 'https://open.bigmodel.cn/api/paas/v4'

DEFAULT_TEXT_MODEL = 'glm-4-flash'
DEFAULT_VISION_MODEL = 'glm-4v-flash'

# 常用服务预设，界面下拉直接选
PRESETS = {
    'zhipu': {
        'label': '智谱 AI（免费，推荐）',
        'base_url': ZHIPU_BASE,
        'text_model': DEFAULT_TEXT_MODEL,
        'vision_model': DEFAULT_VISION_MODEL,
        'apply_url': 'https://open.bigmodel.cn/',
        'vision_ok': True,
        'hint': 'GLM-4-Flash 与 GLM-4V-Flash 免费不限量',
    },
    'modelscope': {
        'label': '魔搭 ModelScope',
        'base_url': 'https://api-inference.modelscope.cn/v1',
        'text_model': 'Qwen/Qwen2.5-72B-Instruct',
        'vision_model': 'Qwen/Qwen2-VL-7B-Instruct',
        'apply_url': 'https://modelscope.cn/my/myaccesstoken',
        'vision_ok': True,
        'hint': '阿里云魔搭社区，有免费额度',
    },
    'deepseek': {
        'label': 'DeepSeek（仅文本）',
        'base_url': 'https://api.deepseek.com/v1',
        'text_model': 'deepseek-chat',
        'vision_model': '',
        'apply_url': 'https://platform.deepseek.com/api_keys',
        'vision_ok': False,
        'hint': 'DeepSeek 不支持图片，去水印需另外配视觉模型',
    },
    'custom': {
        'label': '自定义（OpenAI 兼容）',
        'base_url': '',
        'text_model': '',
        'vision_model': '',
        'apply_url': '',
        'vision_ok': True,
        'hint': '填任意兼容 /chat/completions 的地址，末尾不要带斜杠',
    },
}


# ============================================================
# 配置读写
# ============================================================
def user_config_dir():
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'XianyuTool')


def config_path():
    return os.path.join(user_config_dir(), CONFIG_FILENAME)


def _read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _normalize_section(sec, default_model, fallback_key):
    sec = sec if isinstance(sec, dict) else {}
    base_url = (sec.get('base_url') or '').strip().rstrip('/')
    api_key = (sec.get('api_key') or '').strip()
    model = (sec.get('model') or '').strip()
    return {
        'provider': (sec.get('provider') or 'zhipu').strip(),
        'base_url': base_url or ZHIPU_BASE,
        'api_key': api_key or fallback_key,
        'model': model or default_model,
    }


def load_config():
    """读取并规范化配置，兼容只有 zhipuai_key 的旧格式"""
    raw = _read_json(config_path())
    legacy_key = (raw.get('zhipuai_key') or '').strip()

    if not legacy_key:
        dev_cfg = _read_json(os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILENAME))
        legacy_key = (dev_cfg.get('zhipuai_key') or '').strip()
        # 开发目录里的 key 也作为旧格式的兜底来源
        if not raw and dev_cfg:
            raw = dev_cfg

    env_key = (os.environ.get('ZHIPUAI_API_KEY') or '').strip()
    if env_key and '在此填入' not in env_key:
        legacy_key = env_key

    if '在此填入' in legacy_key:
        legacy_key = ''

    return {
        'legacy_key': legacy_key,
        'text': _normalize_section(raw.get('text'), DEFAULT_TEXT_MODEL, legacy_key),
        'vision': _normalize_section(raw.get('vision'), DEFAULT_VISION_MODEL, legacy_key),
    }


def save_config(text_sec=None, vision_sec=None, legacy_key=None):
    """写配置。未传的字段保持原值"""
    cfg = load_config()
    data = {
        'zhipuai_key': legacy_key if legacy_key is not None else cfg['legacy_key'],
        'text': text_sec if text_sec is not None else cfg['text'],
        'vision': vision_sec if vision_sec is not None else cfg['vision'],
    }
    os.makedirs(user_config_dir(), exist_ok=True)
    with open(config_path(), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return config_path()


def mask_key(key):
    if not key:
        return ''
    return (key[:6] + '……' + key[-4:]) if len(key) > 12 else '已配置'


# ============================================================
# 调用客户端
# ============================================================
class LLMError(RuntimeError):
    pass


class LLM:
    """一个 OpenAI 兼容的对话客户端"""

    def __init__(self, kind, section):
        self.kind = kind          # 'text' | 'vision'
        self.base_url = section['base_url']
        self.api_key = section['api_key']
        self.model = section['model']

    # ---------- 状态 ----------
    def available(self):
        return bool(self.api_key and self.model and self.base_url)

    def describe(self):
        return {
            'kind': self.kind,
            'base_url': self.base_url,
            'model': self.model,
            'key_masked': mask_key(self.api_key),
            'available': self.available(),
        }

    # ---------- 核心请求 ----------
    def chat(self, messages, max_tokens=1200, temperature=0.7, timeout=60, retries=2):
        """发一次对话请求，返回纯文本。失败自动退避重试"""
        if not self.available():
            raise LLMError(
                '未配置%s模型。请在设置里填写该模型的 API 地址、Key 和模型名。'
                % ('文本' if self.kind == 'text' else '视觉')
            )

        url = self.base_url + '/chat/completions'
        headers = {
            'Authorization': 'Bearer ' + self.api_key,
            'Content-Type': 'application/json',
        }
        body = {
            'model': self.model,
            'messages': messages,
            'max_tokens': max_tokens,
            'temperature': round(float(temperature), 2),
        }

        last_err = None
        for attempt in range(retries + 1):
            try:
                with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                    resp = client.post(url, json=body, headers=headers)

                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get('choices') or []
                    if not choices:
                        raise LLMError('接口返回没有 choices：' + resp.text[:200])
                    content = (choices[0].get('message') or {}).get('content')
                    if isinstance(content, list):
                        # 有些服务把内容拆成多段
                        content = ''.join(
                            part.get('text', '') for part in content
                            if isinstance(part, dict)
                        )
                    return (content or '').strip()

                # 明确的鉴权失败不再重试
                if resp.status_code in (401, 403):
                    raise LLMError('鉴权失败（HTTP %d），Key 无效或无权限访问该模型'
                                   % resp.status_code)

                last_err = LLMError('HTTP %d：%s' % (resp.status_code, resp.text[:200]))
                # 429 限流、5xx 服务端错误值得重试
                if resp.status_code not in (429, 500, 502, 503, 504):
                    raise last_err

            except LLMError:
                raise
            except Exception as e:
                last_err = e

            if attempt < retries:
                delay = 2 * (attempt + 1)
                print('  ⚠ %s模型调用失败（%s），%d 秒后重试…'
                      % ('文本' if self.kind == 'text' else '视觉',
                         str(last_err)[:60], delay))
                time.sleep(delay)

        raise LLMError('调用失败（已重试 %d 次）：%s' % (retries, last_err))

    # ---------- 便捷方法 ----------
    def ask(self, prompt, **kwargs):
        return self.chat([{'role': 'user', 'content': prompt}], **kwargs)

    def ask_image(self, image_b64, prompt, mime='image/jpeg', **kwargs):
        """带图片提问。image_b64 为不带前缀的 base64"""
        messages = [{
            'role': 'user',
            'content': [
                {'type': 'image_url',
                 'image_url': {'url': 'data:%s;base64,%s' % (mime, image_b64)}},
                {'type': 'text', 'text': prompt},
            ],
        }]
        return self.chat(messages, **kwargs)


def get_llm(kind='text'):
    """按配置取客户端。kind: 'text' | 'vision'"""
    cfg = load_config()
    section = cfg.get('vision' if kind == 'vision' else 'text')
    return LLM(kind, section)
