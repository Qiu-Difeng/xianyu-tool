# -*- coding: utf-8 -*-
"""搜图模块测试

只测不需要真实网络的纯逻辑：去重、参数校验、URL 清洗。
search_by_image 要访问百度，不在单测里跑。
"""
import os

import pytest

import image_search as isr


# ---------------- 参数与边界 ----------------

def test_search_missing_file_returns_empty():
    urls, kw = __import__('asyncio').run(isr.search_by_image('/nonexistent/x.jpg'))
    assert urls == []
    assert kw == ''


def test_search_empty_path():
    urls, kw = __import__('asyncio').run(isr.search_by_image(''))
    assert urls == []


def test_download_empty_list(tmp_path):
    paths = __import__('asyncio').run(isr.download_images([], str(tmp_path)))
    assert paths == []


# ---------------- 去重 ----------------

def make_file(path, size_kb):
    with open(path, 'wb') as f:
        f.write(b'\x00' * (size_kb * 1024))
    return str(path)


def test_dedupe_removes_same_size(tmp_path):
    """大小完全相同的当成重复（百度同一张图常给多个 URL）"""
    a = make_file(tmp_path / 'a.jpg', 50)
    b = make_file(tmp_path / 'b.jpg', 50)
    c = make_file(tmp_path / 'c.jpg', 80)
    out = isr.dedupe_by_size([a, b, c])
    assert len(out) == 2
    assert not os.path.exists(b), '重复的那个文件应被删掉'


def test_dedupe_filters_tiny_files(tmp_path):
    a = make_file(tmp_path / 'small.jpg', 2)    # 低于 10KB
    b = make_file(tmp_path / 'ok.jpg', 50)
    out = isr.dedupe_by_size([a, b], min_kb=10)
    assert out == [b]


def test_dedupe_keeps_order(tmp_path):
    a = make_file(tmp_path / '1.jpg', 30)
    b = make_file(tmp_path / '2.jpg', 40)
    c = make_file(tmp_path / '3.jpg', 50)
    out = isr.dedupe_by_size([a, b, c])
    assert out == [a, b, c]


def test_dedupe_handles_missing_file(tmp_path):
    """列表里有不存在的路径不应崩"""
    ok = make_file(tmp_path / 'ok.jpg', 50)
    out = isr.dedupe_by_size([str(tmp_path / 'nope.jpg'), ok])
    assert out == [ok]


def test_dedupe_empty():
    assert isr.dedupe_by_size([]) == []


def test_dedupe_all_duplicates(tmp_path):
    a = make_file(tmp_path / 'a.jpg', 60)
    b = make_file(tmp_path / 'b.jpg', 60)
    out = isr.dedupe_by_size([a, b])
    assert len(out) == 1


# ---------------- 常量与配置 ----------------

def test_graph_home_url():
    assert isr.GRAPH_HOME.startswith('https://graph.baidu.com/')
    assert 'pcpage' in isr.GRAPH_HOME


def test_ua_looks_like_browser():
    assert 'Mozilla' in isr.UA
    assert 'Chrome' in isr.UA


# ---------------- 内容去重（dHash）----------------

def make_img(path, color, size=(400, 400), pattern=None, texture=True):
    """造一张测试图

    texture=True 会加随机噪点，模拟真实照片（相机噪点、光线不均）。
    纯色图在颜色统计上和文章截图完全一样，不加纹理没法区分。
    """
    import random
    from PIL import Image, ImageDraw

    im = Image.new('RGB', size, color)

    if texture:
        px = im.load()
        for y in range(0, size[1], 2):
            for x in range(0, size[0], 2):
                # 三个通道各自加不同的扰动：只加同一个值的话亮度变了但饱和度不变，
                # 而饱和度正是区分"照片"和"截图"的关键特征
                px[x, y] = tuple(max(0, min(255, c + random.randint(-35, 35)))
                                 for c in color)

    if pattern == 'stripes':
        d = ImageDraw.Draw(im)
        for i in range(0, size[0], 20):
            d.rectangle([i, 0, i + 10, size[1]], fill=(30, 30, 30))
    elif pattern == 'banner':
        # 顶部纯色横幅 + 白底黑字正文 = 文章截图的典型样子
        # 颜色要用淡色：实测小红书/公众号截图的平均饱和度只有 3-5，
        # 用鲜艳色会失真（鲜艳横幅会把整图饱和度拉高，反而判不出截图）
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, size[0], int(size[1] * 0.12)], fill=(206, 232, 214))
        # 正文画几行"文字"（横向条纹）
        for row in range(1, 14):
            y = int(size[1] * 0.12) + row * 40
            if y > size[1] - 20:
                break
            d.rectangle([40, y, size[0] - 40, y + 11], fill=(45, 45, 45))

    im.save(str(path), 'JPEG', quality=92)
    return str(path)


