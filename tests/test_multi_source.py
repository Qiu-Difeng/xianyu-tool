# -*- coding: utf-8 -*-
"""多源聚合搜图的测试

不访问网络：把 search_by_image / search_by_keyword 换成桩函数，
只验证聚合逻辑、排序、降级和汇总文案。
"""
import asyncio

import pytest

import image_search as isr


def run(coro):
    return asyncio.run(coro)


# ---------------- 汇总文案 ----------------

def test_summarize_all_ok():
    results = [
        {'source': 'baidu_image', 'name': '百度识图', 'status': 'ok', 'images': ['a', 'b'], 'count': 2},
        {'source': 'baidu_keyword', 'name': '百度图片', 'status': 'ok', 'images': ['c'], 'count': 1},
    ]
    s = isr.summarize_sources(results)
    assert '3 张' in s
    assert '百度识图' in s and '百度图片' in s


def test_summarize_nothing_found():
    results = [
        {'source': 'baidu_image', 'name': '百度识图', 'status': 'empty', 'images': []},
    ]
    s = isr.summarize_sources(results)
    assert '没能收到图片' in s


def test_summarize_lists_unavailable():
    results = [
        {'source': 'baidu_image', 'name': '百度识图', 'status': 'ok', 'images': ['a'], 'count': 1},
        {'source': 'jd', 'name': '京东评价图', 'status': 'unavailable', 'images': []},
        {'source': 'pdd', 'name': '拼多多评价图', 'status': 'unavailable', 'images': []},
    ]
    s = isr.summarize_sources(results)
    assert '京东评价图' in s and '拼多多评价图' in s
    assert '不可用' in s


def test_summarize_uses_count_not_url_length():
    """汇总要用下载去重后的实际张数，不是 URL 条数"""
    results = [
        {'source': 'baidu_image', 'name': '百度识图', 'status': 'ok',
         'images': ['a', 'b', 'c', 'd'], 'count': 2},
    ]
    s = isr.summarize_sources(results)
    assert '2 张' in s
    assert '4 张' not in s


# ---------------- 聚合与降级 ----------------
def test_collect_order():
    """只剩百度识图，结果里就该只有它"""
    results = run(isr.collect_all_sources('', keyword='', sources=['baidu_image']))
    order = [r['source'] for r in results]
    assert order == ['baidu_image'], order
def test_collect_skips_when_no_input():
    """没图没关键词时两个源都应标 skipped"""
    results = run(isr.collect_all_sources('', keyword='', sources=['baidu_image', 'baidu_keyword']))
    for r in results:
        assert r['status'] == 'skipped', r


def test_source_order_constant():
    # 只剩百度识图（以图搜图）
    assert isr.SOURCE_ORDER == ['baidu_image']


def test_source_labels_complete():
    for s in isr.SOURCE_ORDER:
        assert s in isr.SOURCE_LABELS, '缺少 %s 的显示名' % s


# ---------------- 平台登录检测 ----------------

def test_platform_config_complete():
    # 淘宝和拼多多已从来源里移除，只剩京东
    for plat in ('jd',):
        cfg = isr.PLATFORM_LOGIN[plat]
        for key in ('name', 'login_url', 'search', 'cookies'):
            assert key in cfg, '%s 缺少 %s' % (plat, key)
        assert cfg['login_url'].startswith('https://')


def test_platform_logged_in_by_cookie():
    """有对应 cookie 就算登录，没有就不算"""
    jd_cookies = [{'name': 'thor'}, {'name': 'pin'}]
    assert isr.platform_logged_in(jd_cookies, 'jd') is True

    other = [{'name': 'some_other'}]
    assert isr.platform_logged_in(other, 'jd') is False


def test_platform_logged_in_unknown():
    assert isr.platform_logged_in([{'name': 'thor'}], 'unknown_plat') is False


def test_platform_logged_in_empty():
    assert isr.platform_logged_in([], 'jd') is False


# ---------------- 评价抓取的平台差异 ----------------

@pytest.mark.parametrize('plat', ['taobao', 'pdd'])
def test_fetch_reviews_unsupported_platforms(plat):
    """淘宝/拼多多已从来源和登录配置里移除，直接调用返回不可用"""
    r = run(isr.fetch_review_images(plat, '插排'))
    assert r['status'] == 'unavailable'
    assert r['images'] == []
    assert '不支持' in r['message'] or '签名' in r['message']


def test_fetch_reviews_no_keyword():
    r = run(isr.fetch_review_images('jd', ''))
    assert r['status'] == 'skipped'
    assert '关键词' in r['message']


def test_fetch_reviews_unknown_platform():
    r = run(isr.fetch_review_images('nope', 'x'))
    assert r['status'] == 'unavailable'


def test_default_profile_dir():
    d = isr._default_profile_dir()
    assert 'XianyuTool_ChromeData' in d, '应该和闲鱼共用浏览器配置'


# ---------------- 京东图片地址升级 ----------------

