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


# ---------------- 平台不可用 ----------------

@pytest.mark.parametrize('plat', ['jd', 'pdd', 'taobao'])
def test_platform_unavailable_has_message(plat):
    r = run(isr.try_platform_review_images(plat, '插排'))
    assert r['status'] == 'unavailable'
    assert r['images'] == []
    assert len(r['message']) > 5, '必须说明为什么不可用'
    assert r['source'] == plat


def test_platform_names():
    assert run(isr.try_platform_review_images('jd', 'x'))['name'] == '京东'
    assert run(isr.try_platform_review_images('pdd', 'x'))['name'] == '拼多多'
    assert run(isr.try_platform_review_images('taobao', 'x'))['name'] == '淘宝'


# ---------------- 聚合与降级 ----------------

def test_collect_order():
    """返回结果必须按 SOURCE_ORDER 排好"""
    results = run(isr.collect_all_sources('', keyword='', include_platforms=False))
    order = [r['source'] for r in results]
    assert order == ['baidu_image', 'baidu_keyword'], order


def test_collect_skips_when_no_input():
    """没图没关键词时两个源都应标 skipped"""
    results = run(isr.collect_all_sources('', keyword='', include_platforms=False))
    for r in results:
        assert r['status'] == 'skipped', r


def test_collect_includes_platforms():
    results = run(isr.collect_all_sources('', keyword='', include_platforms=True))
    srcs = [r['source'] for r in results]
    assert 'jd' in srcs and 'pdd' in srcs and 'taobao' in srcs
    # 平台排在百度后面
    assert srcs.index('jd') > srcs.index('baidu_keyword')


def test_collect_degrades_on_source_failure(monkeypatch):
    """一个源抛异常，不应影响整体返回"""
    async def boom(*a, **kw):
        raise RuntimeError('模拟接口挂了')

    async def ok_keyword(*a, **kw):
        return ['http://x/1.jpg', 'http://x/2.jpg']

    monkeypatch.setattr(isr, 'search_by_image', boom)
    monkeypatch.setattr(isr, 'search_by_keyword', ok_keyword)

    results = run(isr.collect_all_sources('fake.jpg', keyword='插排', include_platforms=False))

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

    run(isr.collect_all_sources('fake.jpg', keyword='', include_platforms=False))
    assert captured.get('kw') == '智能插排', '应复用识图识别出的关键词'


def test_collect_empty_source_marks_empty(monkeypatch):
    async def empty_image(*a, **kw):
        return [], ''

    async def empty_keyword(*a, **kw):
        return []

    monkeypatch.setattr(isr, 'search_by_image', empty_image)
    monkeypatch.setattr(isr, 'search_by_keyword', empty_keyword)

    results = run(isr.collect_all_sources('fake.jpg', keyword='x', include_platforms=False))
    for r in results:
        assert r['status'] == 'empty', r


def test_source_order_constant():
    assert isr.SOURCE_ORDER[0] == 'baidu_image'
    assert isr.SOURCE_ORDER[-1] == 'taobao'
    assert len(isr.SOURCE_ORDER) == 5


def test_source_labels_complete():
    for s in isr.SOURCE_ORDER:
        assert s in isr.SOURCE_LABELS, '缺少 %s 的显示名' % s
