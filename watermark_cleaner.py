# -*- coding: utf-8 -*-
"""通用去水印模块
方案：GLM-4V定位水印区域 → LaMa修复 → 羽化贴回关键区域
适用于任意商品图片，不依赖固定坐标
"""
import cv2
import numpy as np
import os
import base64
import threading
from PIL import Image
from io import BytesIO

# LaMa模型单例（避免重复加载）
# 加锁防止多线程同时 check-then-set 各加载一份模型（每份约 200MB+）
_lama_instance = None
_lama_lock = threading.Lock()
_lama_unavailable = False


def get_lama():
    """获取 LaMa 单例。不可用时返回 None（调用方需降级处理）"""
    global _lama_instance, _lama_unavailable
    if _lama_instance is not None:
        return _lama_instance
    if _lama_unavailable:
        return None
    with _lama_lock:
        # 双重检查：等锁期间可能已被其他线程加载/判定失败
        if _lama_instance is not None:
            return _lama_instance
        if _lama_unavailable:
            return None
        try:
            # 走 _lama_load_cpu：它会先 patch torch.jit.load 的 map_location，
            # 否则纯 CPU 机器加载 CUDA 导出的 big-lama.pt 会抛 NotImplementedError
            _lama_instance = _lama_load_cpu()
        except Exception as e:
            print(f"    ⚠ LaMa 不可用（{type(e).__name__}: {e}），降级使用 OpenCV inpaint")
            _lama_unavailable = True
            return None
    return _lama_instance


def _cv2_inpaint(img_bgr, mask):
    """LaMa 不可用时的兜底修复：OpenCV Telea 算法

    效果弱于 LaMa，但零额外依赖，打包体积无增长，保证功能不会静默失效。
    """
    return cv2.inpaint(img_bgr, mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)


