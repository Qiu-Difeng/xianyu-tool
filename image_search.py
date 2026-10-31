# -*- coding: utf-8 -*-
"""以图搜图：用百度识图找同类商品图片

为什么走浏览器而不是直接调接口：
graph.baidu.com/upload 直接 POST 会被拒（status=1, msg=Reject），
需要页面上的 csrf 和 cookie。所以用 Playwright 打开识图首页模拟上传，
再从结果页的 ajax/pcsimi 接口里取图。

能拿到的图是 500px 宽的缩略图（改 CDN 的 w/h 参数无效，只返回原尺寸），
作为商品补充图够用——闲鱼手机端展示宽度约 750px。
"""
import asyncio
import io
import os
import re

import httpx

GRAPH_HOME = 'https://graph.baidu.com/pcpage/index?tpl_from=pc'

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


async def search_by_image(image_path, max_images=15, timeout=40, keywords_hint=''):
    """上传一张图，返回百度识图找到的相似图片 URL 列表

    image_path: 本地图片路径
    max_images: 最多返回多少条
    timeout: 整体超时（秒）
    keywords_hint: 百度识别出的商品名，通过这个参数带回来（可变传参不优雅，
                   这里返回二元组更直白）

    返回 (urls, detected_keyword)
    """
    if not image_path or not os.path.isfile(image_path):
        print('  ⚠ 参考图不存在，跳过搜图')
        return [], ''

    from playwright.async_api import async_playwright

    captured = {}
    detected = ''

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled'])
        try:
            ctx = await browser.new_context(user_agent=UA, viewport={'width': 1440, 'height': 900})
            page = await ctx.new_page()

            async def on_response(resp):
                if 'ajax/pcsimi' not in resp.url:
                    return
                try:
                    body = await resp.text()
                except Exception:
                    return
                if len(body) > 200 and 'list' in body:
                    captured['pcsimi'] = body

            page.on('response', lambda r: asyncio.create_task(on_response(r)))

            await page.goto(GRAPH_HOME, wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(1.2)

            n = await page.locator('input[type=file]').count()
            if not n:
                print('  ⚠ 百度识图页面结构变了，找不到上传框')
                return [], ''

            await page.locator('input[type=file]').first.set_input_files(image_path)

            # 等结果接口回来
            waited = 0.0
            while waited < timeout and 'pcsimi' not in captured:
                await asyncio.sleep(0.5)
                waited += 0.5

            # 百度会在页面里写"图中可能是 xxx"
            try:
                text = await page.inner_text('body')
                m = re.search(r'图中可能是\s*([^\n]{2,20})', text)
                if m:
                    detected = m.group(1).strip()
            except Exception:
                pass

        finally:
            try:
                await browser.close()
            except Exception:
                pass

    if 'pcsimi' not in captured:
        print('  ⚠ 没等到识图结果（%.0f 秒超时）' % timeout)
        return [], detected

    import json
    try:
        data = json.loads(captured['pcsimi'])
    except Exception:
        return [], detected

    items = (data.get('data') or {}).get('list') or []
    urls = []
    seen = set()
    for it in items:
        u = (it.get('thumbUrl') or '').strip()
        if not u:
            continue
        # 去掉尺寸参数，统一按原尺寸取（带了也无效，留着更容易去重）
        key = re.sub(r'[?&](w|h)=\d+', '', u)
        if key in seen:
            continue
        seen.add(key)
        urls.append(u if u.startswith('http') else 'https:' + u)
        if len(urls) >= max_images:
            break

    return urls, detected


async def download_images(urls, output_dir, timeout=15):
    """并发下载图片，返回成功保存的本地路径列表"""
    os.makedirs(output_dir, exist_ok=True)
    if not urls:
        return []

    from concurrent.futures import ThreadPoolExecutor

    headers = {'User-Agent': UA, 'Referer': 'https://graph.baidu.com/'}

    def _one(args):
        idx, url = args
        path = os.path.join(output_dir, 'search_%02d.jpg' % idx)
        try:
            r = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
            if r.status_code != 200 or len(r.content) < 3000:
                return None
            # 统一转 JPEG，顺便校验是不是真图片
            from PIL import Image
            im = Image.open(io.BytesIO(r.content))
            if im.width < 200 or im.height < 200:
                return None
            im.convert('RGB').save(path, 'JPEG', quality=92)
            return path
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(_one, enumerate(urls)))

    return [p for p in results if p]


