# -*- coding: utf-8 -*-
"""文案处理纯函数测试：去 emoji、后处理、词典替换、违禁词检测"""
import module3_copywriter as mc


# ---------------- remove_emoji ----------------

def test_remove_emoji_basic():
    assert mc.remove_emoji('好看😀的商品') == '好看的商品'
    assert mc.remove_emoji('🔥热卖🔥') == '热卖'


def test_remove_emoji_keeps_chinese():
    """不能误伤中文和常用标点"""
    s = '这是一件很好的商品，价格实惠。联系电话：13800138000'
    assert mc.remove_emoji(s) == s


def test_remove_emoji_variation_selector():
    """❤️ 是 U+2764 + U+FE0F，两个都要删，否则粘贴到闲鱼会出现乱码方块"""
    out = mc.remove_emoji('喜欢❤️')
    assert '\ufe0f' not in out, '变体选择符残留'
    assert '\u2764' not in out
    assert out == '喜欢'


def test_remove_emoji_zero_width_joiner():
    """带 ZWJ 的复合 emoji 不能留不可见字符"""
    out = mc.remove_emoji('家里👨‍👩‍👧都爱用')
    assert '\u200d' not in out
    assert '家里' in out and '都爱用' in out


# ---------------- post_process ----------------

def test_post_process_replaces_banned_phrase():
    out = mc.post_process('白菜价出售')
    assert '白菜价' not in out
    assert '实惠价' in out


def test_post_process_cleans_empty_sentence():
    """删掉违禁短语后会留下 "，。" 这种空句，要清理"""
    out = mc.post_process('直接充电，快来入手吧。')
    assert '，。' not in out
    assert '快来入手吧' not in out


def test_post_process_collapses_periods():
    out = mc.post_process('很好。。真的')
    assert '。。' not in out


def test_post_process_strips_trailing_comma():
    out = mc.post_process('便宜好用，')
    assert not out.endswith('，')


# ---------------- v1_dict_replace ----------------

def test_v1_replaces_synonym():
    out = mc.v1_dict_replace('快来入手这个宝贝')
    assert '入手' not in out
    assert '拿下' in out or '购入' in out


def test_v1_keeps_unmatched_text():
    out = mc.v1_dict_replace('这是一段没有同义词的话')
    assert '没有同义词' in out


def test_v1_also_runs_post_process():
    """词典替换后仍要去 emoji、换违禁词"""
    out = mc.v1_dict_replace('白菜价😀')
    assert '😀' not in out
    assert '白菜价' not in out


# ---------------- filter_banned ----------------

def test_filter_banned_detects_word():
    hits = mc.filter_banned('这是全网第一好用的')
    assert '第一' in hits


def test_filter_banned_returns_list():
    assert isinstance(mc.filter_banned('正常文案'), list)


def test_filter_banned_single_char_safe_combo():
    """"最"是单字违禁词，但"最后""最新"等搭配算安全"""
    hits = mc.filter_banned('最后三件，最新款式')
    assert '最' not in hits, '安全搭配不应误报'


def test_filter_banned_single_char_unsafe_combo():
    """"最好"不在安全名单里，应该报出来"""
    hits = mc.filter_banned('这是最好用的')
    assert '最' in hits


def test_filter_banned_empty():
    assert mc.filter_banned('') == []


# ---------------- mask_key ----------------

def test_mask_key_long():
    import llm_provider as lp
    masked = lp.mask_key('1234567890abcdefghij')
    assert masked.startswith('123456')
    assert masked.endswith('ghij')
    assert '……' in masked
    assert len(masked) < 21


def test_mask_key_short():
    import llm_provider as lp
    assert lp.mask_key('short') == '已配置'


def test_mask_key_empty():
    import llm_provider as lp
    assert lp.mask_key('') == ''
    assert lp.mask_key(None) == ''