def _img_to_base64(img_path):
    """图片转base64"""
    with open(img_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _get_vision_llm():
    """获取视觉模型客户端（复用 llm_provider 的统一配置）

    去水印必须用能看图的模型，因此单独取 vision 配置，
    与写文案的 text 模型互不影响。
    """
    try:
        import llm_provider
        llm = llm_provider.get_llm('vision')
        return llm if llm.available() else None
    except Exception:
        pass

    # 极端情况下退回环境变量 + 智谱官方地址
    api_key = (os.environ.get("ZHIPUAI_API_KEY") or "").strip()
    if not api_key or "在此填入" in api_key:
        return None
    try:
        import llm_provider
        return llm_provider.LLM('vision', {
            'provider': 'zhipu',
            'base_url': llm_provider.ZHIPU_BASE,
            'api_key': api_key,
            'model': llm_provider.DEFAULT_VISION_MODEL,
        })
    except Exception:
        return None


def _parse_watermark_answer(answer):
    """解析 GLM 的回答，判断是否含水印。

    返回 True(有) / False(无) / None(无法判断)

    注意：不能用 `'有' in answer` —— "没有水印"、"无水印" 都含有"有"字，
    会把干净的图误判成有水印，进而用默认区域把图片抹坏。
    """
    if not answer:
        return None
    text = answer.strip()

    # 1. 明确的否定短语（优先于单个"有"字判断）
    if '无水印' in text or '没有水印' in text:
        return False
    # 2. 明确的肯定短语
    if '有水印' in text:
        return True
    # 3. 其他否定表述
    if '没有' in text or '未见' in text or '未发现' in text or '不含' in text or '看不到' in text:
        return False
    if text.startswith('无') or text.startswith('没'):
        return False
    # 4. 到这里已排除否定，含"有"即可判为有水印
    #    （GLM 常复述问法，如"图上有半透明水印文字"，以"图"开头但确实有水印）
    if '有' in text:
        return True

    return None


def _detect_watermark_region_glm4v(img_path):
    """
    用GLM-4V-Flash检测水印文字位置
    返回水印区域的百分比坐标 [y1%, y2%, x1%, x2%] 或 None
    """
    llm = _get_vision_llm()
    if llm is None:
        print("  ⚠ 未配置视觉模型，跳过水印检测")
        return None, None
    img_b64 = _img_to_base64(img_path)

    try:
        answer = llm.ask_image(
            img_b64,
            "图上有无半透明水印文字（店铺名/禁止盗图等）？有多块水印则分别回答，"
            "格式：y1,y2,x1,x2;y1,y2,x1,x2;... 无水印则回答'无水印'",
            max_tokens=200,
            temperature=0.1,
            timeout=45,
        )

        has_wm = _parse_watermark_answer(answer)
        if has_wm is False:
            return False, None  # 确认无水印

        # 尝试提取多组坐标（分号分隔）
        import re
        regions = []
        # 按分号分割多块水印
        parts = re.split(r'[;；]', answer)
        for part in parts:
            m = re.search(r'(\d+)[,，](\d+)[,，](\d+)[,，](\d+)', part)
            if m:
                y1, y2, x1, x2 = [int(x) for x in m.groups()]
                if 0 <= y1 < y2 <= 100 and 0 <= x1 < x2 <= 100 and (y2 - y1) > 3 and (x2 - x1) > 3:
                    regions.append((y1, y2, x1, x2))
        
        if regions:
            return True, regions  # 返回多区域列表

        # 判断为有水印但没给出合法坐标：
        # 原实现会退回默认区域 (30,55,5,92)，即把图片中部整条 25% 高度抹掉重绘，
        # 一旦 GLM 误判就直接毁掉商品主体。宁可不处理，也不乱抹。
        if has_wm is True:
            print("    ⚠ 判定有水印但未给出可用坐标，跳过修复以保护画面")
            return None, None

        return None, None  # 不确定
    except Exception as e:
        print(f"    GLM-4V定位失败: {e}")
        return None, None


def _feather_blend(result, original, y1, y2, x1, x2, feather=12):
    """羽化贴回：中心用修复结果，边缘渐变过渡回原图，避免明显接缝

    blend_mask 语义：1.0 = 完全采用 result（LaMa 修复结果），0.0 = 完全采用 original
    区域中心为 1.0，向四周 feather 像素内线性衰减到 0，形成无缝过渡。
    """
    h, w = result.shape[:2]
    blend_mask = np.zeros((h, w), dtype=np.float32)
    blend_mask[y1:y2, x1:x2] = 1.0

    # 羽化半径不能超过区域一半，否则中心永远到不了 1.0（小水印会残留）
    radius = max(1, min(feather, (y2 - y1) // 2, (x2 - x1) // 2))
    for i in range(radius):
        alpha = (i + 1) / radius  # 最外圈接近 0（保留原图），最内圈达到 1.0（采用修复）
        if y1 + i < y2:
            blend_mask[y1+i, x1:x2] = np.minimum(blend_mask[y1+i, x1:x2], alpha)
        if y2 - 1 - i > y1:
            blend_mask[y2-1-i, x1:x2] = np.minimum(blend_mask[y2-1-i, x1:x2], alpha)
        if x1 + i < x2:
            blend_mask[y1:y2, x1+i] = np.minimum(blend_mask[y1:y2, x1+i], alpha)
        if x2 - 1 - i > x1:
            blend_mask[y1:y2, x2-1-i] = np.minimum(blend_mask[y1:y2, x2-1-i], alpha)

    blend_mask = np.clip(blend_mask, 0, 1)
    if len(result.shape) == 3:
        blend_mask = blend_mask[:, :, np.newaxis]

    # blend_mask=1 处采用 result（已修复），=0 处采用 original（保留原像素）
    return (result * blend_mask + original * (1 - blend_mask)).astype(np.uint8)


def process_single_image(img_path, output_path, reference_image=None):
    """
    通用去水印处理单张图片
    1. GLM-4V检测并定位水印
    2. LaMa修复水印区域
    3. 羽化贴回关键区域避免变形

    参数：
        img_path: 输入图片路径
        output_path: 输出图片路径
        reference_image: 参考图（未使用，兼容接口）

    返回：output_path（成功）或 None（失败）
    """
    try:
        img = cv2.imread(img_path)
        if img is None:
            return None

        h, w = img.shape[:2]

        # 步骤1：GLM-4V检测水印
        has_watermark, region = _detect_watermark_region_glm4v(img_path)

        if has_watermark is False:
            # 确认无水印，直接复制
            import shutil
            shutil.copy2(img_path, output_path)
            return output_path

        if has_watermark is None or region is None:
            # 检测失败，保守处理（复制原图）
            import shutil
            shutil.copy2(img_path, output_path)
            return output_path

        # 有水印，region是多区域列表 [(y1,y2,x1,x2), ...]
        if not isinstance(region, list):
            region = [region]
        
        # 计算每个区域的像素坐标并扩展边界
        regions_px = []
        for y1_pct, y2_pct, x1_pct, x2_pct in region:
            y1, y2 = int(h * y1_pct / 100), int(h * y2_pct / 100)
            x1, x2 = int(w * x1_pct / 100), int(w * x2_pct / 100)
            pad = max(5, min(w, h) // 50)
            y1 = max(0, y1 - pad)
            y2 = min(h, y2 + pad)
            x1 = max(0, x1 - pad)
            x2 = min(w, x2 + pad)
            regions_px.append((y1, y2, x1, x2))

        # 步骤2：构建修复掩膜（包含所有水印区域）
        mask = np.zeros((h, w), dtype=np.uint8)
        for y1, y2, x1, x2 in regions_px:
            mask[y1:y2, x1:x2] = 255
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)), iterations=2)

        lama = get_lama()
        if lama is not None:
            # 第1轮LaMa
            pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            result = lama(pil_img, Image.fromarray(mask))
            result = cv2.cvtColor(np.array(result), cv2.COLOR_RGB2BGR)

            # 第2轮LaMa（缩小每个区域的mask，修复残留）
            mask2 = np.zeros((h, w), dtype=np.uint8)
            for y1, y2, x1, x2 in regions_px:
                margin_y = int((y2 - y1) * 0.1)
                margin_x = int((x2 - x1) * 0.1)
                mask2[max(0, y1 + margin_y):min(h, y2 - margin_y),
                      max(0, x1 + margin_x):min(w, x2 - margin_x)] = 255
            mask2 = cv2.dilate(mask2, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)

            pil_result = Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))
            result = lama(pil_result, Image.fromarray(mask2))
            result = cv2.cvtColor(np.array(result), cv2.COLOR_RGB2BGR)
        else:
            # 降级路径：OpenCV inpaint 兜底，保证去水印不会静默失效
            result = _cv2_inpaint(img, mask)

        # 步骤3：羽化贴回每个区域（保护关键区域不变形）
        for y1, y2, x1, x2 in regions_px:
            result = _feather_blend(result, img, y1, y2, x1, x2, feather=12)

        cv2.imwrite(output_path, result)
        return output_path

    except Exception as e:
        print(f"    去水印异常: {e}")
        # 出错时复制原图
        import shutil
        try:
            shutil.copy2(img_path, output_path)
        except Exception:
            pass
        return output_path


