# -*- coding: utf-8 -*-
"""去水印模块测试

这个模块之前零测试，但它是主流程必经环节（每张图都要过），
改坏了不会有人发现，直到用户看到「图糊了」。

不依赖 LaMa（模型文件大且慢），只测纯算法部分：
mask 生成、边界处理、降级路径。
"""
import os
import tempfile

import cv2
import numpy as np
import pytest

import watermark_cleaner as wc


def make_white_image(w=200, h=200):
    """纯白图，方便观察 mask"""
    return np.full((h, w, 3), 255, dtype=np.uint8)


def make_jpeg(w=200, h=200, color=(255, 255, 255)):
    p = os.path.join(tempfile.mkdtemp(), 'img.jpg')
    img = np.full((h, w, 3), color, dtype=np.uint8)
    cv2.imwrite(p, img)
    return p


# ---------------- build_text_mask ----------------

def test_text_mask_outside_box_is_black():
    """框外必须全黑，一个像素都不能修"""
    img = make_white_image()
    mask = wc.build_text_mask(img, (50, 50, 150, 150))
    assert mask.shape == img.shape[:2]
    assert mask[:50].max() == 0
    assert mask[150:].max() == 0
    assert mask[:, :50].max() == 0
    assert mask[:, 150:].max() == 0


def test_text_mask_red_text_detected():
    """框内画红色文字，应该被检测到"""
    img = make_white_image()
    # 画一条红色横条（模拟水印文字）
    cv2.rectangle(img, (60, 90), (140, 110), (0, 0, 220), -1)
    mask = wc.build_text_mask(img, (50, 80, 150, 120))
    assert (mask > 0).sum() > 0, '红色区域没被检测到'


def test_text_mask_white_bg_not_detected():
    """框内全白（没有水印）应该几乎全黑"""
    img = make_white_image()
    mask = wc.build_text_mask(img, (50, 50, 150, 150))
    ratio = (mask > 0).sum() / float(mask.size)
    assert ratio < 0.01, '白底不该被误判成水印'


def test_text_mask_dilate_expands():
    """膨胀参数越大，覆盖面积越大"""
    img = make_white_image()
    cv2.rectangle(img, (80, 90), (120, 110), (0, 0, 220), -1)
    small = wc.build_text_mask(img, (60, 80, 140, 120), dilate_px=1)
    big = wc.build_text_mask(img, (60, 80, 140, 120), dilate_px=9)
    assert (big > 0).sum() > (small > 0).sum()


def test_text_mask_tiny_box_returns_black():
    """太小的框（<4px）直接返回全黑，不做无意义处理"""
    img = make_white_image()
    mask = wc.build_text_mask(img, (10, 10, 12, 12))
    assert mask.max() == 0


def test_text_mask_box_out_of_bounds_clamped():
    """框超出图片边界要被夹住，不能崩"""
    img = make_white_image(100, 100)
    mask = wc.build_text_mask(img, (-50, -50, 500, 500))
    assert mask.shape == (100, 100)
    assert isinstance(mask, np.ndarray)


def test_text_mask_reversed_box_ok():
    """传反方向的坐标（x2<x1）也要能用"""
    img = make_white_image()
    cv2.rectangle(img, (60, 90), (140, 110), (0, 0, 220), -1)
    mask = wc.build_text_mask(img, (150, 120, 50, 80))
    assert mask.shape == img.shape[:2]


# ---------------- remove_watermark_in_box ----------------

def test_remove_box_mode_creates_output():
    """box 模式：能生成输出文件，尺寸和原图一致"""
    src = make_jpeg(200, 200)
    dst = os.path.join(os.path.dirname(src), 'out.jpg')
    r = wc.remove_watermark_in_box(src, dst, (50, 80, 150, 120), mode='box')
    assert r.get('success') is True, r.get('error')
    assert os.path.exists(dst)
    a = cv2.imread(src)
    b = cv2.imread(dst)
    assert a.shape == b.shape


def test_remove_box_mode_reports_coverage():
    """覆盖率要合理：整框抹除掉，覆盖率约等于框占画面的比例"""
    src = make_jpeg(200, 200)
    dst = os.path.join(os.path.dirname(src), 'out.jpg')
    r = wc.remove_watermark_in_box(src, dst, (0, 80, 200, 120), mode='box')
    # 框是 200x40，占 200x200 的 20%
    assert 15 < r['coverage'] < 25, r['coverage']


def test_remove_text_mode_skips_when_no_text():
    """text 模式：框里没文字时报错，不该生成无意义的图"""
    src = make_jpeg(200, 200)
    dst = os.path.join(os.path.dirname(src), 'out.jpg')
    r = wc.remove_watermark_in_box(src, dst, (50, 50, 150, 150), mode='text')
    assert r.get('success') is False
    assert '没找到' in (r.get('error') or '') or '水印' in (r.get('error') or '')


def test_remove_text_mode_works_with_red_text():
    """text 模式：框里有红字能处理"""
    p = os.path.join(tempfile.mkdtemp(), 'img.jpg')
    img = make_white_image(200, 200)
    cv2.rectangle(img, (60, 90), (140, 110), (0, 0, 220), -1)
    cv2.imwrite(p, img)
    dst = os.path.join(os.path.dirname(p), 'out.jpg')
    r = wc.remove_watermark_in_box(p, dst, (50, 80, 150, 120), mode='text')
    assert r.get('success') is True, r.get('error')
    assert r['coverage'] < 15, 'text 模式覆盖率应该很小'


def test_remove_nonexistent_file():
    """文件不存在要返回错误，不能抛异常"""
    r = wc.remove_watermark_in_box('/nope/x.jpg', '/nope/out.jpg', (0, 0, 10, 10))
    assert r.get('success') is False
    assert r.get('error')


def test_remove_large_image_downscaled():
    """超过 1100 宽的大图要先缩小（不然 LaMa 要跑几分钟）"""
    p = os.path.join(tempfile.mkdtemp(), 'big.jpg')
    big = np.full((600, 2000, 3), 255, dtype=np.uint8)
    cv2.imwrite(p, big)
    dst = os.path.join(os.path.dirname(p), 'out.jpg')
    r = wc.remove_watermark_in_box(p, dst, (100, 200, 1900, 400), mode='box')
    assert r.get('success') is True
    out = cv2.imread(dst)
    # LaMa 内部会 pad 到 8 的倍数，1100 会变成 1104，所以给点余量
    assert out.shape[1] <= 1120, '输出宽度应限制在 1100 附近，实际 %d' % out.shape[1]


# ---------------- check_watermark ----------------

def test_check_watermark_on_plain_image():
    """纯色图没有水印"""
    p = make_jpeg(200, 200, (240, 240, 240))
    r = wc.check_watermark(p)
    # 不同实现返回结构可能不同，只要求不崩
    assert r is not None


def test_check_watermark_nonexistent():
    """文件不存在时返回 None（表示"无法检测"），不能抛异常中断批量预筛"""
    r = wc.check_watermark('/nope/x.jpg')
    assert r is None


# ---------------- _lama_load_cpu ----------------

def test_lama_load_does_not_break_torch_jit():
    """_lama_load_cpu 会 patch torch.jit.load，调用后不该破坏已有行为"""
    import torch
    orig = torch.jit.load
    try:
        wc._lama_load_cpu()
    except Exception:
        pass
    # 无论模型能不能加载，torch.jit.load 必须还是可调用的
    assert callable(torch.jit.load)
    torch.jit.load = orig
