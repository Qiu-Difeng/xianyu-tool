# -*- coding: utf-8 -*-
"""闲鱼辅助工具 - 蜡笔小新冬夜壁纸主题 GUI"""
import os
import sys
import json
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

    def _get_local_version(self):
        """读取本地版本号：优先注册表，源码运行默认1.0"""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\XianyuTool') as key:
                version, _ = winreg.QueryValueEx(key, 'Version')
                return version
        except Exception:
            return '1.0'

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

    # ============ API Key 配置 ============
    def get_key_status(self):
        """返回 Key 配置状态，供界面判断是否需要在首次启动时引导填写"""
        try:
            from module3_copywriter import resolve_api_key
            key, source = resolve_api_key()
            if not key:
                return {"configured": False, "source": "", "masked": ""}
            masked = (key[:6] + "……" + key[-4:]) if len(key) > 12 else "已配置"
            return {"configured": True, "source": source, "masked": masked}
        except Exception as e:
            return {"configured": False, "source": "", "masked": "", "error": str(e)}

    def save_api_key(self, key):
        """保存用户填写的 API Key，并立即生效（不用重启程序）"""
        try:
            key = (key or "").strip()
            if not key:
                return {"success": False, "error": "请填写 API Key"}
            if '在此填入' in key:
                return {"success": False, "error": "这是占位符，请填真实的 Key"}
            if any(c.isspace() for c in key):
                return {"success": False, "error": "Key 里不能有空格或换行，请重新复制"}
            if len(key) < 20:
                return {"success": False, "error": "Key 太短，可能没复制完整"}

            import module3_copywriter as m3
            cfg_dir = m3._user_config_dir()
            os.makedirs(cfg_dir, exist_ok=True)
            cfg_path = os.path.join(cfg_dir, 'api_config.json')
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump({'zhipuai_key': key}, f, ensure_ascii=False, indent=2)

            # 立即重载客户端，避免用户还要重启一次
            m3.CLIENT = None
            m3.API_KEY, m3.API_KEY_SOURCE = m3.resolve_api_key()
            client = m3.get_client()
            if client is None:
                return {"success": False, "error": "已写入文件但加载失败，请重启程序"}
            return {"success": True, "path": cfg_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def test_api_key(self):
        """用一次极小的请求验证 Key 是否真的可用"""
        try:
            import module3_copywriter as m3
            client = m3.get_client()
            if client is None:
                return {"success": False, "error": "尚未配置 Key"}
            resp = client.chat.completions.create(
                model=m3.MODEL,
                messages=[{"role": "user", "content": "只回复两个字：可用"}],
                max_tokens=16,
                temperature=0.1,
                timeout=30,
            )
            reply = (resp.choices[0].message.content or "").strip()[:20]
            return {"success": True, "reply": reply}
        except Exception as e:
            msg = str(e)
            if '401' in msg or 'auth' in msg.lower() or 'key' in msg.lower():
                return {"success": False, "error": "Key 无效或已过期，请检查"}
            return {"success": False, "error": msg[:160]}

    def open_url(self, url):
        """用默认浏览器打开链接（去申请 Key）"""
        try:
            import webbrowser
            webbrowser.open(url)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def run_tool(self, url, search_max=15):
        # 同一时间只允许一个采集任务，避免超时后前后台两个 Chromium 抢用户数据目录
        with self._run_lock:
            if self._running:
                return {"success": False,
                        "error": "已有任务正在执行，请等当前任务完成后再试"}
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
                except:
                    pass
        return images

    def get_copies(self, output_dir):
        copies_dir = os.path.join(output_dir, "copies")
        try:
            with open(os.path.join(copies_dir, "copies.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            return {"versions": []}

        try:
            from module3_copywriter import filter_banned
        except:
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
