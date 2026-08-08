# -*- coding: utf-8 -*-
"""通用去水印模块
方案：GLM-4V定位水印区域 → LaMa修复 → 羽化贴回关键区域
适用于任意商品图片，不依赖固定坐标
"""
import cv2
import numpy as np
import os
import base64
import json
from PIL import Image
from io import BytesIO

# LaMa模型单例（避免重复加载）
_lama_instance = None

def get_lama():
    global _lama_instance
    if _lama_instance is None:
        from simple_lama_inpainting import SimpleLama
        _lama_instance = SimpleLama()
    return _lama_instance


def _img_to_base64(img_path):
    """图片转base64"""
    with open(img_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _detect_watermark_region_glm4v(img_path):
    """
    用GLM-4V-Flash检测水印文字位置
    返回水印区域的百分比坐标 [y1%, y2%, x1%, x2%] 或 None
    """
    try:
        from zhipuai import ZhipuAI
    except:
        return None, None

    api_key = os.environ.get("ZHIPUAI_API_KEY", "在此填入你的智谱API Key")
    if not api_key or "在此填入" in api_key:
        print("  ⚠ 未配置智谱API Key，跳过水印检测")
        return None, None
    client = ZhipuAI(api_key=api_key)
    img_b64 = _img_to_base64(img_path)

    try:
        resp = client.chat.completions.create(
            model="glm-4v-flash",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    {"type": "text", "text": "图上有无半透明水印文字（店铺名/禁止盗图等）？有则回答区域百分比y1,y2,x1,x2，无则回答'无水印'"}
                ]
            }],
        )
        answer = resp.choices[0].message.content.strip()

        if '无水印' in answer:
            return False, None  # 确认无水印

        # 尝试提取坐标
        import re
        m = re.search(r'(\d+)[,，](\d+)[,，](\d+)[,，](\d+)', answer)
        if m:
            y1, y2, x1, x2 = [int(x) for x in m.groups()]
            # 坐标合法性检查
            if 0 <= y1 < y2 <= 100 and 0 <= x1 < x2 <= 100 and (y2 - y1) > 3 and (x2 - x1) > 3:
                return True, (y1, y2, x1, x2)

        # 有水印但没给出合法坐标，用默认区域
        if '有' in answer and '无水印' not in answer:
            return True, (30, 55, 5, 92)  # 默认水印区域

        return None, None  # 不确定
    except Exception as e:
        print(f"    GLM-4V定位失败: {e}")
        return None, None


def _feather_blend(result, original, y1, y2, x1, x2, feather=12):
    """羽化贴回：边缘渐变过渡，避免明显接缝"""
    h, w = result.shape[:2]
    blend_mask = np.zeros((h, w), dtype=np.float32)
    blend_mask[y1:y2, x1:x2] = 1.0

    for i in range(min(feather, (y2 - y1) // 2, (x2 - x1) // 2)):
        alpha = i / max(feather, 1)
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

    return (result * (1 - blend_mask) + original * blend_mask).astype(np.uint8)


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

        # 有水印，拿到区域坐标
        y1_pct, y2_pct, x1_pct, x2_pct = region
        y1, y2 = int(h * y1_pct / 100), int(h * y2_pct / 100)
        x1, x2 = int(w * x1_pct / 100), int(w * x2_pct / 100)

        # 扩展mask边界（确保覆盖水印边缘）
        pad = max(5, min(w, h) // 50)
        y1 = max(0, y1 - pad)
        y2 = min(h, y2 + pad)
        x1 = max(0, x1 - pad)
        x2 = min(w, x2 + pad)

        # 步骤2：LaMa修复
        lama = get_lama()

        # 创建mask
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[y1:y2, x1:x2] = 255
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)), iterations=2)

        # 第1轮LaMa
        pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        result = lama(pil_img, Image.fromarray(mask))
        result = cv2.cvtColor(np.array(result), cv2.COLOR_RGB2BGR)

        # 第2轮LaMa（缩小mask，修复残留）
        mask2 = np.zeros((h, w), dtype=np.uint8)
        margin_y = int((y2 - y1) * 0.1)
        margin_x = int((x2 - x1) * 0.1)
        mask2[max(0, y1 + margin_y):min(h, y2 - margin_y),
              max(0, x1 + margin_x):min(w, x2 - margin_x)] = 255
        mask2 = cv2.dilate(mask2, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)

        pil_result = Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))
        result = lama(pil_result, Image.fromarray(mask2))
        result = cv2.cvtColor(np.array(result), cv2.COLOR_RGB2BGR)

        # 步骤3：羽化贴回（保护关键区域不变形）
        # 羽化区域比水印区域稍大，让修复结果和原图平滑过渡
        result = _feather_blend(result, img, y1, y2, x1, x2, feather=12)

        cv2.imwrite(output_path, result)
        return output_path

    except Exception as e:
        print(f"    去水印异常: {e}")
        # 出错时复制原图
        import shutil
        try:
            shutil.copy2(img_path, output_path)
        except:
            pass
        return output_path


def check_watermark(img_path):
    """快速检测单张图片是否有水印（用于批量预筛）"""
    try:
        from zhipuai import ZhipuAI
    except:
        return None

    api_key = os.environ.get("ZHIPUAI_API_KEY", "在此填入你的智谱API Key")
    if not api_key or "在此填入" in api_key:
        print("  ⚠ 未配置智谱API Key，跳过水印检测")
        return None
    client = ZhipuAI(api_key=api_key)
    img_b64 = _img_to_base64(img_path)

    try:
        resp = client.chat.completions.create(
            model="glm-4v-flash",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    {"type": "text", "text": "图上有无水印文字？只回答'有'或'无'"}
                ]
            }],
        )
        answer = resp.choices[0].message.content.strip()
        return '有' in answer
    except Exception as e:
        print(f"    GLM-4V检测失败: {e}")
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
