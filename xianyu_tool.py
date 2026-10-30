# -*- coding: utf-8 -*-
"""闲鱼辅助工具 - 一键全流程（模块4：集成主控）

输入：闲鱼商品分享链接
输出：
  output/<商品ID>/
    ├── original/         原始商品图（带水印）
    ├── clean/            去水印后的商品图
    ├── search/           百度识图搜到的干净补充图
    ├── copies/           三版本文案（V1/V2/V3）
    └── result.json       全部数据汇总

流程：
  1. 模块1：解析链接 → 标题、文案、价格、图片URL
  2. 模块2：下载原始图片
  3. 模块3a：去水印（多模态AI定位 + LaMa修复）
  4. 模块3b：AI文案改写（V1词典/V2微调/V3重写）
  5. 模块5：百度识图搜补充图 + GLM-4V-Flash水印过滤
  6. 一键保存所有产出

依赖：playwright, httpx, zhipuai, opencv-python, Pillow, numpy
"""
import asyncio
import json
import threading
import os
import sys
import time
import shutil
import httpx
import base64
import re
from pathlib import Path

# ============================================================
# 路径配置
# ============================================================
if getattr(sys, 'frozen', False):
    WORKSPACE = sys._MEIPASS
else:
    WORKSPACE = os.path.dirname(os.path.abspath(__file__))
# 输出到系统临时目录，每次运行前自动清空，最多只留最新一次
OUTPUT_ROOT = os.path.join(os.environ.get('TEMP', os.path.expanduser('~')), 'xianyu_tool')
# 注意：这里不能删除 OUTPUT_ROOT 本身 —— anti_detect 的每日请求计数器
# （request_count.json）也放在这个目录下，删掉会导致每次启动都从 0 重新计数，
# 30 次/天的限额形同虚设。清理动作统一放到 run() 里，只删 output 子目录。
os.makedirs(OUTPUT_ROOT, exist_ok=True)
# PYTHON路径已移除（未使用，改为sys.executable动态获取）

sys.path.insert(0, WORKSPACE)
from module1_parser import parse_xianyu

# ============================================================
# 模块2：图片下载
# ============================================================
async def download_product_images(image_urls, output_dir, captured_images=None):
    os.makedirs(output_dir, exist_ok=True)
    downloaded = []
    
    print(f"\n{'='*60}")
    print(f"模块2：下载商品图片（{len(image_urls)}张）")
    print(f"{'='*60}")
    
    if captured_images:
        print(f"  使用Playwright拦截的图片数据（{len(captured_images)}张）")
        for i, url in enumerate(image_urls):
            ext = ".jpg"
            out_path = os.path.join(output_dir, f"img_{i+1:02d}{ext}")
            
            img_data = captured_images.get(url)
            if not img_data:
                m = re.search(r'(O1CN0\w+)', url)
                if m:
                    img_id = m.group(1)
                    for cap_url, cap_data in captured_images.items():
                        if img_id in cap_url:
                            img_data = cap_data
                            break
            
            if img_data and len(img_data) > 5000:
                if img_data[:4] == b'RIFF' or img_data[:4] == b'WEBP':
                    try:
                        from PIL import Image
                        import io
                        pil_img = Image.open(io.BytesIO(img_data))
                        pil_img.convert('RGB').save(out_path, 'JPEG', quality=95)
                    except Exception:
                        with open(out_path, "wb") as f:
                            f.write(img_data)
                else:
                    with open(out_path, "wb") as f:
                        f.write(img_data)
                downloaded.append(out_path)
                print(f"  [{i+1}] ✓ {len(img_data)//1024}KB (拦截)")
            else:
                print(f"  [{i+1}] ⚠ 拦截数据未匹配，尝试URL下载")
                async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                    try:
                        resp = await client.get(url, headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            "Referer": "https://h5.m.goofish.com/",
                        })
                        if resp.status_code == 200 and len(resp.content) > 5000:
                            with open(out_path, "wb") as f:
                                f.write(resp.content)
                            downloaded.append(out_path)
                            print(f"  [{i+1}] ✓ {len(resp.content)//1024}KB (下载)")
                        else:
                            print(f"  [{i+1}] ✗ 下载失败 status={resp.status_code}")
                    except Exception as e:
                        print(f"  [{i+1}] ✗ {e}")
    else:
        print(f"  使用URL直接下载")
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            for i, url in enumerate(image_urls):
                ext = ".jpg"
                out_path = os.path.join(output_dir, f"img_{i+1:02d}{ext}")
                
                try:
                    resp = await client.get(url, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Referer": "https://h5.m.goofish.com/",
                    })
                    if resp.status_code == 200 and len(resp.content) > 5000:
                        if resp.content[:4] == b'RIFF' or resp.content[:4] == b'WEBP':
                            try:
                                from PIL import Image
                                import io
                                pil_img = Image.open(io.BytesIO(resp.content))
                                pil_img.convert('RGB').save(out_path, 'JPEG', quality=95)
                            except Exception:
                                with open(out_path, "wb") as f:
                                    f.write(resp.content)
                        else:
                            with open(out_path, "wb") as f:
                                f.write(resp.content)
                        downloaded.append(out_path)
                        print(f"  [{i+1}] ✓ {len(resp.content)//1024}KB")
                    else:
                        print(f"  [{i+1}] ✗ status={resp.status_code}")
                except Exception as e:
                    print(f"  [{i+1}] ✗ {e}")
    
    print(f"  下载完成: {len(downloaded)}/{len(image_urls)}张")
    return downloaded