def test_dhash_same_image_different_size(tmp_path):
    """同一张图缩放后 hash 应该很接近"""
    from PIL import Image
    a = make_img(tmp_path / 'a.jpg', (200, 100, 50), (400, 400))
    b = str(tmp_path / 'b.jpg')
    Image.open(a).resize((600, 600)).save(b, 'JPEG', quality=80)

    ha, hb = isr._dhash(a), isr._dhash(b)
    assert ha is not None and hb is not None
    assert isr._hamming(ha, hb) <= 6, '同一张图缩放后 hash 差异过大'


def test_dhash_different_images(tmp_path):
    """不同图 hash 差得远"""
    a = make_img(tmp_path / 'a.jpg', (200, 100, 50), (400, 400))
    b = make_img(tmp_path / 'b.jpg', (50, 100, 200), (400, 400), pattern='stripes')
    assert isr._hamming(isr._dhash(a), isr._dhash(b)) > 6


def test_hamming_null():
    assert isr._hamming(None, 123) == 999
    assert isr._hamming(0b1010, 0b1010) == 0
    assert isr._hamming(0b1010, 0b1011) == 1


# ---------------- 文字截图打分 ----------------

def test_screenshot_score_plain_image_low(tmp_path):
    """有内容的商品图不该被判截图

    注意不能拿纯色图来测：纯色背景本来就和"标题横幅"长得一样，
    判成可疑是对的。真实商品图总有商品主体和光影层次。
    """
    p = make_img(tmp_path / 'goods.jpg', (200, 150, 100), (500, 500), pattern='stripes')
    assert isr.screenshot_score(p) < 0.5


def test_screenshot_score_banner_high(tmp_path):
    """顶部大色块 + 低饱和 = 像文章截图"""
    p = make_img(tmp_path / 'banner.jpg', (255, 255, 255), (500, 900), pattern='banner')
    assert isr.screenshot_score(p) >= 0.5


def test_screenshot_score_missing_file():
    assert isr.screenshot_score('/nonexistent/x.jpg') == 0.0


# ---------------- 内容去重主逻辑 ----------------

def test_dedupe_by_content_removes_scaled_duplicate(tmp_path):
    """同一张图两个尺寸，只留清晰的那个"""
    from PIL import Image
    a = make_img(tmp_path / 'small.jpg', (120, 180, 240), (300, 300))
    b = str(tmp_path / 'big.jpg')
    Image.open(a).resize((800, 800)).save(b, 'JPEG', quality=92)

    res = isr.dedupe_by_content([a, b])
    assert len(res) == 1, '重复图应只留一张，实际 %d' % len(res)
    assert res[0][1] == 800, '应保留更大的那张'


def test_dedupe_by_content_keeps_different_images(tmp_path):
    a = make_img(tmp_path / 'a.jpg', (200, 100, 50), (400, 400))
    b = make_img(tmp_path / 'b.jpg', (50, 100, 200), (400, 400), pattern='stripes')
    res = isr.dedupe_by_content([a, b])
    assert len(res) == 2


def test_dedupe_by_content_filters_small(tmp_path):
    """宽度小于阈值的丢掉"""
    small = make_img(tmp_path / 's.jpg', (200, 100, 50), (120, 120))
    ok = make_img(tmp_path / 'o.jpg', (100, 200, 50), (500, 500))
    res = isr.dedupe_by_content([small, ok], min_width=200)
    assert len(res) == 1
    assert res[0][0] == ok


def test_dedupe_by_content_sorted_by_score(tmp_path):
    """可疑截图排后面，正常图在前"""
    normal = make_img(tmp_path / 'n.jpg', (200, 150, 100), (500, 500))
    banner = make_img(tmp_path / 'b.jpg', (255, 255, 255), (500, 900), pattern='banner')
    res = isr.dedupe_by_content([banner, normal])
    assert res[0][0] == normal, '正常图应排在最前'


def test_dedupe_by_content_returns_triples(tmp_path):
    a = make_img(tmp_path / 'a.jpg', (200, 100, 50), (400, 400))
    res = isr.dedupe_by_content([a])
    assert len(res) == 1
    assert len(res[0]) == 3, '应返回 (path, width, score)'
    assert res[0][1] == 400


def test_dedupe_by_content_empty():
    assert isr.dedupe_by_content([]) == []


def test_dedupe_by_content_skips_missing(tmp_path):
    ok = make_img(tmp_path / 'ok.jpg', (200, 100, 50), (400, 400))
    res = isr.dedupe_by_content(['/nonexistent/a.jpg', ok])
    assert len(res) == 1
