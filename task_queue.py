# -*- coding: utf-8 -*-
"""批量任务队列

设计取向：
- **串行执行**。闲鱼对同一账号的并发请求敏感，同时跑多条容易触发验证码
  甚至临时限流，因此宁慢勿险。
- **批间随机停顿**。固定间隔容易被识别成脚本，这里用 3~8 秒的随机值。
- **不依赖具体业务**。runner 由调用方注入（GUI 传入 xianyu_tool.run），
  队列本身只管调度与状态，便于单测。
- 状态通过 snapshot() 暴露，界面定时轮询即可。

注意：本模块不 import xianyu_tool，避免循环依赖。
"""
import random
import threading
import time

PENDING = 'pending'
RUNNING = 'running'
DONE = 'done'
FAILED = 'failed'


class TaskQueue:
    def __init__(self, min_gap=3.0, max_gap=8.0):
        self._tasks = []
        self._lock = threading.RLock()
        self._thread = None
        self._stop = False
        self._seq = 0
        self._min_gap = float(min_gap)
        self._max_gap = float(max_gap)
        self._batch_started = None

    # ---------------- 入队 ----------------
    def add(self, urls):
        """把链接列表加入队列，同批内重复链接自动跳过。返回新增条数"""
        added = 0
        with self._lock:
            seen = set(t['url'] for t in self._tasks
                       if t['status'] in (PENDING, RUNNING))
            for raw in urls or []:
                url = (raw or '').strip()
                if not url or url in seen:
                    continue
                self._seq += 1
                self._tasks.append({
                    'id': self._seq,
                    'url': url,
                    'status': PENDING,
                    'stage': '',
                    'error': '',
                    'title': '',
                    'product_id': '',
                    'output_dir': '',
                    'elapsed': 0,
                })
                seen.add(url)
                added += 1
        return added

    # ---------------- 状态 ----------------
    def snapshot(self):
        """返回可直接序列化给界面的状态快照"""
        with self._lock:
            tasks = [dict(t) for t in self._tasks]
            counts = {PENDING: 0, RUNNING: 0, DONE: 0, FAILED: 0}
            for t in tasks:
                counts[t['status']] = counts.get(t['status'], 0) + 1
            alive = self._thread is not None and self._thread.is_alive()
            return {
                'tasks': tasks,
                'total': len(tasks),
                'pending': counts[PENDING],
                'running': counts[RUNNING],
                'done': counts[DONE],
                'failed': counts[FAILED],
                'active': alive,
                'stopping': self._stop and alive,
                'elapsed': round(time.time() - self._batch_started, 1) if self._batch_started else 0,
            }

    # ---------------- 调度 ----------------
    def start(self, runner):
        """启动串行处理。runner(url) 需返回 run() 的结果字典"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            if not any(t['status'] == PENDING for t in self._tasks):
                return False
            self._stop = False
            self._batch_started = time.time()
            self._thread = threading.Thread(target=self._worker, args=(runner,),
                                            name='xianyu-queue', daemon=True)
            self._thread.start()
            return True

    def stop(self):
        """请求停止：当前这条会跑完，后面的不再开始"""
        with self._lock:
            self._stop = True
        return True

    def clear_finished(self):
        """清掉已完成/失败的条目，保留待处理与进行中的"""
        with self._lock:
            self._tasks = [t for t in self._tasks if t['status'] in (PENDING, RUNNING)]
        return True

    def reset(self):
        """整体重置（仅在空闲时允许）"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._tasks = []
            self._seq = 0
            self._batch_started = None
            return True

    # ---------------- 内部 ----------------
    def _next_pending(self):
        with self._lock:
            for t in self._tasks:
                if t['status'] == PENDING:
                    return t
        return None

    def _worker(self, runner):
        try:
            while True:
                with self._lock:
                    if self._stop:
                        break
                task = self._next_pending()
                if task is None:
                    break

                with self._lock:
                    task['status'] = RUNNING
                    task['stage'] = '开始处理'

                t0 = time.time()
                try:
                    result = runner(task['url'])
                    elapsed = round(time.time() - t0, 1)
                    with self._lock:
                        task['elapsed'] = elapsed
                        if isinstance(result, dict) and result.get('success'):
                            task['status'] = DONE
                            task['stage'] = '完成'
                            task['title'] = result.get('title', '')
                            task['product_id'] = str(result.get('product_id', '') or '')
                            task['output_dir'] = result.get('output_dir', '') or ''
                        elif result is None:
                            # run() 解析失败时返回 None
                            task['status'] = FAILED
                            task['stage'] = '解析失败'
                            task['error'] = '链接无效或解析失败'
                        else:
                            task['status'] = FAILED
                            task['stage'] = result.get('stage', '') or '失败'
                            task['error'] = result.get('error', '') or '未知错误'
                except Exception as exc:
                    with self._lock:
                        task['status'] = FAILED
                        task['stage'] = '异常'
                        task['error'] = '%s: %s' % (type(exc).__name__, exc)
                        task['elapsed'] = round(time.time() - t0, 1)

                # 批间随机停顿，降低被风控识别的概率
                if not self._stop and self._next_pending() is not None:
                    time.sleep(random.uniform(self._min_gap, self._max_gap))
        finally:
            with self._lock:
                self._batch_started = None