def _dhash(path, size=8):
    """算图片的 dHash（差值哈希），返回 64 位整数

    做法：缩到 (size+1) x size 的灰度图，逐行比较相邻像素，
    左 > 右 记 1，否则记 0。用这个判断"是不是同一张图"比文件大小可靠得多——
    同一张图不同尺寸/不同压缩率，hash 几乎不变。
    """
    try:
        from PIL import Image
        im = Image.open(path).convert('L').resize((size + 1, size), Image.LANCZOS)
    except Exception:
        return None
    px = list(im.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            left = px[row * (size + 1) + col]
            right = px[row * (size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def _hamming(a, b):
    """两个 hash 有几位不一样"""
    if a is None or b is None:
        return 999
    return bin(a ^ b).count('1')


def screenshot_score(path):
    """给"像不像文章截图"打分，0 = 完全不像，1 = 很像

    为什么要打分而不是直接判断：纯白底的商品图和文字截图在颜色统计上
    几乎重合（都是大面积白 + 低饱和），一刀切会误删好图。
    这里只输出可疑程度，由调用方决定是丢弃还是排到后面。

    三个特征：
    - 顶部大块纯色（放标题的横幅）
    - 颜色种类特别多（彩色标题栏 + 白底 + 图标，量化后 100+ 种）
    - 平均饱和度极低（黑白文档）
    """
    try:
        from PIL import Image
        im = Image.open(path).convert('RGB')
    except Exception:
        return 0.0

    w, h = im.size
    if h < 80 or w < 80:
        return 0.0

    score = 0.0

    # 1) 顶部 12% 的主色占比
    band = im.crop((0, 0, w, max(20, int(h * 0.12)))).resize((60, 12), Image.LANCZOS)
    px = list(band.getdata())
    cnt = {}
    for r, g, b in px:
        k = (r // 32, g // 32, b // 32)
        cnt[k] = cnt.get(k, 0) + 1
    top_ratio = max(cnt.values()) / float(len(px)) if px else 0

    # 2) 整图量化色数 + 平均饱和度
    small = im.resize((80, 80), Image.LANCZOS)
    colors = len(set((r // 32, g // 32, b // 32) for r, g, b in small.getdata()))
    hsv_px = list(small.convert('HSV').getdata())
    s_avg = sum(p[1] for p in hsv_px) / float(len(hsv_px)) if hsv_px else 0

    # 顶部纯色 + 低饱和 = 像标题横幅
    if top_ratio > 0.70 and s_avg < 12:
        score += 0.5
    # 颜色种类异常多（彩色标题栏那种）
    if colors > 100:
        score += 0.4
    # 接近黑白的文档
    if s_avg < 8:
        score += 0.2

    return min(1.0, score)


def dedupe_by_content(paths, max_distance=6, min_width=200, drop_score=0.75):
    """按图片内容去重，保留清晰度最高的那张

    原来的 dedupe_by_size 只能挡掉"文件大小完全一样"的重复，
    而搜索引擎返回同一张图经常是不同尺寸（500 宽 / 667 宽），大小不同就漏了。
    换成 dHash 后，同一张图不管多大都能认出来。

    同时按 screenshot_score 排序：可疑的文章截图排到最后，但**不删**——
    因为纯白底的商品图也会被判可疑，删了会误伤。

    返回 [(path, width, score)]，按"可用程度"从高到低排
    """
    if not paths:
        return []

    items = []
    for pth in paths:
        if not os.path.isfile(pth):
            continue
        try:
            from PIL import Image
            with Image.open(pth) as im:
                w, h = im.size
        except Exception:
            continue
        if w < min_width:
            continue
        sc = screenshot_score(pth)
        if sc >= drop_score:      # 非常确定是截图的才丢
            continue
        items.append({'path': pth, 'w': w, 'px': w * h,
                      'score': sc, 'hash': _dhash(pth)})

    # 先按像素总量降序，去重时保留最清晰的那张
    items.sort(key=lambda x: x['px'], reverse=True)
    kept = []
    for it in items:
        if any(_hamming(it['hash'], k['hash']) <= max_distance for k in kept):
            continue
        kept.append(it)

    # 再去掉重复后，按"截图可疑度"升序排（正常图在前）
    kept.sort(key=lambda x: (x['score'], -x['px']))
    return [(k['path'], k['w'], round(k['score'], 2)) for k in kept]


def dedupe_by_size(paths, min_kb=10):
    """按文件大小粗略去重（同一张图不同 URL 常见）"""
    seen = set()
    out = []
    for p in paths:
        try:
            size = os.path.getsize(p)
        except Exception:
            continue
        if size < min_kb * 1024:
            continue
        if size in seen:
            os.remove(p)
            continue
        seen.add(size)
        out.append(p)
    return out

# ============================================================
# 来源 2：百度图片（关键词搜图）
# ============================================================

async def search_by_keyword(keyword, max_images=30, timeout=30):
    """用关键词在百度图片搜图，返回图片 URL 列表

    和 search_by_image 的区别：那个是以图搜图（要上传参考图，更精准），
    这个是按文字搜（量大，但可能有不相关的）。两者互补。

    不需要登录，也不需要 csrf。
    """
    if not keyword or not keyword.strip():
        return []

    from playwright.async_api import async_playwright
    from urllib.parse import quote

    urls = []
    seen = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled'])
        try:
            ctx = await browser.new_context(user_agent=UA, viewport={'width': 1440, 'height': 900})
            page = await ctx.new_page()

            search_url = 'https://image.baidu.com/search/index?tn=baiduimage&word=' + quote(keyword)
            try:
                await page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
            except Exception:
                pass
            await asyncio.sleep(2.5)

            # 滚两次触发懒加载
            for _ in range(2):
                try:
                    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                except Exception:
                    pass
                await asyncio.sleep(1.8)

            try:
                srcs = await page.eval_on_selector_all(
                    'img',
                    'els => els.map(e => e.src || e.getAttribute("data-imgurl") || "")')
            except Exception:
                srcs = []

            for u in srcs:
                if not u or not u.startswith('http'):
                    continue
                low = u.lower()
                # 过滤站点图标、占位图
                if any(k in low for k in ['logo', 'icon', '.svg', 'static', 'loading', 'blank']):
                    continue
                if len(u) < 30:
                    continue
                key = re.sub(r'[?&](w|h|fmt)=\w+', '', u)
                if key in seen:
                    continue
                seen.add(key)
                urls.append(u)
                if len(urls) >= max_images:
                    break
        finally:
            try:
                await browser.close()
            except Exception:
                pass

    return urls


# ============================================================
# 来源 3~5：电商平台买家评价图（实测不可用，保留尝试逻辑）
# ============================================================

# ============================================================
# 多源聚合
# ============================================================

# 京东方案已下线（2026-10-31）：
#   1. 以图搜图能通但不稳定（手动跑通 1 次拿到 30 个同款，自动化后连续 5 次失败）
#   2. 关键词搜图不精准（拿「插排」去搜会混进黑色款等无关商品）
#   3. 评价图带红色「JD.COM京东」水印，位置随机，去水印后痕迹明显
# 淘宝/拼多多同样做不通：淘宝的上传 input 在前端框架的受控组件里，
# CDP 设文件后 el.files.length 还是 0；拼多多要 anti_content 签名。
# 所以只保留两个百度源，它们抓回来的图不带水印。
# 只保留百度识图（以图搜图）。百度图片（关键词搜图）已移除：
# 它按文字搜，拿回来的图一半是小红书/公众号文章截图，
# 而且和闲鱼商品经常不是同款（用户反馈「混进黑色款」主要来自这里）。
# 以图搜图是按图找同款，精准度高得多。
SOURCE_ORDER = ['baidu_image']

SOURCE_LABELS = {
    'baidu_image': '百度识图',
}

# 每个来源的默认抓取数量，前端可覆盖
SOURCE_DEFAULT_MAX = {
    'baidu_image': 15,
}


async def collect_all_sources(product_image, keyword='', max_per_source=15,
                              sources=None, max_map=None):
    """按顺序从各个来源收图，某个源失败不影响其他源

    返回列表，每项：
      {source, name, status, images, message, cost}
      status: ok / empty / failed / unavailable / skipped

    调用方按返回顺序展示即可（已经按 SOURCE_ORDER 排好）。
    """
    # sources 为 None 才默认全开；传空列表表示"一个都不要"（前端全取消勾选）
    enabled = [x for x in (SOURCE_ORDER if sources is None else sources)
               if x in SOURCE_ORDER]
    max_map = max_map or {}

    def _max_for(src):
        """取某个源的数量上限：优先用传入的映射，否则用默认"""
        v = max_map.get(src)
        try:
            v = int(v)
        except (TypeError, ValueError):
            v = None
        if v is None or v <= 0:
            v = max_per_source or SOURCE_DEFAULT_MAX.get(src, 15)
        return max(1, min(v, 100))

    results = []

    # --- 源 1：百度识图（以图搜图）---
    if 'baidu_image' in enabled and product_image:
        t0 = asyncio.get_event_loop().time()
        try:
            urls, detected = await search_by_image(product_image, max_images=_max_for('baidu_image'))
            cost = asyncio.get_event_loop().time() - t0
            if urls:
                results.append({
                    'source': 'baidu_image',
                    'name': SOURCE_LABELS['baidu_image'],
                    'status': 'ok',
                    'images': urls,
                    'message': ('识别为「%s」' % detected) if detected else '',
                    'cost': round(cost, 1),
                })
                # 识图能识别出商品名，后面关键词搜图可以复用
                if not keyword and detected:
                    keyword = detected
            else:
                results.append({
                    'source': 'baidu_image', 'name': SOURCE_LABELS['baidu_image'],
                    'status': 'empty', 'images': [],
                    'message': '没找到相似图（可能图片太小或太模糊）',
                    'cost': round(cost, 1),
                })
        except Exception as e:
            results.append({
                'source': 'baidu_image', 'name': SOURCE_LABELS['baidu_image'],
                'status': 'failed', 'images': [],
                'message': '%s: %s' % (type(e).__name__, e), 'cost': 0,
            })
    elif 'baidu_image' in enabled:
        results.append({
            'source': 'baidu_image', 'name': SOURCE_LABELS['baidu_image'],
            'status': 'skipped', 'images': [],
            'message': '没有参考图，跳过以图搜图', 'cost': 0,
        })

    # 按预定义顺序稳定排序
    order = {k: i for i, k in enumerate(SOURCE_ORDER)}
    results.sort(key=lambda x: order.get(x['source'], 99))
    return results


def summarize_sources(results):
    """把多源结果压成一句人话，给界面提示用"""
    # count 是下载去重后的真实数量；没有 count 时才退回 URL 条数
    ok_imgs = sum(r.get('count', len(r.get('images') or []))
                  for r in results if r['status'] == 'ok')
    ok_src = [r['name'] for r in results if r['status'] == 'ok']
    bad = [r['name'] for r in results if r['status'] in ('failed', 'unavailable')]
    parts = []
    if ok_imgs:
        parts.append('从 %s 收到 %d 张' % ('、'.join(ok_src), ok_imgs))
    else:
        parts.append('没能收到图片')
    if bad:
        parts.append('%s 不可用' % '、'.join(bad))
    return '；'.join(parts)

# ============================================================
# 电商平台：登录 + 抓买家评价图
# ============================================================
# 三个平台的网页版都要求登录才能看商品和评价（实测：
# 京东 PC 搜索页跳登录、移动版 403、club.jd.com 评价接口 444；
# 拼多多直接弹手机验证码登录框；淘宝/天猫要登录态 + mtop 签名）。
#
# 所以走"用户登录一次，之后复用登录态"的路子：
# 程序已经有一份持久化浏览器配置（和闲鱼共用），登录后 cookie 就留下了。

PLATFORM_LOGIN = {
    'jd': {
        'name': '京东',
        'login_url': 'https://passport.jd.com/new/login.aspx',
        'home': 'https://www.jd.com/',
        'search': 'https://search.jd.com/Search?keyword={kw}&enc=utf-8',
        # 京东登录成功的标志：thor（登录票据）或 pin（用户名）
        'cookies': ('thor', 'pin'),
    },

}


def upgrade_jd_image(url):
    """把京东评价图的缩略图地址换成原图

    京东 CDN 用路径里的尺寸前缀控制大小：
      //img30.360buyimg.com/n0/s128x96_jfs/t1/.../x.jpg   ← 128x96，才 1.7KB
    去掉 s128x96_ 这段就是原图：
      //img30.360buyimg.com/n0/jfs/t1/.../x.jpg           ← 800x800，57KB
    """
    if not url:
        return url
    if url.startswith('//'):
        url = 'https:' + url
    return re.sub(r'/s\d+x\d+_', '/', url)


def platform_logged_in(cookies, platform):
    """根据 cookie 判断平台是否已登录"""
    cfg = PLATFORM_LOGIN.get(platform)
    if not cfg:
        return False
    names = {c.get('name') for c in cookies}
    return any(n in names for n in cfg['cookies'])


async def check_platform_login(platform, user_data_dir=None):
    """只检查登录态，不打开可见窗口（用无头模式读一遍 cookie）"""
    from playwright.async_api import async_playwright

    cfg = PLATFORM_LOGIN.get(platform)
    if not cfg:
        return {'platform': platform, 'logged_in': False, 'message': '不支持的平台'}

    async with async_playwright() as p:
        try:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir or _default_profile_dir(),
                headless=True,
                args=['--disable-blink-features=AutomationControlled'])
        except Exception as e:
            return {'platform': platform, 'logged_in': False,
                    'message': '读取浏览器配置失败：%s' % e}
        try:
            cookies = await ctx.cookies()
            ok = platform_logged_in(cookies, platform)
            return {
                'platform': platform,
                'name': cfg['name'],
                'logged_in': ok,
                'message': '已登录' if ok else '还没登录，需要先登录一次',
            }
        finally:
            try:
                await ctx.close()
            except Exception:
                pass


def _default_profile_dir():
    """和闲鱼共用一个浏览器配置目录，登录一次就够了"""
    return os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
                        'XianyuTool_ChromeData')


async def check_all_platforms(user_data_dir=None):
    """一次启动浏览器，读一遍 cookie，判断三个平台的登录状态

    不要每个平台各启动一次浏览器——连续启动会撞 playwright driver
    （实测报 EPIPE，整个驱动崩掉）。
    """
    from playwright.async_api import async_playwright

    empty = [{'platform': k, 'name': v['name'], 'logged_in': False,
              'message': '读取失败'} for k, v in PLATFORM_LOGIN.items()]

    async with async_playwright() as p:
        ctx = None
        try:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir or _default_profile_dir(),
                headless=True,
                args=['--disable-blink-features=AutomationControlled'])
            cookies = await ctx.cookies()
        except Exception as e:
            if ctx:
                try:
                    await ctx.close()
                except Exception:
                    pass
            return [{'platform': k, 'name': v['name'], 'logged_in': False,
                     'message': '读取浏览器配置失败：%s' % str(e)[:60]}
                    for k, v in PLATFORM_LOGIN.items()]

        out = []
        for k, v in PLATFORM_LOGIN.items():
            ok = platform_logged_in(cookies, k)
            out.append({
                'platform': k,
                'name': v['name'],
                'logged_in': ok,
                'message': '已登录' if ok else '未登录',
            })

        try:
            await ctx.close()
        except Exception:
            pass
        return out


async def open_platform_login(platform, timeout=240):
    """打开可见浏览器窗口让用户登录，登录成功后自动关闭

    为什么要用户手动登录：三个平台都用手机验证码或扫码，程序没法代劳。
    登录一次之后 cookie 存在本地浏览器配置里，后面抓评价就能直接用。
    """
    from playwright.async_api import async_playwright

    cfg = PLATFORM_LOGIN.get(platform)
    if not cfg:
        return {'success': False, 'error': '不支持的平台：%s' % platform}

    async with async_playwright() as p:
        try:
            ctx = await p.chromium.launch_persistent_context(
                _default_profile_dir(),
                headless=False,          # 必须可见，用户要扫码
                args=['--disable-blink-features=AutomationControlled',
                      '--window-position=100,100', '--window-size=1200,860'],
                user_agent=UA,
                viewport={'width': 1200, 'height': 820},
                locale='zh-CN')
        except Exception as e:
            return {'success': False, 'error': '启动浏览器失败（可能闲鱼窗口还开着）：%s' % e}

        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            try:
                await page.goto(cfg['login_url'], wait_until='domcontentloaded', timeout=30000)
            except Exception:
                pass

            # 轮询等待登录完成
            waited = 0
            while waited < timeout:
                await asyncio.sleep(2)
                waited += 2
                try:
                    cookies = await ctx.cookies()
                except Exception:
                    break
                if platform_logged_in(cookies, platform):
                    return {'success': True, 'platform': platform,
                            'message': '%s 登录成功' % cfg['name']}

            return {'success': False,
                    'error': '%s 登录超时（%d 秒），请重试' % (cfg['name'], timeout)}
        finally:
            try:
                await ctx.close()
            except Exception:
                pass


async def jd_search_by_image(image_path, timeout=40):
    """京东以图搜图：把图片传上去，返回同款商品的 ID 列表

    这条路试了很多次才通，记一下关键点：
    1. 上传入口在搜索页顶部，但要 hover「同款搜低价」才展开，
       而且按钮在隐藏容器里，普通 click 会超时
    2. 用 CDP 的 DOM.setFileInputFiles 设文件（绕过可见性检查）
    3. 设完文件不会自动上传，要用 JS 强制 click 那个按钮
    4. 上传成功后跳到 https://search.jd.com/image?imgpath=<路径>，
       这个 URL 就是结果页，商品在 data-sku 属性里
    5. 结果页是懒加载的，滚动一屏后从 30 个涨到 60 个

    返回 (pids, imgpath)，失败返回 ([], '')
    """
    if not image_path or not os.path.isfile(image_path):
        return [], ''

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = None
        try:
            # 必须可见模式：无头模式下那个上传面板不渲染，CDP 设了文件也没用
            ctx = await p.chromium.launch_persistent_context(
                _default_profile_dir(), headless=False,
                args=['--disable-blink-features=AutomationControlled',
                      # 窗口必须在屏幕内：挪到屏幕外（-2400,-2400）时，
                      # Chromium 会跳过渲染，上传面板不生成，CDP 设了文件也没用
                      '--window-position=80,60',
                      '--window-size=1180,820'],
                user_agent=UA, viewport={'width': 1260, 'height': 800}, locale='zh-CN')
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()

            # 必须先进一个搜索结果页：上传入口只在结果页顶部渲染，
            # 搜首页（search.jd.com/）是没有 input[type=file] 的。
            # 搜什么词无所谓，这里只是为了把上传面板渲染出来。
            try:
                await page.goto(
                    'https://search.jd.com/Search?keyword=%E5%95%86%E5%93%81&enc=utf-8',
                    wait_until='domcontentloaded', timeout=25000)
            except Exception:
                pass
            await asyncio.sleep(3)

            # 1) CDP 设文件
            cdp = await ctx.new_cdp_session(page)
            doc = await cdp.send('DOM.getDocument')
            node = await cdp.send('DOM.querySelector', {
                'nodeId': doc['root']['nodeId'],
                'selector': 'input[type=file]'})
            if not node.get('nodeId'):
                return [], ''
            await cdp.send('DOM.setFileInputFiles', {
                'files': [os.path.abspath(image_path)],
                'nodeId': node['nodeId']})
            await asyncio.sleep(2)

            # 2) JS 强制点上传
            await page.evaluate("""
            () => {
              const all = Array.from(document.querySelectorAll('div,button,span,a'));
              let btn = all.find(e => (e.textContent||'').trim() === '上传图片'
                                      && (e.className||'').toString().includes('btn'));
              if (!btn) btn = document.querySelector('[class*="image_search_btn"]');
              if (btn) btn.click();
            }
            """)

            # 3) 等跳到结果页
            waited = 0
            while waited < timeout:
                await asyncio.sleep(1)
                waited += 1
                if 'search.jd.com/image' in page.url:
                    break
            if 'search.jd.com/image' not in page.url:
                return [], ''

            imgpath = ''
            m = re.search(r'imgpath=([^&]+)', page.url)
            if m:
                imgpath = m.group(1)

            # 4) 等结果 + 滚动触发懒加载
            await asyncio.sleep(3)
            pids = []
            for _pos in (0, 600, 1400):
                if _pos:
                    try:
                        await page.evaluate('window.scrollTo(0, %d)' % _pos)
                    except Exception:
                        pass
                    await asyncio.sleep(1.5)
                html = await page.content()
                found = list(dict.fromkeys(re.findall(r'data-sku="(\d{6,})"', html)))
                if len(found) > len(pids):
                    pids = found

            return pids, imgpath
        except Exception as e:
            print('  京东以图搜图失败: %s: %s' % (type(e).__name__, str(e)[:80]))
            return [], ''
        finally:
            if ctx:
                try:
                    await ctx.close()
                except Exception:
                    pass


async def fetch_review_images_by_image(image_path, max_images=10, max_products=8):
    """闲鱼首图 → 京东以图搜图 → 抓同款的评价图

    整个流程在**同一个浏览器实例**里跑完。
    之前拆成两个 context（一个上传、一个抓评价），结果第二个拿不到登录态，
    评价接口全返回空。合并后正常。

    返回 {source, name, status, images, message, pids}
    """
    name = '京东评价图'
    if not image_path or not os.path.isfile(image_path):
        return {'source': 'jd', 'name': name, 'status': 'skipped', 'images': [],
                'message': '没有参考图，无法以图搜图', 'pids': []}

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = None
        page = None
        try:
            # 必须可见模式：无头模式下上传面板不渲染；
            # 窗口也不能挪到屏幕外，否则 Chromium 跳过渲染
            ctx = await p.chromium.launch_persistent_context(
                _default_profile_dir(), headless=False,
                args=['--disable-blink-features=AutomationControlled',
                      '--window-position=80,60', '--window-size=1180,820'],
                user_agent=UA, viewport={'width': 1160, 'height': 760}, locale='zh-CN')

            cookies = await ctx.cookies()
            if not platform_logged_in(cookies, 'jd'):
                return {'source': 'jd', 'name': name, 'status': 'unavailable',
                        'images': [], 'message': '京东未登录，先点「登录京东」', 'pids': []}

            page = ctx.pages[0] if ctx.pages else await ctx.new_page()

            # ---- 1. 进搜索结果页拿到上传入口 ----
            try:
                # 这个关键词只是跳板：要一个能正常出商品列表的搜索页，
                # 上传入口才会渲染。用「商品」这种泛词搜不出东西，
                # 页面只有 200KB、没有商品列表，点了上传也不跳转（踩过）。
                await page.goto('https://search.jd.com/Search?keyword=%E6%8F%92%E6%8E%92&enc=utf-8',
                                wait_until='domcontentloaded', timeout=25000)
            except Exception:
                pass
            await asyncio.sleep(3)

            # ---- 2. CDP 设文件 + JS 点上传 ----
            cdp = await ctx.new_cdp_session(page)
            doc = await cdp.send('DOM.getDocument')
            node = await cdp.send('DOM.querySelector', {
                'nodeId': doc['root']['nodeId'],
                'selector': 'input[type=file]'})
            if not node.get('nodeId'):
                return {'source': 'jd', 'name': name, 'status': 'failed', 'images': [],
                        'message': '京东搜索页没有上传入口（可能改版了）', 'pids': []}

            await cdp.send('DOM.setFileInputFiles', {
                'files': [os.path.abspath(image_path)],
                'nodeId': node['nodeId']})
            await asyncio.sleep(2)

            await page.evaluate("""
            () => {
              const all = Array.from(document.querySelectorAll('div,button,span,a'));
              let btn = all.find(e => (e.textContent||'').trim() === '上传图片'
                                      && (e.className||'').toString().includes('btn'));
              if (!btn) btn = document.querySelector('[class*="image_search_btn"]');
              if (btn) btn.click();
            }
            """)

            # ---- 3. 等跳转到以图搜图结果页 ----
            # 有时候第一次点击没生效，等到 6 秒还没动静就补点一次
            waited = 0
            retried = False
            while waited < 30:
                await asyncio.sleep(1)
                waited += 1
                if 'search.jd.com/image' in page.url:
                    break
                if waited == 6 and not retried:
                    retried = True
                    try:
                        await page.evaluate("""
                        () => {
                          const all = Array.from(document.querySelectorAll('div,button,span,a'));
                          let b = all.find(e => (e.textContent||'').trim() === '上传图片'
                                                 && (e.className||'').toString().includes('btn'));
                          if (!b) b = document.querySelector('[class*="image_search_btn"]');
                          if (b) b.click();
                        }
                        """)
                    except Exception:
                        pass
            if 'search.jd.com/image' not in page.url:
                return {'source': 'jd', 'name': name, 'status': 'failed', 'images': [],
                        'message': '京东没跳到以图搜图结果页（上传可能失败了）', 'pids': []}

            # ---- 4. 滚出商品列表 ----
            # 结果页是异步渲染的，刚跳过来时 data-sku 可能一个都没有。
            # 多轮「等 + 滚 + 取」，直到抓到商品或者彻底放弃。
            pids = []
            for attempt in range(4):
                await asyncio.sleep(2.5 if attempt == 0 else 2)
                if attempt > 0:
                    try:
                        await page.evaluate('window.scrollTo(0, %d)' % (attempt * 700))
                    except Exception:
                        pass
                try:
                    html = await page.content()
                except Exception:
                    continue
                found = list(dict.fromkeys(re.findall(r'data-sku="(\d{6,})"', html)))
                if len(found) > len(pids):
                    pids = found
                if len(pids) >= 20:      # 够了，不用再滚
                    break

            if not pids:
                return {'source': 'jd', 'name': name, 'status': 'empty', 'images': [],
                        'message': '以图搜图没匹配到商品', 'pids': []}

            # ---- 5. 新开一个 page 抓评价 ----
            # 不能直接用结果页那个 page：从 search.jd.com/image 跳到
            # club.jd.com 时 Referer 是 search.jd.com，评价接口会拒绝（返回空）。
            # 新 page 在同一个 context 里，登录态共享，但 Referer 是干净的。
            comment_page = await ctx.new_page()
            images = []
            used = 0
            for pid in pids[:max_products]:
                if len(images) >= max_images:
                    break
                used += 1
                api = ('https://club.jd.com/comment/productPageComments.action'
                       '?productId=%s&score=0&sortType=5&page=0&pageSize=10'
                       '&isShadowSku=0&fold=1&imageStatus=1' % pid)
                try:
                    resp = await comment_page.goto(api, wait_until='domcontentloaded', timeout=20000)
                    if not resp or resp.status != 200:
                        continue
                    raw = await comment_page.inner_text('body')
                    if len(raw) < 60:
                        continue
                    data = json.loads(raw)
                except Exception:
                    continue
                for c in (data.get('comments') or []):
                    for im in (c.get('images') or []):
                        u = im if isinstance(im, str) else (im.get('imgUrl') or '')
                        if not u:
                            continue
                        u = upgrade_jd_image(u)
                        if u not in images:
                            images.append(u)
                        if len(images) >= max_images:
                            break
                    if len(images) >= max_images:
                        break

            if not images:
                return {'source': 'jd', 'name': name, 'status': 'empty', 'images': [],
                        'message': '以图搜图匹配 %d 个同款，但前 %d 个都没有带图评价' % (
                            len(pids), used), 'pids': pids}

            return {'source': 'jd', 'name': name, 'status': 'ok',
                    'images': images[:max_images],
                    'message': '以图搜图匹配 %d 个同款，从 %d 个抓到带图评价' % (len(pids), used),
                    'pids': pids}

        except Exception as e:
            return {'source': 'jd', 'name': name, 'status': 'failed', 'images': [],
                    'message': '%s: %s' % (type(e).__name__, str(e)[:100]), 'pids': []}
        finally:
            if ctx:
                try:
                    await ctx.close()
                except Exception:
                    pass


async def fetch_review_images(platform, keyword, max_images=10, timeout=40):
    """用已登录的浏览器抓某平台的买家评价图

    现状：
    - 京东：登录后搜索页和评价接口都能用，评价数据里 images 字段就是买家实拍图
    - 淘宝 / 拼多多：接口要签名（mtop / anti_content），暂时只返回"不支持"

    返回 {source, name, status, images, message}
    """
    cfg = PLATFORM_LOGIN.get(platform)
    if not cfg:
        return {'source': platform, 'name': platform, 'status': 'unavailable',
                'images': [], 'message': '不支持的平台'}

    if platform != 'jd':
        return {
            'source': platform, 'name': cfg['name'], 'status': 'unavailable',
            'images': [],
            'message': '%s 的评价接口要额外签名（%s），当前版本只支持京东' % (
                cfg['name'], 'mtop sign' if platform == 'taobao' else 'anti_content'),
        }

    if not keyword:
        return {'source': platform, 'name': cfg['name'], 'status': 'skipped',
                'images': [], 'message': '没有关键词，无法搜索'}

    from playwright.async_api import async_playwright
    from urllib.parse import quote

    async with async_playwright() as p:
        try:
            ctx = await p.chromium.launch_persistent_context(
                _default_profile_dir(), headless=True,
                args=['--disable-blink-features=AutomationControlled'],
                user_agent=UA, viewport={'width': 1440, 'height': 900}, locale='zh-CN')
        except Exception as e:
            return {'source': platform, 'name': cfg['name'], 'status': 'failed',
                    'images': [], 'message': '启动浏览器失败：%s' % e}

        try:
            cookies = await ctx.cookies()
            if not platform_logged_in(cookies, platform):
                return {'source': platform, 'name': cfg['name'], 'status': 'unavailable',
                        'images': [], 'message': '%s 未登录，先在界面上点「登录%s」' % (
                            cfg['name'], cfg['name'])}

            page = ctx.pages[0] if ctx.pages else await ctx.new_page()

            # 1) 搜索页拿商品 ID
            search_url = cfg['search'].format(kw=quote(keyword))
            try:
                await page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
            except Exception:
                pass
            # 等页面渲染完再滚：京东搜索页是分块加载的，
            # 只等 2 秒或只滚一屏常常抓不到 data-sku（实测 3 秒 + 滚两屏才稳）
            await asyncio.sleep(3)
            for _pos in (600, 1400):
                try:
                    await page.evaluate('window.scrollTo(0, %d)' % _pos)
                    await asyncio.sleep(1.7)
                except Exception:
                    pass

            html = await page.content()
            import re as _re
            # 京东搜索页的商品 ID 在 data-sku 属性里，不是 item.jd.com 链接
            pids = list(dict.fromkeys(_re.findall(r'data-sku="(\d{6,})"', html)))
            if not pids:
                # 兜底：老版页面是 item.jd.com/xxx.html 链接
                pids = list(dict.fromkeys(
                    _re.findall(r'item\.jd\.com/(\d{6,})\.html', html)))
            if not pids:
                # 京东有搜索频率限制，短时间内搜太多次会返回一句话的提示页
                if '访问频繁' in html or '无法搜索' in html or '稍后再试' in html:
                    return {'source': platform, 'name': cfg['name'],
                            'status': 'unavailable', 'images': [],
                            'message': '京东限制了搜索频率（提示"访问频繁导致无法搜索"），'
                                       '等几分钟再试，或者少勾几次'}
                if 'passport.jd.com' in html or '请登录' in html:
                    return {'source': platform, 'name': cfg['name'],
                            'status': 'unavailable', 'images': [],
                            'message': '京东登录态失效了，重新点一次「登录京东」'}
                snippet = html[:150].replace('\n', ' ')
                return {'source': platform, 'name': cfg['name'], 'status': 'empty',
                        'images': [],
                        'message': '搜索页没解析到商品（页面 %d 字节）：%s'
                                   % (len(html), snippet)}

            # 2) 逐个商品抓带图评价
            images = []
            for pid in pids[:3]:
                if len(images) >= max_images:
                    break
                api = ('https://club.jd.com/comment/productPageComments.action'
                       '?productId=%s&score=0&sortType=5&page=0&pageSize=10'
                       '&isShadowSku=0&fold=1&imageStatus=1' % pid)
                try:
                    resp = await page.goto(api, wait_until='domcontentloaded', timeout=20000)
                    if not resp or resp.status != 200:
                        continue
                    raw = await page.inner_text('body')
                    import json as _json
                    data = _json.loads(raw)
                except Exception:
                    continue
                for c in (data.get('comments') or []):
                    for im in (c.get('images') or []):
                        u = im if isinstance(im, str) else (im.get('imgUrl') or '')
                        if not u:
                            continue
                        u = upgrade_jd_image(u)   # 缩略图换成原图
                        if u not in images:
                            images.append(u)
                        if len(images) >= max_images:
                            break
                    if len(images) >= max_images:
                        break

            if not images:
                return {'source': platform, 'name': cfg['name'], 'status': 'empty',
                        'images': [], 'message': '搜到商品但没找到带图评价'}
            return {'source': platform, 'name': cfg['name'], 'status': 'ok',
                    'images': images[:max_images],
                    'message': '从 %d 个商品抓到带图评价' % min(len(pids), 3)}
        finally:
            try:
                await ctx.close()
            except Exception:
                pass
