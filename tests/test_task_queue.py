# -*- coding: utf-8 -*-
"""批量队列的状态机测试

不碰浏览器、不碰网络，runner 用桩函数代替。
"""
import threading
import time

import pytest

from task_queue import TaskQueue, PENDING, RUNNING, DONE, FAILED


def make_queue(**kw):
    kw.setdefault('min_gap', 0.01)
    kw.setdefault('max_gap', 0.02)
    return TaskQueue(**kw)


def wait_idle(q, timeout=5.0):
    """等队列跑完"""
    end = time.time() + timeout
    while time.time() < end:
        if not q.snapshot()['active']:
            return True
        time.sleep(0.02)
    return False


# ---------------- 入队 ----------------

def test_add_dedup_and_filter():
    q = make_queue()
    n = q.add(['http://a/1', 'http://a/2', '  http://a/1  ', '', '   '])
    assert n == 2, '重复链接和空行应被跳过'
    assert q.snapshot()['pending'] == 2


def test_add_returns_zero_for_empty():
    q = make_queue()
    assert q.add([]) == 0
    assert q.add(['', '  ']) == 0
    assert q.snapshot()['total'] == 0


def test_snapshot_counts():
    q = make_queue()
    q.add(['u1', 'u2', 'u3'])
    s = q.snapshot()
    assert s['total'] == 3
    assert s['pending'] == 3
    assert s['done'] == 0
    assert s['failed'] == 0
    assert s['active'] is False


# ---------------- 执行 ----------------

def test_serial_execution():
    """同一时刻只能跑一条"""
    q = make_queue()
    q.add(['u%d' % i for i in range(4)])
    concurrent = []
    peak = [0]
    lock = threading.Lock()

    def runner(url):
        with lock:
            concurrent.append(1)
            peak[0] = max(peak[0], len(concurrent))
        time.sleep(0.03)
        with lock:
            concurrent.pop()
        return {'success': True, 'title': 't', 'product_id': 'p', 'output_dir': '/d'}

    q.start(runner)
    assert wait_idle(q)
    assert peak[0] == 1, '峰值并发应为 1，实际 %d' % peak[0]
    assert q.snapshot()['done'] == 4


def test_result_classification():
    """成功 / 失败 / 返回 None 三种结果要分对"""
    q = make_queue()
    q.add(['ok', 'fail', 'none'])

    def runner(url):
        if url == 'ok':
            return {'success': True, 'title': '商品', 'product_id': 'p1', 'output_dir': '/x'}
        if url == 'fail':
            return {'success': False, 'error': '下载超时', 'stage': '模块2'}
        return None

    q.start(runner)
    assert wait_idle(q)
    s = q.snapshot()
    assert s['done'] == 1
    assert s['failed'] == 2

    tasks = {t['url']: t for t in s['tasks']}
    assert tasks['ok']['title'] == '商品'
    assert tasks['ok']['product_id'] == 'p1'
    assert tasks['fail']['error'] == '下载超时'
    assert tasks['fail']['stage'] == '模块2'
    assert '链接无效' in tasks['none']['error']


def test_runner_exception_captured():
    q = make_queue()
    q.add(['boom'])

    def runner(url):
        raise RuntimeError('故意炸')

    q.start(runner)
    assert wait_idle(q)
    s = q.snapshot()
    assert s['failed'] == 1
    assert 'RuntimeError' in s['tasks'][0]['error']
    assert s['tasks'][0]['status'] == FAILED


def test_start_rejected_when_running():
    q = make_queue()
    q.add(['u1', 'u2'])

    def slow(url):
        time.sleep(0.1)
        return {'success': True, 'title': 't', 'product_id': 'p', 'output_dir': '/d'}

    assert q.start(slow) is True
    assert q.start(slow) is False, '运行中重复 start 应被拒'
    wait_idle(q)


def test_start_rejected_when_empty():
    q = make_queue()
    assert q.start(lambda u: None) is False


# ---------------- 停止与清理 ----------------

def test_stop_keeps_remaining_pending():
    q = make_queue(min_gap=0.3, max_gap=0.4)
    q.add(['u%d' % i for i in range(5)])
    started = []

    def slow(url):
        started.append(url)
        time.sleep(0.1)
        return {'success': True, 'title': 't', 'product_id': 'p', 'output_dir': '/d'}

    q.start(slow)
    time.sleep(0.05)
    q.stop()
    assert wait_idle(q, timeout=8)

    s = q.snapshot()
    assert len(started) < 5, 'stop 后不应把剩下的全跑完'
    assert s['pending'] > 0, '剩余条目应留在 pending'


def test_retry_failed():
    q = make_queue()
    q.add(['good', 'bad'])

    def runner(url):
        if url == 'bad':
            return {'success': False, 'error': 'x', 'stage': 's'}
        return {'success': True, 'title': 't', 'product_id': 'p', 'output_dir': '/d'}

    q.start(runner)
    assert wait_idle(q)
    assert q.snapshot()['failed'] == 1

    assert q.retry_failed() == 1
    s = q.snapshot()
    assert s['failed'] == 0
    assert s['pending'] == 1

    # 没有失败项时返回 0
    assert q.retry_failed() == 0


def test_clear_finished():
    q = make_queue()
    q.add(['u1', 'u2'])

    def runner(url):
        return {'success': True, 'title': 't', 'product_id': 'p', 'output_dir': '/d'}

    q.start(runner)
    assert wait_idle(q)
    assert q.snapshot()['done'] == 2

    q.clear_finished()
    s = q.snapshot()
    assert s['done'] == 0
    assert s['total'] == 0


def test_reset():
    q = make_queue()
    q.add(['u1'])
    assert q.reset() is True
    assert q.snapshot()['total'] == 0


def test_reset_rejected_when_running():
    q = make_queue()
    q.add(['u1'])

    def slow(url):
        time.sleep(0.15)
        return {'success': True, 'title': 't', 'product_id': 'p', 'output_dir': '/d'}

    q.start(slow)
    assert q.reset() is False, '运行中不应允许 reset'
    wait_idle(q)


# ---------------- 并发安全 ----------------

def test_add_while_running_is_safe():
    """运行中追加任务不应崩，且新任务会被执行"""
    q = make_queue()
    q.add(['a', 'b'])

    def runner(url):
        time.sleep(0.03)
        return {'success': True, 'title': url, 'product_id': url, 'output_dir': '/d'}

    q.start(runner)
    q.add(['c'])
    assert wait_idle(q, timeout=8)

    s = q.snapshot()
    assert s['total'] >= 3
    assert s['done'] >= 2