# ============================================================
# 模块3a：去水印
# ============================================================
from watermark_cleaner import check_watermark as _check_watermark_with_glm4v


def remove_watermarks(image_paths, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    clean_images = []
    
    print(f"\n{'='*60}")
    print(f"模块3a：去水印（{len(image_paths)}张）")
    print(f"{'='*60}")
    
    print(f"  逐张检测水印（{len(image_paths)}张，并发3）...")
    need_process = []
    no_watermark = []
    
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def _check_one(img_path):
        """检测单张；GLM 并发限流时易失败，失败重试一次"""
        has_wm = _check_watermark_with_glm4v(img_path)
        if has_wm is None:
            has_wm = _check_watermark_with_glm4v(img_path)
        return has_wm
    
    results_map = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_check_one, p): p for p in image_paths}
        for future in as_completed(futures):
            p = futures[future]
            try:
                results_map[p] = future.result()
            except Exception:
                results_map[p] = None
    
    # 按原始顺序归集，便于用户对照原图
    for img_path in image_paths:
        img_name = os.path.basename(img_path)
        has_wm = results_map.get(img_path)
        if has_wm is True:
            print(f"    {img_name}: 有水印，需处理")
            need_process.append(img_path)
        elif has_wm is False:
            print(f"    {img_name}: 无水印，跳过")
            no_watermark.append(img_path)
        else:
            print(f"    {img_name}: 检测失败，保守处理")
            need_process.append(img_path)
    
    # 输入路径 -> 输出路径，最后按原始顺序组装，避免 no_watermark 与
    # need_process 分两批 append、且线程池 as_completed 乱序导致结果错位
    output_map = {}

    for img_path in no_watermark:
        img_name = os.path.basename(img_path)
        dst = os.path.join(output_dir, img_name)
        shutil.copy2(img_path, dst)
        output_map[img_path] = dst
    
    if need_process:
        print(f"\n  {len(need_process)}张需要去水印，启动修复...")
        try:
            from watermark_cleaner import process_single_image
            
            # 并行处理多张图片（用线程池）
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            def _process_one(img_path):
                img_name = os.path.basename(img_path)
                out_path = os.path.join(output_dir, img_name)
                try:
                    result_path = process_single_image(img_path, out_path)
                    if result_path and os.path.exists(result_path):
                        return (img_path, result_path, True)
                    else:
                        shutil.copy2(img_path, out_path)
                        return (img_path, out_path, False)
                except Exception:
                    shutil.copy2(img_path, out_path)
                    return (img_path, out_path, False)
            
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(_process_one, img): img for img in need_process}
                for future in as_completed(futures):
                    img_path = futures[future]
                    img_name = os.path.basename(img_path)
                    orig_path, result_path, success = future.result()
                    output_map[img_path] = result_path
                    print(f"    {'✓' if success else '⚠(用原图)'} {img_name}")
        except ImportError:
            print(f"  去水印模块未导入，有水印图片暂用原图")
            for img_path in need_process:
                img_name = os.path.basename(img_path)
                dst = os.path.join(output_dir, img_name)
                shutil.copy2(img_path, dst)
                output_map[img_path] = dst
    else:
        print(f"  所有图片均无水印，无需处理")

    # 按输入顺序组装，顺序与 original/ 目录一致
    for img_path in image_paths:
        dst = output_map.get(img_path)
        if dst and os.path.exists(dst):
            clean_images.append(dst)

    print(f"  去水印完成: {len(clean_images)}/{len(image_paths)}张")
    return clean_images


