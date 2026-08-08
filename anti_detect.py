# -*- coding: utf-8 -*-
"""闲鱼辅助工具 - 防封号策略模块

核心原则：
1. 不频繁请求同一页面
2. 不用同一UA连续请求
3. 加入随机延迟，模拟人类行为
4. 错误后指数退避
5. 不自动化登录（让用户扫码）
6. 不批量抓取（一次一个链接）
"""
import random
import time
import os
import json

# ============================================================
# UA池
# ============================================================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]

def get_random_ua():
    """随机返回一个UA"""
    return random.choice(USER_AGENTS)


# ============================================================
# 频率控制
# ============================================================
class RateLimiter:
    """请求频率控制器"""
    
    def __init__(self, min_interval=2.0, max_interval=5.0, daily_limit=50):
        self.min_interval = min_interval  # 最小间隔（秒）
        self.max_interval = max_interval  # 最大间隔（秒）
        self.daily_limit = daily_limit    # 每日最大请求数
        self.last_request_time = 0
        self.request_count_file = os.path.join(
            os.environ.get('TEMP', os.path.expanduser('~')),
            'xianyu_tool', 'request_count.json'
        )
    
    def _load_count(self):
        """加载今日请求计数"""
        today = time.strftime('%Y-%m-%d')
        try:
            with open(self.request_count_file, 'r') as f:
                data = json.load(f)
            if data.get('date') == today:
                return data.get('count', 0)
        except:
            pass
        return 0
    
    def _save_count(self, count):
        """保存今日请求计数"""
        today = time.strftime('%Y-%m-%d')
        data = {'date': today, 'count': count}
        os.makedirs(os.path.dirname(self.request_count_file), exist_ok=True)
        try:
            with open(self.request_count_file, 'w') as f:
                json.dump(data, f)
        except:
            pass
    
    def check(self):
        """检查是否允许请求，返回(wait_seconds, reason)"""
        # 检查日限额
        count = self._load_count()
        if count >= self.daily_limit:
            return 0, f"已达每日限额({self.daily_limit}次)，请明天再试"
        
        # 检查间隔
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.min_interval:
            wait = self.min_interval - elapsed
            return wait, "请求间隔保护"
        
        return 0, None
    
    async def wait(self):
        """异步等待（如果需要）"""
        wait_sec, reason = self.check()
        if wait_sec > 0:
            print(f"  ⏳ {reason}，等待{wait_sec:.1f}秒...")
            import asyncio
            await asyncio.sleep(wait_sec)
        
        # 随机延迟（模拟人类）
        delay = random.uniform(self.min_interval, self.max_interval)
        import asyncio
        await asyncio.sleep(delay)
        
        self.last_request_time = time.time()
        self._save_count(self._load_count() + 1)
    
    def record(self):
        """记录一次请求（不等待，只计数）"""
        self.last_request_time = time.time()
        self._save_count(self._load_count() + 1)


# ============================================================
# 指数退避
# ============================================================
async def retry_with_backoff(func, max_retries=3, initial_delay=2):
    """
    带指数退避的重试
    delay: 2s → 4s → 8s → 放弃
    """
    import asyncio
    
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except Exception as e:
            if attempt == max_retries:
                raise
            
            delay = initial_delay * (2 ** attempt)
            jitter = random.uniform(0, delay * 0.3)  # 加抖动
            total_delay = delay + jitter
            
            print(f"  ⚠ 第{attempt+1}次失败: {e}，{total_delay:.1f}秒后重试...")
            await asyncio.sleep(total_delay)
    
    return None


# ============================================================
# 行为模拟
# ============================================================
async def human_like_scroll(page):
    """模拟人类滚动行为"""
    import asyncio
    
    # 先等一下
    await asyncio.sleep(random.uniform(1, 2))
    
    # 分段滚动
    scroll_steps = random.randint(3, 6)
    for i in range(scroll_steps):
        scroll_amount = random.randint(200, 600)
        await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
        await asyncio.sleep(random.uniform(0.5, 1.5))
    
    # 偶尔往回滚一点
    if random.random() < 0.3:
        await page.evaluate(f"window.scrollBy(0, -{random.randint(100, 300)})")
        await asyncio.sleep(random.uniform(0.5, 1))


async def random_mouse_move(page):
    """随机移动鼠标（反检测）"""
    import asyncio
    
    for _ in range(random.randint(2, 5)):
        x = random.randint(100, 800)
        y = random.randint(100, 600)
        try:
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.2, 0.8))
        except:
            pass


# ============================================================
# 安全检查
# ============================================================
def check_risk_indicators(page_text):
    """检查页面是否有风控拦截迹象"""
    risk_keywords = [
        '验证码', '滑块', '安全验证', '请拖动',
        '请求过于频繁', '操作太频繁', '请稍后再试',
        '账号异常', '安全提醒', '限制访问',
        'RGV587', '被挤爆啦', '网络不见了',
    ]
    
    for kw in risk_keywords:
        if kw in page_text:
            return True, kw
    
    return False, None


# 全局频率控制器实例
_global_limiter = None

def get_limiter():
    """获取全局频率控制器"""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = RateLimiter(min_interval=3.0, max_interval=6.0, daily_limit=30)
    return _global_limiter
