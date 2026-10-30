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


class Api:
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

    def _get_local_version(self):
        """读取本地版本号：优先注册表；源码运行时回落到当前开发版本"""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\XianyuTool') as key:
                version, _ = winreg.QueryValueEx(key, 'Version')
                return version
        except Exception:
            return '1.4.7'

    def _parse_version(self, tag):
        """将版本号字符串转为可比较的元组，如 'v1.2.3' -> (1, 2, 3)"""
        if not tag:
            return (0, 0, 0)
        tag = tag.strip().lstrip('vV').strip()
        parts = []
        for p in tag.split('.'):
            try:
                parts.append(int(p))
            except ValueError:
                # 取数字前缀
                num = ''
                for ch in p:
                    if ch.isdigit():
                        num += ch
                    else:
                        break
                parts.append(int(num) if num else 0)
        return tuple(parts) if parts else (0, 0, 0)

    def check_update(self):
        """检查GitHub Release是否有新版。返回 dict: has_update, latest_version, download_url, current_version, message"""
        try:
            import httpx
            import ssl
            local_ver = self._get_local_version()
            
            # SSL证书多重兜底（用户电脑有迅游/SteamTools等代理注入根证书，certifi也可能失效）
            # 检查更新只读GitHub公开API，不涉及敏感数据，verify=False安全
            verify = False
            
            resp = httpx.get(
                'https://api.github.com/repos/Qiu-Difeng/xianyu-tool/releases/latest',
                timeout=15,
                headers={'Accept': 'application/vnd.github+json'},
                verify=verify
            )
            if resp.status_code != 200:
                return {'has_update': False, 'error': 'HTTP ' + str(resp.status_code), 'current_version': local_ver}
            data = resp.json()
            tag = data.get('tag_name', '')
            latest_ver = tag.lstrip('vV') if tag else ''
            # 对比版本号
            if self._parse_version(tag) > self._parse_version(local_ver):
                # 找exe安装包下载URL
                download_url = None
                for asset in data.get('assets', []):
                    name = asset.get('name', '').lower()
                    if name.endswith('.exe') and 'setup' in name:
                        download_url = asset.get('browser_download_url')
                        break
                if not download_url:
                    # 没有setup exe，取第一个exe
                    for asset in data.get('assets', []):
                        if asset.get('name', '').lower().endswith('.exe'):
                            download_url = asset.get('browser_download_url')
                            break
                if not download_url:
                    # 没有assets，用zip页面
                    download_url = data.get('html_url', 'https://github.com/Qiu-Difeng/xianyu-tool/releases')
                self._update_info = {
                    'has_update': True,
                    'latest_version': latest_ver,
                    'current_version': local_ver,
                    'download_url': download_url,
                    'release_notes': data.get('body', '')[:500],
                    'release_page': data.get('html_url', ''),
                }
                return self._update_info
            else:
                self._update_info = {'has_update': False, 'latest_version': latest_ver, 'current_version': local_ver}
                return self._update_info
        except Exception as e:
            return {'has_update': False, 'error': str(e), 'current_version': self._get_local_version()}

    def download_update(self):
        """打开浏览器下载更新安装包（程序内下载大文件易超时，改用浏览器）。"""
        try:
            info = self._update_info
            if not info or not info.get('has_update'):
                return {'success': False, 'error': '无可用更新'}
            url = info.get('download_url')
            if not url:
                return {'success': False, 'error': '无下载链接'}
            # 用默认浏览器打开下载页
            import webbrowser
            webbrowser.open(url)
            return {'success': True, 'path': url, 'message': '已打开浏览器下载，下载完成后请运行安装包'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def open_file(self, path):
        """打开文件或文件夹"""
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 提示词模板 ============
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

    # ============ 历史记录 ============
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

    # ============ 批量队列 ============
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

    # ============ 大模型配置 ============
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

    def open_url(self, url):
        """用默认浏览器打开链接（去申请 Key）"""
        try:
            import webbrowser
            webbrowser.open(url)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============ 界面状态（引导/主题/跳过版本）============
    # pywebview 用 html= 直接加载时页面是 about:blank，
    # localStorage 与 sessionStorage 都是 SecurityError，
    # 所以界面状态必须落到后端文件，不能存浏览器里。
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

    # ============ 配置备份 / 恢复 ============
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

    # ============ 日志 ============
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

    def get_images(self, output_dir, subfolder):
        dir_path = os.path.join(output_dir, subfolder)
        if not os.path.exists(dir_path):
            return []
        images = []
        for f in sorted(os.listdir(dir_path)):
            if f.endswith(('.jpg', '.png', '.jpeg', '.webp')):
                p = os.path.join(dir_path, f)
                try:
                    with open(p, "rb") as fp:
                        b64 = base64.b64encode(fp.read()).decode()
                    ext = f.split('.')[-1].lower()
                    mime = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'webp': 'webp'}.get(ext, 'jpeg')
                    images.append(f"data:image/{mime};base64,{b64}")
                except Exception:
                    pass
        return images

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
        return {"versions": versions, "title": data.get("title", "")}

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

    def regenerate_copy(self, output_dir, version, custom_prompt=None):
        """重新生成指定版本的文案；V3支持自定义提示词"""
        try:
            from xianyu_tool import regenerate_copy, save_single_copy
            from module3_copywriter import filter_banned

            # 读取原始数据
            copies_dir = os.path.join(output_dir, "copies")
            with open(os.path.join(copies_dir, "copies.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
            title = data.get("title", "")
            desc = data.get("original", "")

            if version == 'v3' and custom_prompt:
                # V3自定义提示词重写
                from module3_copywriter import v3_ai_custom_rewrite, post_process
                text = post_process(v3_ai_custom_rewrite(title, desc, custom_prompt))
                banned = filter_banned(text)
                result = {"text": text, "banned": banned}
            else:
                result = regenerate_copy(title, desc, version)
            
            if result:
                save_single_copy(title, result["text"], version, copies_dir)
                # 更新JSON
                data[version] = result["text"]
                with open(os.path.join(copies_dir, "copies.json"), "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return {"success": True, "text": result["text"], "banned": result["banned"]}
            return {"success": False, "error": "生成失败"}
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

    def refresh_search(self, output_dir, max_images=15):
        """重新搜索补充图"""
        try:
            from xianyu_tool import search_extra_images

            # 找第一张clean图
            clean_dir = os.path.join(output_dir, "clean")
            search_dir = os.path.join(output_dir, "search")
            first_img = None
            if os.path.exists(clean_dir):
                for f in sorted(os.listdir(clean_dir)):
                    if f.endswith(('.jpg', '.png', '.jpeg')):
                        first_img = os.path.join(clean_dir, f)
                        break
            if not first_img:
                return {"success": False, "error": "无干净图片可用于搜索"}

            result_holder = {}
            def run_in_thread():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    paths, keyword = loop.run_until_complete(
                        search_extra_images(first_img, search_dir, max_images=max_images)
                    )
                    result_holder['paths'] = paths
                    result_holder['keyword'] = keyword
                except Exception as e:
                    result_holder['error'] = str(e)
                finally:
                    loop.close()
            t = threading.Thread(target=run_in_thread, daemon=True)
            t.start()
            t.join(timeout=120)

            if 'error' in result_holder:
                return {"success": False, "error": result_holder['error']}

            return {"success": True, "count": len(result_holder.get('paths', []))}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_images(self, output_dir, subfolder):
        """弹窗选保存位置，把图片复制过去并打开"""
        import tkinter as tk
        from tkinter import filedialog
        src_dir = os.path.join(output_dir, subfolder)
        if not os.path.exists(src_dir):
            return {"success": False, "error": "文件夹不存在"}
        
        # 弹窗选文件夹
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        dst_dir = filedialog.askdirectory(title=f"选择保存位置（{subfolder}）", initialdir=os.path.expanduser('~'))
        root.destroy()
        
        if not dst_dir:
            return {"success": False, "error": "已取消"}
        
        # 复制文件
        # 用户可能直接选中源目录本身，此时 shutil.copy2 会抛 SameFileError，
        # 原实现没有 try，整个接口直接抛异常，前端 Promise 收不到任何结果
        import shutil
        same_dir = os.path.normcase(os.path.abspath(src_dir)) == os.path.normcase(os.path.abspath(dst_dir))
        saved = 0
        failed = 0
        for f in sorted(os.listdir(src_dir)):
            if not f.endswith(('.jpg', '.png', '.jpeg', '.webp', '.txt', '.json')):
                continue
            try:
                shutil.copy2(os.path.join(src_dir, f), os.path.join(dst_dir, f))
                saved += 1
            except shutil.SameFileError:
                pass  # 源与目标同一文件，无需复制
            except Exception:
                failed += 1

        if same_dir:
            return {"success": True, "saved": 0, "path": dst_dir,
                    "message": "所选目录就是源目录，文件已在原处"}

        # 打开目标文件夹
        if sys.platform == 'win32':
            try:
                os.startfile(dst_dir)
            except Exception:
                pass
        if failed:
            return {"success": saved > 0, "saved": saved, "path": dst_dir,
                    "error": f"{failed} 个文件复制失败"}
        return {"success": True, "saved": saved, "path": dst_dir}

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

    def download_video(self, output_dir):
        """下载商品视频"""
        try:
            import asyncio, httpx
            # 从result.json读取视频URL
            result_path = os.path.join(output_dir, "result.json")
            if not os.path.exists(result_path):
                return {"success": False, "error": "无结果数据"}
            with open(result_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            video_url = data.get("video_url", "")
            if not video_url:
                return {"success": False, "error": "该商品没有视频"}
            
            # 弹窗选保存位置
            import tkinter as tk
            from tkinter import filedialog, simpledialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            dst_path = filedialog.asksaveasfilename(
                title="保存视频",
                defaultextension=".mp4",
                initialfile=f"video_{data.get('product_id', 'unknown')}.mp4",
                initialdir=os.path.expanduser('~')
            )
            root.destroy()
            if not dst_path:
                return {"success": False, "error": "已取消"}
            
            # 下载
            async def _dl():
                async with httpx.AsyncClient(follow_redirects=True, timeout=60) as c:
                    resp = await c.get(video_url, headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://h5.m.goofish.com/",
                    })
                    if resp.status_code == 200:
                        with open(dst_path, "wb") as f:
                            f.write(resp.content)
                        return True
                    return False
            
            result_holder = {}
            def run_thread():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result_holder['ok'] = loop.run_until_complete(_dl())
                except Exception as e:
                    result_holder['error'] = str(e)
                finally:
                    loop.close()
            t = threading.Thread(target=run_thread, daemon=True)
            t.start()
            t.join(timeout=60)
            
            if result_holder.get('ok'):
                return {"success": True, "path": dst_path}
            return {"success": False, "error": result_holder.get('error', '下载失败')}
        except Exception as e:
            return {"success": False, "error": str(e)}


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