# ============================================================
# 模块3b：AI文案改写
# ============================================================
from module3_copywriter import generate_versions, regenerate_v1, regenerate_v2, regenerate_v3, filter_banned

def generate_copywriting(title, desc):
    print(f"\n{'='*60}")
    print(f"模块3b：AI文案改写")
    print(f"{'='*60}")
    
    result = generate_versions(title, desc)
    
    print(f"\n  V1 词典替换: {len(result['v1'])}字")
    print(f"  V2 AI微调:   {len(result['v2'])}字")
    print(f"  V3 AI重写:   {len(result['v3'])}字")
    
    for ver in ['v1', 'v2', 'v3']:
        warnings = result['banned_warnings'][ver]
        if warnings:
            print(f"  ⚠ {ver} 违禁词: {warnings}")
        else:
            print(f"  ✓ {ver} 零违禁词")
    
    return result


def regenerate_copy(title, desc, version):
    """重新生成指定版本的文案"""
    print(f"\n  重新生成 {version}...")
    if version == 'v1':
        text = regenerate_v1(desc)
    elif version == 'v2':
        text = regenerate_v2(title, desc)
    elif version == 'v3':
        text = regenerate_v3(title, desc)
    else:
        return None
    
    banned = filter_banned(text)
    print(f"  {version} 完成 ({len(text)}字) 违禁词: {banned if banned else '无'}")
    return {"text": text, "banned": banned}


# ============================================================
# 模块5：百度识图搜补充图 + 水印过滤
# ============================================================
async def search_extra_images(product_image, output_dir, max_images=15):
    """用百度识图找同类商品图，下载后去重

    实测：单次约 10 秒（搜索 9 秒 + 下载 1 秒），每次能拿到 20 张左右，
    尺寸在 500-670px 之间（百度只给缩略图，改 CDN 参数无效）。

    没有做水印过滤——每张都要调一次视觉模型，30 张就是半分钟以上，
    而且准确率一般。让用户自己挑更实际。
    """
    try:
        import image_search
    except ImportError:
        print("  ⚠ 搜图模块缺失（image_search.py），跳过补充图")
        return [], ""

    print(f"\n{'='*60}")
    print(f"补充图：百度识图搜同类商品（目标 {max_images} 张）")
    print(f"{'='*60}")

    # 多搜一倍，留出去重的余量
    urls, keyword = await image_search.search_by_image(product_image, max_images=max_images * 2)
    if not urls:
        print("  未搜到相似图片，跳过")
        return [], keyword

    print(f"  识别结果: {keyword or '(未识别)'}，拿到 {len(urls)} 条")

    search_dir = os.path.join(output_dir, "_raw_search")
    downloaded = await image_search.download_images(urls, search_dir)
    print(f"  下载成功 {len(downloaded)} 张")

    clean = image_search.dedupe_by_size(downloaded)
    print(f"  去重后 {len(clean)} 张")

    # 补充图放 search/ 子目录，和 get_images(..., 'search') 保持一致
    search_dir = os.path.join(output_dir, "search")
    os.makedirs(search_dir, exist_ok=True)
    for old_f in os.listdir(search_dir):
        try:
            os.remove(os.path.join(search_dir, old_f))
        except Exception:
            pass

    final_paths = []
    for i, path in enumerate(clean[:max_images]):
        dst = os.path.join(search_dir, "search_%02d.jpg" % (i + 1))
        try:
            shutil.copy2(path, dst)
            final_paths.append(dst)
        except Exception:
            pass

    if os.path.exists(search_dir):
        shutil.rmtree(search_dir, ignore_errors=True)

    print(f"  补充图片: {len(final_paths)} 张")
    return final_paths, keyword