def check_watermark(img_path):
    """快速检测单张图片是否有水印（用于批量预筛）"""
    llm = _get_vision_llm()
    if llm is None:
        print("  ⚠ 未配置视觉模型，跳过水印检测")
        return None
    img_b64 = _img_to_base64(img_path)

    try:
        answer = llm.ask_image(
            img_b64,
            "图上有无水印文字？只回答'有'或'无'",
            max_tokens=16,
            temperature=0.1,
            timeout=45,
            retries=1,
        )
        return _parse_watermark_answer(answer)
    except Exception as e:
        print(f"    水印检测失败: {e}")
        return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python watermark_cleaner.py <图片路径>")
        sys.exit(1)

    result = process_single_image(sys.argv[1], "test_clean_output.jpg")
    if result:
        print(f"✓ 完成: {result}")
    else:
        print("✗ 失败")

# ============================================================
# 手动框选去水印
# ============================================================
# 场景：京东/拼多多评价图带红色「JD.COM京东」水印，位置每张都不一样。
# 自动检测不准（试过红色行投影和 GLM-4V 判断区域，6 张只对 3 张），
# 所以交给用户框一下，程序负责精准修复。
#
# 关键：**只抹框内的水印笔画，不是整块抹掉**。
# 实测整条横带全抹会覆盖画面 15.9%，修完插排中段一片模糊；
# 只抹红色文字笔画只覆盖 2.9%，背景和商品细节全部保留。

def _lama_load_cpu():
    """加载 LaMa（强制 CPU）

    simple_lama_inpainting 里 torch.jit.load 没传 map_location，
    而 big-lama.pt 是 CUDA 上导出的，纯 CPU 机器直接加载会抛
    NotImplementedError: Could not run 'aten::empty_strided' ... 'CUDA' backend。
    """
    import torch
    _orig = torch.jit.load

    def _patched(path, *a, **kw):
        kw.setdefault('map_location', 'cpu')
        return _orig(path, *a, **kw)

    torch.jit.load = _patched
    from simple_lama_inpainting import SimpleLama
    return SimpleLama()


