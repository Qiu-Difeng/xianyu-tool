# -*- coding: utf-8 -*-
"""京东评价图 + 自动定位水印 + LaMa 修复，出对比图

水印特征：红色半透明「JD.COM京东」，横贯画面，位置不固定（有的 24%，有的 65%）。
检测思路：红色像素按行统计，水印所在的行会出现明显峰值。
"""
import asyncio
import io
import json
import os
import sys
import time

import cv2
import numpy as np
import torch
from PIL import Image

sys.path.insert(0, os.getcwd())

LOG = os.path.join(os.environ['TEMP'], 'jd_wm_demo.log')
_lf = io.open(LOG, 'w', encoding='utf-8', newline='\n')


def log(m):
    line = '[%s] %s' % (time.strftime('%H:%M:%S'), m)
    print(line)
    _lf.write(line + '\n')
    _lf.flush()


def detect_watermark_band(img_bgr):
    """找水印所在的横向条带，返回 (y1, y2) 或 None

    京东水印是红色半透明文字，横贯整幅图。
    做法：算每行的"红色像素数"，水印那几行会形成明显峰值。
    只看画面中部 20%~85% 范围，避开顶部导航和底部文案。
    """
    h, w = img_bgr.shape[:2]
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

    # 红色分两段（色相环首尾）
    m1 = cv2.inRange(hsv, np.array([0, 40, 60]), np.array([14, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([166, 40, 60]), np.array([180, 255, 255]))
    red = cv2.bitwise_or(m1, m2)

    # 只看中部区域
    y_lo, y_hi = int(h * 0.18), int(h * 0.88)
    row_cnt = (red[y_lo:y_hi] > 0).sum(axis=1).astype(np.float32)

    if row_cnt.max() < w * 0.05:      # 红色像素太少，认为没水印
        return None

    # 平滑后找峰值区
    k = np.ones(9, np.float32) / 9
    smooth = np.convolve(row_cnt, k, mode='same')
    thresh = smooth.max() * 0.35

    above = smooth > thresh
    if not above.any():
        return None

    # 找最长的一段连续区域
    best_len, best_start, cur_start = 0, 0, None
    for i, v in enumerate(above):
        if v and cur_start is None:
            cur_start = i
        elif not v and cur_start is not None:
            if i - cur_start > best_len:
                best_len, best_start = i - cur_start, cur_start
            cur_start = None
    if cur_start is not None and len(above) - cur_start > best_len:
        best_len, best_start = len(above) - cur_start, cur_start

    if best_len < 8:
        return None

    y1 = y_lo + best_start
    y2 = y_lo + best_start + best_len
    # 上下各留 32 像素余量：实测 15 像素不够，水印下沿会露出来
    # （第 6 张翻车就是因为框只到 90%，水印实际在 88-92%）
    return max(0, y1 - 32), min(h, y2 + 32)


async def fetch_images(pid, outdir, limit=6):
    """从京东评价接口抓买家图"""
    from playwright.async_api import async_playwright
    import httpx
    from image_search import UA, _default_profile_dir, upgrade_jd_image, platform_logged_in

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            _default_profile_dir(), headless=True,
            args=['--disable-blink-features=AutomationControlled'],
            user_agent=UA, viewport={'width': 1440, 'height': 900}, locale='zh-CN')
        cookies = await ctx.cookies()
        if not platform_logged_in(cookies, 'jd'):
            log('✗ 京东未登录')
            await ctx.close()
            return []

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        api = ('https://club.jd.com/comment/productPageComments.action'
               '?productId=%s&score=0&sortType=5&page=0&pageSize=10'
               '&isShadowSku=0&fold=1&imageStatus=1' % pid)
        r = await page.goto(api, wait_until='domcontentloaded', timeout=20000)
        raw = await page.inner_text('body')
        log('评价接口: status=%s len=%d' % (r.status if r else '?', len(raw)))
        if len(raw) < 60:
            await ctx.close()
            return []

        data = json.loads(raw)
        urls = []
        for c in (data.get('comments') or []):
            for im in (c.get('images') or []):
                u = im if isinstance(im, str) else (im.get('imgUrl') or '')
                if u:
                    u = upgrade_jd_image(u)
                    if u not in urls:
                        urls.append(u)
        log('拿到 %d 个图片 URL' % len(urls))
        await ctx.close()

        os.makedirs(outdir, exist_ok=True)
        saved = []
        for i, u in enumerate(urls[:limit], 1):
            try:
                rr = httpx.get(u, headers={'User-Agent': UA, 'Referer': 'https://item.jd.com/'},
                               timeout=20, follow_redirects=True)
                if rr.status_code == 200 and len(rr.content) > 3000:
                    pth = os.path.join(outdir, 'src_%02d.jpg' % i)
                    open(pth, 'wb').write(rr.content)
                    im = Image.open(io.BytesIO(rr.content))
                    log('  下载 %d: %dx%d %.0fKB' % (i, im.width, im.height, len(rr.content) / 1024))
                    saved.append(pth)
            except Exception as e:
                log('  下载 %d 失败: %s' % (i, type(e).__name__))
        return saved


def main():
    log('=' * 55)
    log('京东买家图 + 自动定位水印 + LaMa 修复')
    log('=' * 55)

    # LaMa 加载前必须 patch：模型是 CUDA 上导出的
    _orig = torch.jit.load

    def _patched(path, *a, **kw):
        kw.setdefault('map_location', 'cpu')
        return _orig(path, *a, **kw)

    torch.jit.load = _patched

    from simple_lama_inpainting import SimpleLama
    lama = SimpleLama()
    log('LaMa 就绪')

    # 抓图（用之前验证过有 59 张图的那个商品）
    src_dir = os.path.join(os.environ['TEMP'], 'jd_demo_src')
    files = sorted(
        os.path.join(src_dir, f) for f in os.listdir(src_dir)
        if f.endswith('.jpg')
    ) if os.path.isdir(src_dir) else []

    if len(files) < 6:
        log('抓取图片...')
        files = asyncio.run(fetch_images('10112696457654', src_dir, limit=6))

    if not files:
        log('没抓到图')
        return

    log('')
    log('开始检测 + 修复')
    pairs = []
    MAX_W = 1100

    for f in files[:6]:
        img = cv2.imread(f)
        if img is None:
            continue
        # 大图先缩：4032x3024 的原始买家图直接进 LaMa 要 150 秒，
        # 缩到 1100 宽只要 7 秒，而闲鱼展示宽度也就 750，缩了没损失
        if img.shape[1] > MAX_W:
            scale = MAX_W / float(img.shape[1])
            img = cv2.resize(img, (MAX_W, int(img.shape[0] * scale)),
                             interpolation=cv2.INTER_AREA)
        band = detect_watermark_band(img)
        name = os.path.basename(f)
        if not band:
            log('  %s  未检测到水印，跳过' % name)
            continue
        y1, y2 = band
        h = img.shape[0]
        log('  %s  水印带 y=%d~%d（占高度 %.0f%%~%.0f%%）' % (
            name, y1, y2, y1 / h * 100, y2 / h * 100))

        mask = np.zeros((h, img.shape[1]), dtype=np.uint8)
        mask[y1:y2, :] = 255

        t0 = time.time()
        out = lama(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)),
                   Image.fromarray(mask).convert('L'))
        fixed = cv2.cvtColor(np.array(out), cv2.COLOR_RGB2BGR)
        log('       修复 %.1f 秒' % (time.time() - t0))
        pairs.append((img, fixed, name, band))

    if not pairs:
        log('没有可对比的图')
        return

    # 拼对比图：每行「原图 | 修复后」，原图上用绿框标出水印带
    # 注意：不同图宽高比不同，必须统一高度再横向拼，否则 hstack 会报
    # "array at index 0 has size 559 and index 2 has size 562"
    ROW_H = 380
    GAP = 10

    def fit_h(im, target_h=ROW_H):
        h, w = im.shape[:2]
        return cv2.resize(im, (max(1, int(w * target_h / float(h))), target_h),
                          interpolation=cv2.INTER_AREA)

    rows = []
    for img, fixed, name, (y1, y2) in pairs:
        a = img.copy()
        cv2.rectangle(a, (0, y1), (a.shape[1] - 1, y2), (0, 255, 0), 3)
        a2, f2 = fit_h(a), fit_h(fixed)
        sep = np.full((ROW_H, GAP, 3), 255, np.uint8)
        rows.append(np.hstack([a2, sep, f2]))

    # 每行宽度可能不同，统一用最大宽度，右边补白
    max_w = max(r.shape[1] for r in rows)
    padded = []
    for r in rows:
        if r.shape[1] < max_w:
            r = np.hstack([r, np.full((ROW_H, max_w - r.shape[1], 3), 255, np.uint8)])
        padded.append(r)
        padded.append(np.full((GAP, max_w, 3), 255, np.uint8))
    canvas = np.vstack(padded)
    out_path = os.path.join(os.environ['TEMP'], 'jd_wm_compare.png')
    Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)).save(out_path)
    log('')
    log('对比图: %s (%dx%d)' % (out_path, canvas.shape[1], canvas.shape[0]))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log('异常: %s: %s' % (type(e).__name__, e))
    finally:
        log('结束')
        _lf.close()
