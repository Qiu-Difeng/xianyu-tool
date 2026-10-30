# -*- coding: utf-8 -*-
"""解析辅助函数测试

parse_api_body / fallback_title_from_dom / match_captured_images 都是纯逻辑，
不需要真的开浏览器。resolve_short_url 只测不需要发请求的分支。
"""
import asyncio
import json

import pytest

import module1_parser as mp


# ---------------- parse_api_body ----------------

def make_payload(item=None, seller=None, ret='SUCCESS::调用成功'):
    """构造一份接近闲鱼真实结构的响应"""
    data = {'ret': [ret]}
    inner = {}
    if item is not None:
        inner['itemDO'] = item
    if seller is not None:
        inner['sellerDO'] = seller
    data['data'] = inner
    return json.dumps(data, ensure_ascii=False)


def test_parse_api_body_standard():
    payload = make_payload(
        item={
            'title': '米用家用多功能插座',
            'desc': '白色简约设计',
            'soldPrice': '5.99',
            'itemId': 851035319812,
            'imageInfos': [{'url': '//img.alicdn.com/O1CN0abc.jpg'}],
        },
        seller={'desensitizationNick': '端庄的红枣'},
    )
    out = mp.parse_api_body(payload)
    assert out['title'] == '米用家用多功能插座'
    assert out['desc'] == '白色简约设计'
    assert out['price'] == '5.99'
    assert out['item_id'] == '851035319812'
    assert out['image_urls'] == ['https://img.alicdn.com/O1CN0abc.jpg']
    assert out['seller'] == '端庄的红枣'


def test_parse_api_body_jsonp_wrapped():
    """闲鱼有时返回 callback({...}) 形式"""
    payload = 'mtopjsonp3(' + make_payload(item={'title': '测试商品'}) + ')'
    out = mp.parse_api_body(payload)
    assert out['title'] == '测试商品'


def test_parse_api_body_price_fallback():
    """没有 soldPrice 时退回 price 字段"""
    payload = make_payload(item={'title': 'x', 'price': '12.8'})
    out = mp.parse_api_body(payload)
    assert out['price'] == '12.8'


def test_parse_api_body_images_fallback():
    """没有 imageInfos 时用 images 数组"""
    payload = make_payload(item={'title': 'x', 'images': ['//a.com/1.jpg', '//a.com/2.jpg']})
    out = mp.parse_api_body(payload)
    assert len(out['image_urls']) == 2
    assert all(u.startswith('https://') for u in out['image_urls'])


def test_parse_api_body_video():
    payload = make_payload(item={'title': 'x', 'videoInfos': [{'url': 'https://v.com/a.mp4'}]})
    out = mp.parse_api_body(payload)
    assert out['video_url'] == 'https://v.com/a.mp4'


def test_parse_api_body_video_fallback():
    payload = make_payload(item={'title': 'x', 'videoUrl': 'https://v.com/b.mp4'})
    out = mp.parse_api_body(payload)
    assert out['video_url'] == 'https://v.com/b.mp4'


def test_parse_api_body_nested_itemdo():
    """itemDO 不在原位时，从 data 里找带 title 的那层"""
    payload = json.dumps({'data': {'otherKey': {'title': '藏起来的标题'}}}, ensure_ascii=False)
    out = mp.parse_api_body(payload)
    assert out['title'] == '藏起来的标题'


def test_parse_api_body_invalid_json():
    assert mp.parse_api_body('not a json at all') == {}


def test_parse_api_body_empty():
    assert mp.parse_api_body('') == {}
    assert mp.parse_api_body(None) == {}


def test_parse_api_body_no_item():
    payload = json.dumps({'data': {}}, ensure_ascii=False)
    assert mp.parse_api_body(payload) == {}


def test_parse_api_body_keeps_current_item_id():
    """API 没给 itemId 时保留传入的 item_id"""
    payload = make_payload(item={'title': 'x'})
    out = mp.parse_api_body(payload, current_item_id='999')
    assert out['item_id'] == '999'


def test_parse_api_body_skips_bad_image_entries():
    payload = make_payload(item={
        'title': 'x',
        'imageInfos': [{'url': '//a.com/1.jpg'}, {}, {'no_url': 1}, 'not a dict'],
    })
    out = mp.parse_api_body(payload)
    assert out['image_urls'] == ['https://a.com/1.jpg']


