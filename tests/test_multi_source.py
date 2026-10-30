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
    """返回结果必须按 SOURCE_ORDER 排好"""
    results = run(isr.collect_all_sources('', keyword='', sources=['baidu_image', 'baidu_keyword']))
    order = [r['source'] for r in results]
    assert order == ['baidu_image', 'baidu_keyword'], order


def test_collect_skips_when_no_input():
    """没图没关键词时两个源都应标 skipped"""
    results = run(isr.collect_all_sources('', keyword='', sources=['baidu_image', 'baidu_keyword']))
    for r in results:
        assert r['status'] == 'skipped', r


def test_collect_includes_jd():
    """全开时京东也在里面，且排在百度两个源后面"""
    results = run(isr.collect_all_sources('', keyword='', sources=None))
    srcs = [r['source'] for r in results]
    assert 'jd' in srcs
    assert srcs.index('jd') > srcs.index('baidu_keyword')


def test_collect_degrades_on_source_failure(monkeypatch):
    """一个源抛异常，不应影响整体返回"""
    async def boom(*a, **kw):
        raise RuntimeError('模拟接口挂了')

    async def ok_keyword(*a, **kw):
        return ['http://x/1.jpg', 'http://x/2.jpg']

    monkeypatch.setattr(isr, 'search_by_image', boom)
    monkeypatch.setattr(isr, 'search_by_keyword', ok_keyword)

    results = run(isr.collect_all_sources('fake.jpg', keyword='插排', sources=['baidu_image', 'baidu_keyword']))

    by_src = {r['source']: r for r in results}
    assert by_src['baidu_image']['status'] == 'failed'
    assert 'RuntimeError' in by_src['baidu_image']['message']
    # 另一个源照常返回
    assert by_src['baidu_keyword']['status'] == 'ok'
    assert len(by_src['baidu_keyword']['images']) == 2


def test_collect_uses_detected_keyword(monkeypatch):
    """识图识别出商品名时，关键词搜图应该复用它"""
    async def fake_image(*a, **kw):
        return ['http://x/1.jpg'], '智能插排'

    captured = {}

    async def fake_keyword(kw, **kwargs):
        captured['kw'] = kw
        return ['http://y/1.jpg']

    monkeypatch.setattr(isr, 'search_by_image', fake_image)
    monkeypatch.setattr(isr, 'search_by_keyword', fake_keyword)

    run(isr.collect_all_sources('fake.jpg', keyword='', sources=['baidu_image', 'baidu_keyword']))
    assert captured.get('kw') == '智能插排', '应复用识图识别出的关键词'


def test_collect_empty_source_marks_empty(monkeypatch):
    async def empty_image(*a, **kw):
        return [], ''

    async def empty_keyword(*a, **kw):
        return []

    monkeypatch.setattr(isr, 'search_by_image', empty_image)
    monkeypatch.setattr(isr, 'search_by_keyword', empty_keyword)

    results = run(isr.collect_all_sources('fake.jpg', keyword='x', sources=['baidu_image', 'baidu_keyword']))
    for r in results:
        assert r['status'] == 'empty', r


def test_source_order_constant():
    assert isr.SOURCE_ORDER[0] == 'baidu_image'
    assert isr.SOURCE_ORDER[-1] == 'jd'
    assert len(isr.SOURCE_ORDER) == 3


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

def test_source_order_only_three():
    """拼多多和淘宝已移除，只剩三个来源"""
    assert isr.SOURCE_ORDER == ['baidu_image', 'baidu_keyword', 'jd']
    assert set(isr.SOURCE_LABELS) == set(isr.SOURCE_ORDER)
    assert 'pdd' not in isr.SOURCE_LABELS
    assert 'taobao' not in isr.SOURCE_LABELS


def test_source_default_max():
    assert isr.SOURCE_DEFAULT_MAX['baidu_image'] == 15
    assert isr.SOURCE_DEFAULT_MAX['baidu_keyword'] == 15
    assert isr.SOURCE_DEFAULT_MAX['jd'] == 10


def test_collect_filters_sources(monkeypatch):
    """只传某个源时，结果里只有那个源"""
    called = []

    async def fake_image(*a, **kw):
        called.append('baidu_image')
        return ['http://x/1.jpg'], ''

    async def fake_keyword(*a, **kw):
        called.append('baidu_keyword')
        return ['http://y/1.jpg']

    monkeypatch.setattr(isr, 'search_by_image', fake_image)
    monkeypatch.setattr(isr, 'search_by_keyword', fake_keyword)

    results = run(isr.collect_all_sources('fake.jpg', keyword='插排',
                                          sources=['baidu_keyword']))
    assert [r['source'] for r in results] == ['baidu_keyword']
    assert 'baidu_image' not in called, '没勾选的源不应该被调用'
    assert 'baidu_keyword' in called


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
    monkeypatch.setattr(isr, 'search_by_keyword', fake_keyword)
    monkeypatch.setattr(isr, 'fetch_review_images', fake_image)

    results = run(isr.collect_all_sources('fake.jpg', keyword='插排', sources=None))
    srcs = [r['source'] for r in results]
    assert srcs == ['baidu_image', 'baidu_keyword', 'jd'], srcs


def test_collect_ignores_unknown_source(monkeypatch):
    """传了不认识的源名要忽略掉，不报错"""
    async def fake(*a, **kw):
        return ['http://x/1.jpg'], ''

    monkeypatch.setattr(isr, 'search_by_image', fake)
    results = run(isr.collect_all_sources('fake.jpg', keyword='x',
                                          sources=['baidu_image', 'pdd', 'nope']))
    assert [r['source'] for r in results] == ['baidu_image']


def test_max_map_applied_per_source(monkeypatch):
    """每个源用自己配置的数量，不是统一值"""
    seen = {}

    async def fake_image(img, max_images=15, **kw):
        seen['image'] = max_images
        return [], ''

    async def fake_keyword(kw_, max_images=15, **kw):
        seen['keyword'] = max_images
        return []

    monkeypatch.setattr(isr, 'search_by_image', fake_image)
    monkeypatch.setattr(isr, 'search_by_keyword', fake_keyword)

    run(isr.collect_all_sources('fake.jpg', keyword='x',
                                sources=['baidu_image', 'baidu_keyword'],
                                max_map={'baidu_image': 5, 'baidu_keyword': 9}))
    assert seen['image'] == 5, seen
    assert seen['keyword'] == 9, seen


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


def test_jd_requires_login_message(monkeypatch):
    """京东没登录时要提示去登录"""
    async def fake_fetch(plat, kw, max_images=10, **kwargs):
        return {'source': 'jd', 'name': '京东评价图', 'status': 'unavailable',
                'images': [], 'message': '京东 未登录，先在界面上点「登录京东」'}

    monkeypatch.setattr(isr, 'fetch_review_images', fake_fetch)
    results = run(isr.collect_all_sources('', keyword='插排', sources=['jd']))
    assert results[0]['status'] == 'unavailable'
    assert '登录' in results[0]['message']