async def collect_extra_images(product_image, keyword, output_dir, max_per_source=15,
                                sources=None, max_map=None):
    """多源聚合补充图（独立功能，可以单独触发，不依赖主流程）

    来源（用户在前端勾选，默认全开）：
      1. baidu_image   百度识图（以图搜图）—— 最准，能识别出商品名
      2. baidu_keyword 百度图片（关键词搜图）—— 量大，偶尔能拿到 800px
      3. jd            京东买家评价图 —— 需要登录一次，800x800 实拍图

    sources: 要启用的来源列表，None 表示全部
    max_map: 每个源的数量上限，如 {'baidu_image': 10, 'jd': 5}
    max_per_source: 没在 max_map 里指定的源用这个兜底

    某个源失败不影响其他源，返回里带上每个源的状态和原因。

    返回 {success, sources, total, summary, output_dir, enabled}
    """
    try:
        import image_search
    except ImportError:
        return {'success': False, 'error': '搜图模块缺失（image_search.py）'}

    print(f"\n{'='*60}")
    print("补充图：多源聚合")
    print(f"{'='*60}")

    enabled = [x for x in (image_search.SOURCE_ORDER if sources is None else sources)
               if x in image_search.SOURCE_ORDER]
    if not enabled:
        return {'success': False, 'error': '没有选中任何来源，至少勾选一个'}

    sources = await image_search.collect_all_sources(
        product_image, keyword=keyword or '', max_per_source=max_per_source,
        sources=enabled, max_map=max_map)

    # 逐个源下载（只下状态为 ok 的）
    os.makedirs(output_dir, exist_ok=True)
    seen_sizes = set()      # 跨源去重
    final_paths = []
    src_summary = []

    for r in sources:
        if r['status'] != 'ok' or not r['images']:
            src_summary.append(r)
            continue

        tmp_dir = os.path.join(output_dir, '_raw_' + r['source'])
        paths = await image_search.download_images(r['images'], tmp_dir)
        clean = image_search.dedupe_by_size(paths)

        kept = []
        for pth in clean:
            try:
                size = os.path.getsize(pth)
            except Exception:
                continue
            if size in seen_sizes:
                continue
            seen_sizes.add(size)
            kept.append(pth)

        r['count'] = len(kept)
        r['downloaded'] = kept
        src_summary.append(r)
        print(f"  {r['name']}: 抓到 {len(r['images'])} 条，下载去重后 {len(kept)} 张")

    # 补充图统一放 search/ 子目录：get_images(output_dir, 'search') 读的是这里，
    # 之前存在商品目录根下，前端读不到，列表一直是空的
    search_dir = os.path.join(output_dir, 'search')
    os.makedirs(search_dir, exist_ok=True)
    for old_f in os.listdir(search_dir):
        try:
            os.remove(os.path.join(search_dir, old_f))
        except Exception:
            pass

    # 按源的展示顺序统一编号
    idx = 1
    for r in src_summary:
        for pth in r.get('downloaded', []):
            dst = os.path.join(search_dir, 'search_%02d.jpg' % idx)
            try:
                shutil.copy2(pth, dst)
                final_paths.append(dst)
                idx += 1
            except Exception:
                pass

    # 清理临时下载目录
    for r in src_summary:
        tmp = os.path.join(output_dir, '_raw_' + r['source'])
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)

    # 去掉内部字段再返回（downloaded 是本地路径，不需要给界面）
    clean_sources = []
    for r in src_summary:
        item = {k: v for k, v in r.items() if k != 'downloaded'}
        clean_sources.append(item)

    summary = image_search.summarize_sources(clean_sources)
    print(f"  汇总: {summary}")
    print(f"  共保存 {len(final_paths)} 张到 {output_dir}")

    return {
        'success': True,
        'sources': clean_sources,
        'total': len(final_paths),
        'summary': summary,
        'output_dir': output_dir,
        'enabled': enabled,
    }


