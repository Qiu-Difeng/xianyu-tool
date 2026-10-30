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
