# -*- coding: utf-8 -*-
"""应用日志

设计取舍：不重写各模块里 170 多处 print()，而是给 stdout 挂一个 tee，
让控制台输出同时落盘。这样：
  1. 不改动任何业务代码，避免重构引入新 bug
  2. 打包成 windowed 程序后，print 原本会被吞掉，现在能完整留痕
  3. 出问题可直接让用户把日志文件发回来

日志位置：%LOCALAPPDATA%\XianyuTool\logs\YYYY-MM-DD.log
只保留最近 14 天，自动清理。
"""
import os
import sys
import time
import threading

_LOCK = threading.Lock()
_STATE = {
    'installed': False,
    'dir': None,
    'file': None,
    'path': None,
    'original': None,
}

KEEP_DAYS = 14


def log_dir():
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'XianyuTool', 'logs')


def _today():
    return time.strftime('%Y-%m-%d')


def _prune(directory):
    """删除超过 KEEP_DAYS 天的日志"""
    try:
        cutoff = time.time() - KEEP_DAYS * 86400
        for name in os.listdir(directory):
            if not name.endswith('.log'):
                continue
            path = os.path.join(directory, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                pass
    except Exception:
        pass


class _Tee:
    """把写入同时转发给原 stdout 和日志文件"""

    def __init__(self, original):
        self._original = original

    def write(self, data):
        # 原通道（开发时是控制台，打包后是 devnull，都要兼容）
        try:
            if self._original is not None:
                self._original.write(data)
        except Exception:
            pass

        if not data:
            return 0
        try:
            with _LOCK:
                st = _STATE
                # 跨天自动切到新文件
                if st['file'] is None or not st['path'].endswith(_today() + '.log'):
                    _open_file()
                if st['file'] is not None:
                    st['file'].write(data)
        except Exception:
            # 日志失败绝不影响主流程
            pass
        return len(data)

    def flush(self):
        try:
            if self._original is not None:
                self._original.flush()
        except Exception:
            pass
        try:
            with _LOCK:
                if _STATE['file'] is not None:
                    _STATE['file'].flush()
        except Exception:
            pass

    # 让 print(..., file=sys.stdout) 之类的调用不至于炸
    def isatty(self):
        return False

    def fileno(self):
        try:
            if self._original is not None:
                return self._original.fileno()
        except Exception:
            pass
        raise OSError('no underlying file descriptor')


def _open_file():
    """按当天日期打开（或新建）日志文件"""
    st = _STATE
    try:
        if st['file'] is not None:
            try:
                st['file'].close()
            except Exception:
                pass
            st['file'] = None
        directory = st['dir']
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, _today() + '.log')
        st['file'] = open(path, 'a', encoding='utf-8', buffering=1, errors='replace')
        st['path'] = path
        st['file'].write('\n===== 会话开始 %s =====\n' % time.strftime('%Y-%m-%d %H:%M:%S'))
    except Exception:
        st['file'] = None


def install():
    """安装 tee，让 print 同时写日志"""
    if _STATE['installed']:
        return _STATE['path']
    try:
        directory = log_dir()
        os.makedirs(directory, exist_ok=True)
        _prune(directory)
        _STATE['dir'] = directory
        _STATE['original'] = sys.stdout
        _open_file()
        sys.stdout = _Tee(_STATE['original'])
        _STATE['installed'] = True
        # stderr 一并接管，异常堆栈也要留下
        try:
            sys.stderr = _Tee(sys.stderr)
        except Exception:
            pass
    except Exception:
        return None
    return _STATE['path']


def current_path():
    return _STATE['path']


def note(message):
    """写一条带时间戳的标记（用于关键节点，便于检索）"""
    line = '[%s] %s\n' % (time.strftime('%H:%M:%S'), message)
    try:
        sys.stdout.write(line)
        sys.stdout.flush()
    except Exception:
        pass
