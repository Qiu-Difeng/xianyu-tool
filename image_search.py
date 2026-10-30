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

PLATFORM_NOTES = {
    'jd': '京东要求登录，商品页和评价接口都会拦（实测接口返回 444，浏览器只拿到登录页）',
    'pdd': '拼多多有 anti_content 签名和 verifyAuthToken，且以图搜货只在 App 内有',
    'taobao': '淘宝要登录态和 mtop 签名，网页版评价区不对外直出',
}


async def try_platform_review_images(platform, keyword, max_images=10, timeout=15):
    """尝试从电商平台拿买家评价图

    现状：三个平台都拿不到（要登录 + 强反爬），所以这里直接返回不可用，
    并把原因带出去给界面展示。

    保留这个函数是为了两件事：
    1. 界面能明确告诉用户"这个源为什么没图"，而不是静默少几张
    2. 以后哪个平台开放了（或者有合规的开放接口），只要改这里的实现

    返回 {source, status, images, message}
    """
    name = {'jd': '京东', 'pdd': '拼多多', 'taobao': '淘宝'}.get(platform, platform)
    return {
        'source': platform,
        'name': name,
        'status': 'unavailable',
        'images': [],
        'message': PLATFORM_NOTES.get(platform, '暂不支持'),
    }

# ============================================================
# 多源聚合
# ============================================================

# 展示顺序：先精准的（以图搜图），再量大的（关键词），最后是拿不到的
SOURCE_ORDER = ['baidu_image', 'baidu_keyword', 'jd', 'pdd', 'taobao']

SOURCE_LABELS = {
    'baidu_image': '百度识图',
    'baidu_keyword': '百度图片',
    'jd': '京东评价图',
    'pdd': '拼多多评价图',
    'taobao': '淘宝评价图',
}


async def collect_all_sources(product_image, keyword='', max_per_source=20,
                              include_platforms=True):
    """按顺序从各个来源收图，某个源失败不影响其他源

    返回列表，每项：
      {source, name, status, images, message, cost}
      status: ok / empty / failed / unavailable / skipped

    调用方按返回顺序展示即可（已经按 SOURCE_ORDER 排好）。
    """
    results = []

    # --- 源 1：百度识图（以图搜图）---
    if product_image:
        t0 = asyncio.get_event_loop().time()
        try:
            urls, detected = await search_by_image(product_image, max_images=max_per_source)
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
    else:
        results.append({
            'source': 'baidu_image', 'name': SOURCE_LABELS['baidu_image'],
            'status': 'skipped', 'images': [],
            'message': '没有参考图，跳过以图搜图', 'cost': 0,
        })

    # --- 源 2：百度图片（关键词）---
    if keyword:
        t0 = asyncio.get_event_loop().time()
        try:
            urls = await search_by_keyword(keyword, max_images=max_per_source)
            cost = asyncio.get_event_loop().time() - t0
            results.append({
                'source': 'baidu_keyword',
                'name': SOURCE_LABELS['baidu_keyword'],
                'status': 'ok' if urls else 'empty',
                'images': urls,
                'message': ('按「%s」搜到' % keyword) if urls else '这个关键词没搜到图',
                'cost': round(cost, 1),
            })
        except Exception as e:
            results.append({
                'source': 'baidu_keyword', 'name': SOURCE_LABELS['baidu_keyword'],
                'status': 'failed', 'images': [],
                'message': '%s: %s' % (type(e).__name__, e), 'cost': 0,
            })
    else:
        results.append({
            'source': 'baidu_keyword', 'name': SOURCE_LABELS['baidu_keyword'],
            'status': 'skipped', 'images': [],
            'message': '没有关键词（商品标题为空），跳过', 'cost': 0,
        })

    # --- 源 3~5：电商平台买家评价图 ---
    if include_platforms:
        for plat in ('jd', 'pdd', 'taobao'):
            try:
                r = await try_platform_review_images(plat, keyword, max_images=10)
                r['cost'] = 0
                results.append(r)
            except Exception as e:
                results.append({
                    'source': plat, 'name': SOURCE_LABELS.get(plat, plat),
                    'status': 'failed', 'images': [],
                    'message': '%s: %s' % (type(e).__name__, e), 'cost': 0,
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