def build_text_mask(img_bgr, box, dilate_px=5, red_only=True):
    """在指定框内生成"只覆盖水印笔画"的 mask

    box: (x1, y1, x2, y2) 像素坐标
    red_only: True 时只取红色像素（京东水印是红色）；
              框里如果水印不是红色，设为 False 会取"高对比度笔画"

    返回与原图同尺寸的 mask，框外全黑（不修），框内只有笔画为白。
    """
    import cv2
    import numpy as np

    h, w = img_bgr.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in box]
    x1, x2 = max(0, min(x1, x2)), min(w, max(x1, x2))
    y1, y2 = max(0, min(y1, y2)), min(h, max(y1, y2))
    full = np.zeros((h, w), np.uint8)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return full

    roi = img_bgr[y1:y2, x1:x2]

    if red_only:
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # 红色色相在环的两端，要取两段
        # S 取 45：太高（55）漏掉淡的水印，太低（30）会把商品本身的粉红抹掉。
        # 45 是实测下来既能抓到半透明水印、又不会误伤商品的平衡点。
        m1 = cv2.inRange(hsv, np.array([0, 45, 55]), np.array([15, 255, 255]))
        m2 = cv2.inRange(hsv, np.array([165, 45, 55]), np.array([180, 255, 255]))
        m = cv2.bitwise_or(m1, m2)
    else:
        # 兜底：取框内明显偏离背景的像素
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        med = int(np.median(gray))
        m = cv2.inRange(gray, 0, max(0, med - 25)) | cv2.inRange(gray, min(255, med + 25), 255)

    # 膨胀：水印是半透明的，边缘有抗锯齿，不扩几像素会留一圈红边
    if dilate_px > 0:
        m = cv2.dilate(m, np.ones((dilate_px, dilate_px), np.uint8), iterations=1)

    full[y1:y2, x1:x2] = m
    return full


def remove_watermark_in_box(img_path, out_path, box, dilate_px=5, max_width=1100,
                            mode='box'):
    """按用户框选的区域去水印

    mode:
      'box'  抹整个框（默认）。用户框多小就抹多小，水印一定去掉，
             代价是框里的背景也会被重绘。框得越紧损失越小。
      'text' 只抹框内的水印笔画（按颜色检测）。背景保留得最好，
             但水印颜色太淡时检测不到会漏（实测淡红水印只有 50% 命中）。

    实测结论：半透明水印的颜色随背景变化很大（白底上饱和度只有 20-30），
    靠颜色检测不可靠，所以默认用 'box'。

    返回 {'success', 'coverage', 'method', 'error'}
    """
    import os
    import cv2
    import numpy as np

    try:
        img = cv2.imread(img_path)
        if img is None:
            return {'success': False, 'error': '读不到图片'}

        # 大图先缩：4032x3024 直接进 LaMa 要 150 秒，缩到 1100 宽只要 7 秒，
        # 而闲鱼展示宽度也就 750，缩了没损失
        scale = 1.0
        if img.shape[1] > max_width:
            scale = max_width / float(img.shape[1])
            img = cv2.resize(img, (max_width, int(img.shape[0] * scale)),
                             interpolation=cv2.INTER_AREA)

        scaled_box = [v * scale for v in box]

        if mode == 'text':
            mask = build_text_mask(img, scaled_box, dilate_px=dilate_px)
        else:
            # 整个框全抹，只留 2px 内缩，避免把框外的边缘也带进去
            hh, ww = img.shape[:2]
            x1, y1, x2, y2 = [int(v) for v in scaled_box]
            x1, x2 = max(0, min(x1, x2)), min(ww, max(x1, x2))
            y1, y2 = max(0, min(y1, y2)), min(hh, max(y1, y2))
            mask = np.zeros((hh, ww), np.uint8)
            mask[y1:y2, x1:x2] = 255

        coverage = (mask > 0).sum() / float(mask.shape[0] * mask.shape[1])

        if coverage <= 0:
            return {'success': False,
                    'error': '框里没找到水印笔画，试试把框拖大一点，或者换个位置'}

        # 优先 LaMa，不行降级 OpenCV
        method = 'lama'
        try:
            lama = get_lama()
            if lama is not None:
                from PIL import Image
                out = lama(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)),
                           Image.fromarray(mask).convert('L'))
                fixed = cv2.cvtColor(np.array(out), cv2.COLOR_RGB2BGR)
            else:
                raise RuntimeError('LaMa 不可用')
        except Exception:
            method = 'opencv'
            fixed = _cv2_inpaint(img, mask)

        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
        cv2.imwrite(out_path, fixed, [int(cv2.IMWRITE_JPEG_QUALITY), 93])
        return {'success': True, 'coverage': round(coverage * 100, 2), 'method': method}
    except Exception as e:
        return {'success': False, 'error': '%s: %s' % (type(e).__name__, e)}