def save_copies(copies, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    
    with open(os.path.join(output_dir, "V1_词典替换.txt"), "w", encoding="utf-8") as f:
        f.write(f"标题：{copies['title']}\n\n{copies['v1']}")
    
    with open(os.path.join(output_dir, "V2_AI微调.txt"), "w", encoding="utf-8") as f:
        f.write(f"标题：{copies['title']}\n\n{copies['v2']}")
    
    with open(os.path.join(output_dir, "V3_AI重写.txt"), "w", encoding="utf-8") as f:
        f.write(f"标题：{copies['title']}\n\n{copies['v3']}")
    
    with open(os.path.join(output_dir, "原文.txt"), "w", encoding="utf-8") as f:
        f.write(f"标题：{copies['title']}\n\n{copies['original']}")
    
    with open(os.path.join(output_dir, "copies.json"), "w", encoding="utf-8") as f:
        json.dump(copies, f, ensure_ascii=False, indent=2)
    
    print(f"  文案已保存: V1/V2/V3 + 原文 + JSON")


COPY_FILENAMES = {"v1": "V1_词典替换.txt", "v2": "V2_AI微调.txt", "v3": "V3_AI重写.txt"}
COPY_HISTORY_KEEP = 10


def _backup_copy(output_dir, version, src_path):
    """覆盖前把当前版本存进 history/，每个版本最多留 10 个

    重新生成文案会直接覆盖文件，用户点了几次刷新后想找回上一版就没了。
    这里在覆盖前先留一份，文件名带时间戳。
    """
    hist = os.path.join(output_dir, "history")
    os.makedirs(hist, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(hist, "%s_%s.txt" % (version, stamp))
    # 同一秒内多次覆盖会重名，加一个序号
    seq = 1
    while os.path.exists(dst):
        dst = os.path.join(hist, "%s_%s_%d.txt" % (version, stamp, seq))
        seq += 1
    try:
        shutil.copy2(src_path, dst)
    except Exception as e:
        print(f"  备份文案失败（不影响主流程）: {e}")
        return

    # 只保留最近 N 个
    siblings = sorted(f for f in os.listdir(hist) if f.startswith(version + "_"))
    for old in siblings[:-COPY_HISTORY_KEEP]:
        try:
            os.remove(os.path.join(hist, old))
        except Exception:
            pass


def save_single_copy(title, text, version, output_dir):
    """保存单个版本文案（覆盖前自动备份旧版本）"""
    os.makedirs(output_dir, exist_ok=True)
    fname = COPY_FILENAMES[version]
    target = os.path.join(output_dir, fname)
    if os.path.exists(target):
        _backup_copy(output_dir, version, target)
    with open(target, "w", encoding="utf-8") as f:
        f.write(f"标题：{title}\n\n{text}")


def list_copy_history(output_dir, version):
    """列出某版本文案的历史备份，最新的在前"""
    hist = os.path.join(output_dir, "history")
    if not os.path.isdir(hist) or version not in COPY_FILENAMES:
        return []

    items = []
    for fname in sorted(os.listdir(hist), reverse=True):
        if not fname.startswith(version + "_"):
            continue
        path = os.path.join(hist, fname)
        try:
            raw = open(path, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        m = re.match(r"标题：(.*?)\n\n(.*)", raw, re.S)
        title = m.group(1) if m else ""
        body = m.group(2) if m else raw
        # 文件名形如 v1_20261030_151230.txt 或 v1_20261030_151230_2.txt
        stamp = fname[len(version) + 1:-4]
        items.append({
            "filename": fname,
            "time": stamp,
            "title": title,
            "text": body,
            "length": len(body),
        })
    return items


def restore_copy_history(output_dir, version, filename):
    """把某个历史版本恢复成当前版本（恢复前会把当前版本也备份一次）"""
    # 防目录穿越：先校验文件名，再拼路径。
    # 顺序不能反——先 isfile 的话，带 ../ 的名字会先被解析成真实路径
    if not filename or os.path.sep in filename or "/" in filename or ".." in filename:
        return {"success": False, "error": "非法文件名"}

    hist = os.path.join(output_dir, "history")
    src = os.path.join(hist, filename)
    if not os.path.isfile(src):
        return {"success": False, "error": "历史文件不存在"}

    try:
        raw = open(src, "r", encoding="utf-8", errors="replace").read()
    except Exception as e:
        return {"success": False, "error": str(e)}

    m = re.match(r"标题：(.*?)\n\n(.*)", raw, re.S)
    title = m.group(1) if m else ""
    body = m.group(2) if m else raw

    target = os.path.join(output_dir, COPY_FILENAMES[version])
    if os.path.exists(target):
        _backup_copy(output_dir, version, target)

    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(raw)
    except Exception as e:
        return {"success": False, "error": str(e)}

    return {"success": True, "title": title, "text": body, "length": len(body)}


def delete_copy_history(output_dir, version, filename):
    """删除某条历史备份"""
    if not filename or os.path.sep in filename or "/" in filename or ".." in filename:
        return {"success": False, "error": "非法文件名"}
    path = os.path.join(output_dir, "history", filename)
    if not os.path.isfile(path):
        return {"success": False, "error": "历史文件不存在"}
    try:
        os.remove(path)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# 全局文案线程引用（供GUI轮询）
_copy_thread = None
_copy_result = {}

# 文案是后台异步生成的（不阻塞主流程）。批量队列会连续发起多条任务，
# 若不限制并发，10 条下来就是 10 个线程同时打同一个模型接口，
# 免费额度极易被限流，反而让文案大面积失败。
# 这里限死同时最多 2 条在生成，其余排队等待。
_COPY_SEMAPHORE = threading.Semaphore(2)


async def _run_impl(url, search_max, stage, wait_copies=False):
    """一键全流程（实现体，由 run 包装器负责异常兜底）
    stage: 可变字典，用于向包装器汇报当前所处阶段
    """
    start_time = time.time()
    timings = {}
    
    print("=" * 60)
    print("闲鱼辅助工具 - 一键全流程")
    print(f"输入链接: {url}")
    print("=" * 60)
    
    # 输出目录按 product_id 隔离，不再在任务开始时清空整个 output。
    # 原实现一进来就 rmtree(output/)，批量处理时每条任务会互相删除结果。
    # 现在改为解析出 product_id 后只覆盖自己那一个目录（见下方）。
    output_parent = os.path.join(OUTPUT_ROOT, "output")
    os.makedirs(output_parent, exist_ok=True)
    
    stage['name'] = '模块1_解析'
    # === 模块1：解析链接 ===
    print(f"\n{'='*60}")
    print("模块1：解析闲鱼链接")
    print(f"{'='*60}")
    
    t0 = time.time()
    parsed = await parse_xianyu(url, debug=False)
    timings['模块1_解析'] = round(time.time() - t0, 1)
    
    if not parsed["success"]:
        print(f"  ✗ 解析失败: {parsed.get('error', '未知错误')}")
        return None
    
    print(f"  ✓ 商品ID: {parsed['item_id']}")
    print(f"  ✓ 标题: {parsed['title']}")
    print(f"  ✓ 价格: {parsed['price']}")
    print(f"  ✓ 卖家: {parsed['seller']}")
    print(f"  ✓ 文案: {len(parsed['desc'])}字")
    print(f"  ✓ 图片: {len(parsed['images'])}张")
    
    product_id = parsed["item_id"] or "unknown"
    output_root = os.path.join(OUTPUT_ROOT, "output", product_id)
    # 同一条链接重跑时清掉自己的旧结果，不影响同批次的其他商品
    if os.path.exists(output_root):
        shutil.rmtree(output_root, ignore_errors=True)
    os.makedirs(output_root, exist_ok=True)
    
    with open(os.path.join(output_root, "parsed.json"), "w", encoding="utf-8") as f:
        parsed_save = {k: v for k, v in parsed.items() if k != "captured_images"}
        json.dump(parsed_save, f, ensure_ascii=False, indent=2)
    
    # === 模块2：下载图片 + 模块3b文案（并行启动） ===
    # 优化：解析完拿到标题+文案后，立刻在后台线程启动V1/V2/V3生成
    # 同时主流程继续下载图片+去水印，最后等AI结果回来
    from concurrent.futures import ThreadPoolExecutor
    
    # 先启动文案生成（后台线程）
    print(f"\n{'='*60}")
    print("模块3b：AI文案改写（后台启动，与图片下载/去水印并行）")
    print(f"{'='*60}")
    
    # 改用独立线程
    import threading
    
    copy_result = {}
    def _run_copywriting():
        _t0 = time.time()
        # 限制并发：超出 2 条的文案任务在此排队
        _COPY_SEMAPHORE.acquire()
        try:
            data = generate_copywriting(parsed["title"], parsed["desc"])
            copy_result['data'] = data
            # 自动保存到文件
            copies_dir = os.path.join(output_root, "copies")
            save_copies(data, copies_dir)
            # 同时更新 result.json 中的 copies 字段（持久化）
            # 注意：主线程要等图片下载 + 去水印完成后才写 result.json，
            # 而文案往往先完成。原实现只读一次，文件不存在就永久跳过，
            # 导致 result.json 里的 copies 永远是空的。这里等待文件出现后再补写。
            try:
                result_json_path = os.path.join(output_root, "result.json")
                for _ in range(120):
                    if os.path.exists(result_json_path):
                        break
                    time.sleep(1)
                if os.path.exists(result_json_path):
                    with open(result_json_path, "r", encoding="utf-8") as f:
                        result_data = json.load(f)
                    result_data["copies"] = data
                    with open(result_json_path, "w", encoding="utf-8") as f:
                        json.dump(result_data, f, ensure_ascii=False, indent=2)
                    print(f"  ✅ result.json 已写入文案")
                else:
                    print(f"  ⚠ result.json 未生成，文案仅保存在 copies/ 目录")
            except Exception as e:
                print(f"  更新 result.json 失败: {e}")
            print(f"  ✅ 文案生成完成并已保存（{round(time.time()-_t0, 1)}秒）")
        except Exception as e:
            copy_result['error'] = str(e)
            print(f"  ✗ 文案生成失败: {e}")
        finally:
            copy_result['elapsed'] = round(time.time() - _t0, 1)
            _COPY_SEMAPHORE.release()
    copy_thread = threading.Thread(target=_run_copywriting, daemon=True)
    copy_thread.start()
    print(f"  ✅ V1/V2/V3后台生成中...")
    
    # 同时执行模块2：下载图片
    t0 = time.time()
    original_dir = os.path.join(output_root, "original")
    stage['name'] = '模块2_下载图片'
    original_images = await download_product_images(
        parsed["images"], original_dir, 
        captured_images=parsed.get("captured_images")
    )
    timings['模块2_下载图片'] = round(time.time() - t0, 1)
    
    if not original_images:
        print("  ✗ 图片下载失败，无法继续")
        return None
    
    # === 模块3a：去水印 ===
    t0 = time.time()
    clean_dir = os.path.join(output_root, "clean")
    stage['name'] = '模块3a_去水印'
    clean_images = remove_watermarks(original_images, clean_dir)
    timings['模块3a_去水印'] = round(time.time() - t0, 1)
    
    # === 模块3b：文案改为异步，不等待，先返回结果 ===
    # 文案线程仍在后台跑，跑完自动写入文件
    # 前端通过 check_copywriting_status() 轮询获取
    global _copy_thread, _copy_result
    _copy_thread = copy_thread
    _copy_result = copy_result
    _copy_result['output_root'] = output_root
    copy_elapsed = 0
    timings['模块3b_文案'] = 0  # 0表示仍在生成中
    print(f"  ✅ 文案后台生成中（不阻塞主流程）...")
    
    stage['name'] = '模块5_补充图'
    # === 模块5：百度识图搜补充图（改为独立触发，不在主流程跑） ===
    # 补充图太慢，改为用户单独点击触发
    timings['模块5_补充图'] = 0
    
    # 队列模式（wait_copies=True）下必须等文案跑完再返回。
    # 否则批量连续处理时，每条都会留下一个仍在调 AI 的后台线程，
    # 10 条下来就是 10 个并发请求同时打同一个模型接口，极易触发限流，
    # 结果是大面积文案生成失败。
    if wait_copies and copy_thread is not None:
        print(f"  队列模式：等待文案生成完成（最多 120 秒）...")
        copy_thread.join(timeout=120)
        if copy_thread.is_alive():
            print(f"  ⚠ 文案生成超时，本条结果不含文案")
            timings['模块3b_文案'] = '超时'
        else:
            ce = copy_result.get('elapsed', 0)
            timings['模块3b_文案'] = ce
            if copy_result.get('error'):
                print(f"  ⚠ 文案生成失败: {copy_result['error']}")
            else:
                print(f"  ✓ 文案已生成（{ce}秒）")

    # === 汇总 ===
    elapsed = time.time() - start_time
    
    stage['name'] = '模块6_保存结果'
    result = {
        "product_id": product_id,
        "title": parsed["title"],
        "price": parsed["price"],
        "seller": parsed["seller"],
        "original_desc": parsed["desc"],
        "original_images": original_images,
        "clean_images": clean_images,
        # 文案若已生成则直接带上，否则留空由文案线程稍后补写
        "copies": (copy_result.get('data') or {"v1": "", "v2": "", "v3": ""}),
        "extra_images": [],
        "search_keyword": "",
        "video_url": parsed.get("video_url", ""),
        "output_dir": output_root,
        "elapsed_seconds": round(elapsed, 1),
        "timings": timings,
        "search_max": search_max,
    }
    
    with open(os.path.join(output_root, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"✅ 全流程完成！耗时 {elapsed:.1f}秒")
    print(f"{'='*60}")
    print(f"  各模块耗时:")
    for name, t in timings.items():
        print(f"    {name}: {t}秒")
    print(f"  商品: {parsed['title']}")
    print(f"  价格: {parsed['price']}")
    print(f"  原始图片: {len(original_images)}张 → {original_dir}")
    print(f"  去水印图: {len(clean_images)}张 → {clean_dir}")
    # 文案异步生成，不在此处统计
    print(f"  文案版本: 后台生成中...")
    print(f"  补充图片: {len(result['extra_images'])}张")
    print(f"{'='*60}")
    
    return result


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    
    if len(sys.argv) < 2:
        print("用法: python xianyu_tool.py <闲鱼商品链接>")
        sys.exit(0)
    
    url = sys.argv[1]
    try:
        result = asyncio.run(run(url))
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n❌ 运行出错: {e}")
        sys.exit(1)

async def run(url, search_max=15, wait_copies=False):
    """主流程入口：统一捕获异常并标注失败阶段。

    wait_copies=True 时会等文案生成完毕再返回（批量队列用），
    默认 False 保持界面异步展示文案的行为。

    原先异常只在 GUI 层被转成 str(e)，用户看到的是裸异常文本，
    分不清是解析失败还是下载失败，也没有堆栈可查。
    这里用 stage 跟踪当前阶段，出错时把阶段、异常与完整堆栈
    一并打印（经 app_logger 的 tee 自动落盘）。
    """
    stage = {'name': '初始化'}
    try:
        return await _run_impl(url, search_max, stage, wait_copies)
    except Exception as exc:
        import traceback as _tb
        print('\n[异常] 阶段「%s」失败：%s' % (stage['name'], exc))
        print(_tb.format_exc())
        return {
            'success': False,
            'stage': stage['name'],
            'error': '阶段「%s」失败：%s' % (stage['name'], exc),
        }

