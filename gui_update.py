# -*- coding: utf-8 -*-
"""UpdateMixin —— 从 xianyu_gui.Api 拆出来的一个职责

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


class UpdateMixin:
    def _get_local_version(self):
        """读取本地版本号：优先注册表；源码运行时回落到当前开发版本"""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\XianyuTool') as key:
                version, _ = winreg.QueryValueEx(key, 'Version')
                return version
        except Exception:
            return '1.5.8'

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
