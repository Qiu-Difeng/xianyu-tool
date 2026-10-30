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