def test_upgrade_jd_image_thumbnail_to_original():
    """京东评价图接口给的是 s128x96 缩略图（才 1.7KB），去掉尺寸段就是原图"""
    src = '//img30.360buyimg.com/n0/s128x96_jfs/t1/522202/29/14190/504992/x.jpg'
    out = isr.upgrade_jd_image(src)
    assert out.startswith('https://'), '协议相对地址要补 https'
    assert '/s128x96_' not in out
    assert '/n0/jfs/t1/522202' in out


def test_upgrade_jd_image_various_sizes():
    for size in ['s128x96', 's500x500', 's800x800', 's220x220']:
        src = '//img30.360buyimg.com/n0/%s_jfs/t1/a/b.jpg' % size
        out = isr.upgrade_jd_image(src)
        assert size not in out, '%s 没去掉' % size
        assert out == 'https://img30.360buyimg.com/n0/jfs/t1/a/b.jpg'


def test_upgrade_jd_image_already_original():
    src = 'https://img30.360buyimg.com/n0/jfs/t1/z.jpg'
    assert isr.upgrade_jd_image(src) == src


def test_upgrade_jd_image_empty():
    assert isr.upgrade_jd_image('') == ''
    assert isr.upgrade_jd_image(None) is None


# ---------------- 京东商品 ID 提取口径 ----------------

def test_goods_id_uses_data_sku():
    """京东搜索页的商品 ID 在 data-sku 属性里，不是 item.jd.com 链接"""
    import re as _re
    html = ('<li data-sku="10177306531382">A</li>'
            '<li data-sku="100016407792">B</li>'
            '<li data-sku="10177306531382">重复</li>')
    pids = list(dict.fromkeys(_re.findall(r'data-sku="(\d{6,})"', html)))
    assert pids == ['10177306531382', '100016407792'], pids


# ---------------- 来源勾选与数量控制 ----------------

def test_source_order_only_baidu_image():
    """京东、拼多多、淘宝、百度图片都已移除，只剩百度识图"""
    assert isr.SOURCE_ORDER == ['baidu_image']
    assert set(isr.SOURCE_LABELS) == set(isr.SOURCE_ORDER)
    for gone in ('pdd', 'taobao', 'jd', 'baidu_keyword'):
        assert gone not in isr.SOURCE_LABELS


def test_source_default_max():
    assert isr.SOURCE_DEFAULT_MAX['baidu_image'] == 15
    for gone in ('baidu_keyword', 'jd'):
        assert gone not in isr.SOURCE_DEFAULT_MAX


def test_collect_empty_sources_returns_nothing(monkeypatch):
    """空列表 = 一个都不要（不是"全部默认"）"""
    called = []

    async def fake(*a, **kw):
        called.append(1)
        return [], ''

    monkeypatch.setattr(isr, 'search_by_image', fake)
    monkeypatch.setattr(isr, 'search_by_keyword', fake)

    results = run(isr.collect_all_sources('fake.jpg', keyword='x', sources=[]))
    assert results == []
    assert called == [], '空选择时不该调用任何搜图函数'


def test_collect_none_sources_means_all(monkeypatch):
    """None 才是默认全开"""
    async def fake_image(*a, **kw):
        return ['http://x/1.jpg'], ''

    async def fake_keyword(*a, **kw):
        return ['http://y/1.jpg']

    monkeypatch.setattr(isr, 'search_by_image', fake_image)
    monkeypatch.setattr(isr, 'fetch_review_images', fake_image)

    results = run(isr.collect_all_sources('fake.jpg', keyword='插排', sources=None))
    srcs = [r['source'] for r in results]
    assert srcs == ['baidu_image'], srcs


def test_collect_ignores_unknown_source(monkeypatch):
    """传了不认识的源名要忽略掉，不报错"""
    async def fake(*a, **kw):
        return ['http://x/1.jpg'], ''

    monkeypatch.setattr(isr, 'search_by_image', fake)
    results = run(isr.collect_all_sources('fake.jpg', keyword='x',
                                          sources=['baidu_image', 'pdd', 'nope']))
    assert [r['source'] for r in results] == ['baidu_image']


def test_max_map_clamped(monkeypatch):
    """非法或超范围的数量要兜住"""
    seen = {}

    async def fake_image(img, max_images=15, **kw):
        seen['image'] = max_images
        return [], ''

    monkeypatch.setattr(isr, 'search_by_image', fake_image)

    for val, expect in [(0, isr.SOURCE_DEFAULT_MAX['baidu_image']),
                        (-3, isr.SOURCE_DEFAULT_MAX['baidu_image']),
                        ('abc', isr.SOURCE_DEFAULT_MAX['baidu_image']),
                        (999, 100)]:
        run(isr.collect_all_sources('fake.jpg', sources=['baidu_image'],
                                    max_map={'baidu_image': val}))
        assert seen['image'] == expect, '输入 %r 应得 %d，实际 %d' % (val, expect, seen['image'])

