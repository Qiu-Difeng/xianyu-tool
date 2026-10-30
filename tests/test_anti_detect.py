# -*- coding: utf-8 -*-
"""防封号模块测试：限流参数、UA 池、风控识别、拟人动作时长"""
import asyncio
import time

import pytest

import anti_detect as ad


# ---------------- 限流参数 ----------------

def test_limiter_intervals():
    lim = ad.RateLimiter()
    assert lim.min_interval == 1.5
    assert lim.max_interval == 3.0
    assert lim.max_interval > lim.min_interval
    assert lim.daily_limit == 50


def test_limiter_first_request_no_wait():
    """首次请求不应该被限流拦住"""
    lim = ad.RateLimiter()
    wait, reason = lim.check()
    assert wait == 0, '首次请求不该等待，实际 %s 秒（%s）' % (wait, reason)


def test_get_limiter_singleton():
    a = ad.get_limiter()
    b = ad.get_limiter()
    assert a is b, '限流器应是单例，否则每次新建等于没限制'


# ---------------- UA 池 ----------------

def test_random_ua_returns_string():
    ua = ad.get_random_ua()
    assert isinstance(ua, str)
    assert len(ua) > 20
    assert 'Mozilla' in ua or 'Chrome' in ua


def test_random_ua_varies():
    """多次调用应出现不同值，否则 UA 固定容易被识别"""
    seen = {ad.get_random_ua() for _ in range(20)}
    assert len(seen) > 1, 'UA 池没生效，20 次调用都是同一个'


# ---------------- 风控识别 ----------------

@pytest.mark.parametrize('text,expected_kw', [
    ('请输入验证码继续', '验证码'),
    ('请拖动滑块完成验证', '滑块'),
    ('请求过于频繁，请稍后再试', '请求过于频繁'),
    ('账号异常，请重新登录', '账号异常'),
])
def test_risk_indicators_hit(text, expected_kw):
    hit, kw = ad.check_risk_indicators(text)
    assert hit is True
    assert kw in text


def test_risk_indicators_normal_page():
    """正常商品页不该误判"""
    normal = '米用家用多功能插座USB排插排 价格 5.99 卖家 张三'
    hit, kw = ad.check_risk_indicators(normal)
    assert hit is False
    assert kw is None


def test_risk_indicators_empty():
    hit, kw = ad.check_risk_indicators('')
    assert hit is False


# ---------------- 拟人动作时长 ----------------

class FakePage:
    """只实现拟人动作会用到的两个方法"""
    async def evaluate(self, js):
        return None

    class mouse:
        @staticmethod
        async def move(x, y):
            return None


def test_human_like_scroll_duration():
    """改动目标：1-3 秒（原来 2.5-11 秒，占单条处理时间 1/4）"""
    t0 = time.time()
    asyncio.run(ad.human_like_scroll(FakePage()))
    cost = time.time() - t0
    assert cost < 3.0, '滚动动作 %.2f 秒，超出预期' % cost
    assert cost > 0.3, '滚动动作太快（%.2f 秒），可能把反检测删掉了' % cost


def test_random_mouse_move_duration():
    t0 = time.time()
    asyncio.run(ad.random_mouse_move(FakePage()))
    cost = time.time() - t0
    assert cost < 1.0, '鼠标动作 %.2f 秒，超出预期' % cost
    assert cost > 0.05, '鼠标动作太快，可能没执行'


def test_anti_detect_total_cost():
    """两项加起来不该超过 3.5 秒"""
    t0 = time.time()
    asyncio.run(ad.human_like_scroll(FakePage()))
    asyncio.run(ad.random_mouse_move(FakePage()))
    assert time.time() - t0 < 3.5


# ---------------- 退避重试 ----------------

def test_retry_with_backoff_succeeds_first_try():
    calls = []

    async def ok():
        calls.append(1)
        return 'done'

    result = asyncio.run(ad.retry_with_backoff(ok, max_retries=3, initial_delay=0.01))
    assert result == 'done'
    assert len(calls) == 1


def test_retry_with_backoff_eventually_succeeds():
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError('暂时失败')
        return 'ok'

    result = asyncio.run(ad.retry_with_backoff(flaky, max_retries=5, initial_delay=0.01))
    assert result == 'ok'
    assert len(calls) == 3


def test_retry_with_backoff_gives_up():
    calls = []

    async def always_fail():
        calls.append(1)
        raise RuntimeError('一直失败')

    with pytest.raises(RuntimeError):
        asyncio.run(ad.retry_with_backoff(always_fail, max_retries=2, initial_delay=0.01))
    assert len(calls) == 3, '应该试 1 次 + 重试 2 次'