# ---------------- match_captured_images ----------------

def test_match_captured_images_hit():
    urls = ['https://img.alicdn.com/O1CN0aaa.jpg', 'https://img.alicdn.com/O1CN0bbb.jpg']
    captured = {'O1CN0aaa': b'data-a', 'O1CN0bbb': b'data-b', 'O1CN0zzz': b'other'}
    out = mp.match_captured_images(urls, captured)
    assert len(out) == 2
    assert out[urls[0]] == b'data-a'
    assert out[urls[1]] == b'data-b'


def test_match_captured_images_partial():
    """只有部分 URL 能对上时，只返回对上的"""
    urls = ['https://x.com/O1CN0aaa.jpg', 'https://x.com/nowhere.jpg']
    captured = {'O1CN0aaa': b'd'}
    out = mp.match_captured_images(urls, captured)
    assert len(out) == 1


def test_match_captured_images_empty_inputs():
    assert mp.match_captured_images([], {}) == {}
    assert mp.match_captured_images(['https://x.com/a.jpg'], {}) == {}
    assert mp.match_captured_images([], {'O1CN0a': b'1'}) == {}


def test_match_captured_images_url_without_id():
    """URL 里没有 O1CN0 图 ID 时跳过，不报错"""
    out = mp.match_captured_images(['https://x.com/plain.jpg'], {'O1CN0a': b'1'})
    assert out == {}


# ---------------- fallback_title_from_dom ----------------

class FakeElement:
    def __init__(self, text='', content=None):
        self._text = text
        self._content = content

    async def get_attribute(self, name):
        return self._content

    async def inner_text(self):
        return self._text


class FakePage:
    """按选择器返回预设元素"""
    def __init__(self, mapping):
        self._mapping = mapping
        self.calls = []

    async def query_selector(self, sel):
        self.calls.append(sel)
        return self._mapping.get(sel)


def test_fallback_keeps_existing_title():
    """已有标题时不该去查 DOM"""
    page = FakePage({})
    out = asyncio.run(mp.fallback_title_from_dom(page, '原标题'))
    assert out == '原标题'
    assert page.calls == []


def test_fallback_picks_h1():
    page = FakePage({'h1': FakeElement('页面上的标题')})
    out = asyncio.run(mp.fallback_title_from_dom(page, ''))
    assert out == '页面上的标题'


def test_fallback_uses_meta_content():
    page = FakePage({'meta[property="og:title"]': FakeElement(content='meta里的标题')})
    out = asyncio.run(mp.fallback_title_from_dom(page, ''))
    assert out == 'meta里的标题'


def test_fallback_skips_error_page():
    """错误页的标题要跳过，继续找下一个选择器"""
    page = FakePage({'h1': FakeElement('页面不存在'),
                     '[class*="title"]': FakeElement('真的商品标题')})
    out = asyncio.run(mp.fallback_title_from_dom(page, ''))
    assert out == '真的商品标题'


def test_fallback_skips_too_short():
    page = FakePage({'h1': FakeElement('短'), '[class*="title"]': FakeElement('够长的标题文本')})
    out = asyncio.run(mp.fallback_title_from_dom(page, ''))
    assert out == '够长的标题文本'


def test_fallback_returns_empty_when_nothing_found():
    page = FakePage({})
    out = asyncio.run(mp.fallback_title_from_dom(page, ''))
    assert out == ''


# ---------------- resolve_short_url（只测不需要发请求的分支）----------------

def test_resolve_full_url_with_item_id():
    """已经是完整链接 + 有 item_id 时，直接拼标准地址"""
    url, iid = asyncio.run(mp.resolve_short_url('https://www.goofish.com/item?id=123', '123'))
    assert url == 'https://www.goofish.com/item?id=123'
    assert iid == '123'


def test_resolve_full_url_without_item_id():
    """既不是短链也没 item_id 时原样返回"""
    url, iid = asyncio.run(mp.resolve_short_url('https://example.com/x', ''))
    assert url == 'https://example.com/x'
    assert iid == ''
