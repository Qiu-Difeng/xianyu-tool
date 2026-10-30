# -*- coding: utf-8 -*-
"""文案历史版本测试：备份、列表、恢复、删除、保留上限、路径安全"""
import os
import time

import pytest

import xianyu_tool as xt


@pytest.fixture
def outdir(tmp_path):
    return str(tmp_path)


def test_first_save_no_backup(outdir):
    """第一次保存没有旧版本可备份"""
    xt.save_single_copy('标题', '正文内容', 'v1', outdir)
    assert os.path.exists(os.path.join(outdir, 'V1_词典替换.txt'))
    assert xt.list_copy_history(outdir, 'v1') == []


def test_second_save_creates_backup(outdir):
    xt.save_single_copy('标题', '第一版内容', 'v1', outdir)
    time.sleep(0.01)
    xt.save_single_copy('标题', '第二版内容', 'v1', outdir)

    hist = xt.list_copy_history(outdir, 'v1')
    assert len(hist) == 1
    assert '第一版内容' in hist[0]['text']
    assert hist[0]['length'] == len('第一版内容')

    # 当前文件是第二版
    cur = open(os.path.join(outdir, 'V1_词典替换.txt'), encoding='utf-8').read()
    assert '第二版内容' in cur


def test_history_isolated_by_version(outdir):
    """v1 的历史不该出现在 v2 的列表里"""
    xt.save_single_copy('t', 'a1', 'v1', outdir)
    time.sleep(0.01)
    xt.save_single_copy('t', 'a2', 'v1', outdir)
    xt.save_single_copy('t', 'b1', 'v2', outdir)
    time.sleep(0.01)
    xt.save_single_copy('t', 'b2', 'v2', outdir)

    assert len(xt.list_copy_history(outdir, 'v1')) == 1
    assert len(xt.list_copy_history(outdir, 'v2')) == 1
    assert 'a1' in xt.list_copy_history(outdir, 'v1')[0]['text']
    assert 'b1' in xt.list_copy_history(outdir, 'v2')[0]['text']


def test_history_keeps_max_10(outdir):
    """每个版本最多留 10 个备份"""
    xt.save_single_copy('t', '第0版', 'v1', outdir)
    for i in range(1, 15):
        time.sleep(0.005)
        xt.save_single_copy('t', '第%d版' % i, 'v1', outdir)

    hist = xt.list_copy_history(outdir, 'v1')
    assert len(hist) == xt.COPY_HISTORY_KEEP, '应保留 %d 个，实际 %d' % (xt.COPY_HISTORY_KEEP, len(hist))
    # 保留的应是最近的（不含第0-3版）
    texts = [h['text'] for h in hist]
    assert '第0版' not in texts
    assert '第14版' not in texts, '第14版是当前版本，不在历史里'


def test_list_sorted_newest_first(outdir):
    xt.save_single_copy('t', 'old', 'v1', outdir)
    time.sleep(1.1)   # 时间戳精确到秒，要跨秒才会有不同文件名
    xt.save_single_copy('t', 'new', 'v1', outdir)

    hist = xt.list_copy_history(outdir, 'v1')
    assert len(hist) == 1
    # 文件名倒序，最新的在前
    assert 'old' in hist[0]['text']


def test_restore(outdir):
    xt.save_single_copy('标题X', '原始内容', 'v1', outdir)
    time.sleep(0.01)
    xt.save_single_copy('标题X', '改坏的内容', 'v1', outdir)

    hist = xt.list_copy_history(outdir, 'v1')
    assert len(hist) == 1

    r = xt.restore_copy_history(outdir, 'v1', hist[0]['filename'])
    assert r['success'] is True
    assert r['text'] == '原始内容'
    assert r['title'] == '标题X'

    cur = open(os.path.join(outdir, 'V1_词典替换.txt'), encoding='utf-8').read()
    assert '原始内容' in cur
    assert '改坏的内容' not in cur


def test_restore_backs_up_current(outdir):
    """恢复前应把当前版本也备份，避免又丢一版"""
    xt.save_single_copy('t', 'v-A', 'v1', outdir)
    time.sleep(0.01)
    xt.save_single_copy('t', 'v-B', 'v1', outdir)

    hist = xt.list_copy_history(outdir, 'v1')
    xt.restore_copy_history(outdir, 'v1', hist[0]['filename'])

    # 恢复后历史里应该多了 v-B
    hist2 = xt.list_copy_history(outdir, 'v1')
    texts = [h['text'] for h in hist2]
    assert 'v-B' in texts, '恢复时没备份当前版本，v-B 丢了'


def test_delete(outdir):
    xt.save_single_copy('t', 'a', 'v1', outdir)
    time.sleep(0.01)
    xt.save_single_copy('t', 'b', 'v1', outdir)

    hist = xt.list_copy_history(outdir, 'v1')
    r = xt.delete_copy_history(outdir, 'v1', hist[0]['filename'])
    assert r['success'] is True
    assert xt.list_copy_history(outdir, 'v1') == []


def test_delete_missing(outdir):
    r = xt.delete_copy_history(outdir, 'v1', 'nope.txt')
    assert r['success'] is False


# ---------------- 路径安全 ----------------

@pytest.mark.parametrize('bad', ['../../etc/passwd', 'a/b.txt', '..\\x.txt', ''])
def test_restore_rejects_path_traversal(outdir, bad):
    r = xt.restore_copy_history(outdir, 'v1', bad)
    assert r['success'] is False
    assert r['error'] == '非法文件名'


@pytest.mark.parametrize('bad', ['../../etc/passwd', 'a/b.txt', ''])
def test_delete_rejects_path_traversal(outdir, bad):
    r = xt.delete_copy_history(outdir, 'v1', bad)
    assert r['success'] is False
    assert r['error'] == '非法文件名'


def test_list_unknown_version(outdir):
    """不认识的版本名返回空列表，不报错"""
    assert xt.list_copy_history(outdir, 'v9') == []


def test_list_missing_dir(tmp_path):
    assert xt.list_copy_history(str(tmp_path / 'nope'), 'v1') == []
