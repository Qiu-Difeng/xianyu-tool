# -*- coding: utf-8 -*-
"""ImageMixin —— 从 xianyu_gui.Api 拆出来的一个职责

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


class ImageMixin:
    def collect_extra_images(self, output_dir, sources=None, max_map=None, keyword=''):
        """多源聚合搜补充图（来源和数量都由前端传）

        sources: ['baidu_image', 'baidu_keyword', 'jd'] 的子集
        max_map: {'baidu_image': 15, 'baidu_keyword': 15, 'jd': 10}
        """
        try:
            from xianyu_tool import collect_extra_images
            import asyncio as _aio

            if not output_dir or not os.path.isdir(output_dir):
                return {'success': False, 'error': '没有当前商品目录，先处理一条链接'}

            # 取参考图和标题
            ref_img = None
            for sub in ('clean', 'original'):
                d = os.path.join(output_dir, sub)
                if os.path.isdir(d):
                    cands = sorted(f for f in os.listdir(d)
                                   if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')))
                    if cands:
                        ref_img = os.path.join(d, cands[0])
                        break

            if not keyword:
                rj = os.path.join(output_dir, 'result.json')
                if os.path.exists(rj):
                    try:
                        with open(rj, 'r', encoding='utf-8') as f:
                            keyword = (json.load(f).get('title') or '').strip()
                    except Exception:
                        pass

            if not ref_img and not keyword:
                return {'success': False, 'error': '没有参考图也没有商品标题，无法搜图'}

            loop = _aio.new_event_loop()
            try:
                _aio.set_event_loop(loop)
                result = loop.run_until_complete(
                    collect_extra_images(ref_img, keyword, output_dir,
                                         sources=sources, max_map=max_map))
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
            return result
        except Exception as e:
            return {'success': False, 'error': '%s: %s' % (type(e).__name__, e)}

    def platform_login_status(self):
        """检查京东/淘宝/拼多多的登录状态"""
        try:
            import image_search as isr
            import asyncio as _aio

            loop = _aio.new_event_loop()
            try:
                _aio.set_event_loop(loop)
                # 一次启动浏览器读完三个平台，别每个平台启一次（会崩 driver）
                out = loop.run_until_complete(isr.check_all_platforms())
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
            return {'success': True, 'platforms': out}
        except Exception as e:
            return {'success': False, 'error': '%s: %s' % (type(e).__name__, e)}

    def login_platform(self, platform):
        """打开可见窗口让用户登录，登录成功后 cookie 留在本地"""
        try:
            import image_search as isr
            import asyncio as _aio

            # 队列或单条任务在跑时不要抢浏览器目录
            if self._running or self._queue.snapshot().get('active'):
                return {'success': False, 'error': '有任务正在运行，等它结束再登录'}

            loop = _aio.new_event_loop()
            try:
                _aio.set_event_loop(loop)
                r = loop.run_until_complete(isr.open_platform_login(platform, timeout=240))
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
            return r
        except Exception as e:
            return {'success': False, 'error': '%s: %s' % (type(e).__name__, e)}

    def clean_watermark_box(self, img_src, box, mode='box', output_dir=''):
        """按用户框选的矩形去水印

        img_src: 两种都支持
          - 文件绝对路径
          - data:image/jpeg;base64,... 形式的数据（前端图片列表用的就是这种）
        box: [x1, y1, x2, y2] 像素坐标（原图尺寸）
        mode: 'box' 抹整个框 / 'text' 只抹框内笔画

        返回里带 image（base64 data URL），前端直接换掉图片就行
        """
        try:
            import base64
            import tempfile
            import watermark_cleaner as wc

            if not box or len(box) != 4:
                return {'success': False, 'error': '框选坐标不完整'}
            if not img_src:
                return {'success': False, 'error': '没有图片'}

            tmpdir = tempfile.mkdtemp(prefix='wm_')
            from_data = img_src.startswith('data:')
            if from_data:
                # 前端给的是 base64 数据，落成临时文件再处理
                try:
                    b64 = img_src.split(',', 1)[1]
                except Exception:
                    return {'success': False, 'error': '图片数据格式不对'}
                src_path = os.path.join(tmpdir, 'src.jpg')
                with open(src_path, 'wb') as f:
                    f.write(base64.b64decode(b64))
            else:
                if not os.path.isfile(img_src):
                    return {'success': False, 'error': '图片不存在'}
                src_path = img_src

            out_path = os.path.join(tmpdir, 'out.jpg')
            r = wc.remove_watermark_in_box(src_path, out_path, box, mode=mode)
            if not r.get('success'):
                return r

            with open(out_path, 'rb') as f:
                out_b64 = base64.b64encode(f.read()).decode()
            r['image'] = 'data:image/jpeg;base64,' + out_b64

            # 如果有输出目录，顺便存一份到磁盘（文件名带 _clean）
            if output_dir and os.path.isdir(output_dir):
                try:
                    base_n = 'search_clean_%d.jpg' % int(time.time())
                    dst = os.path.join(output_dir, base_n)
                    with open(dst, 'wb') as f:
                        f.write(base64.b64decode(out_b64))
                    r['out_path'] = dst
                except Exception:
                    pass

            # 清理临时目录
            try:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass
            return r
        except Exception as e:
            return {'success': False, 'error': '%s: %s' % (type(e).__name__, e)}

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
