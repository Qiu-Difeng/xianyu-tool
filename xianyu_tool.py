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
# 启动时清空旧数据
if os.path.exists(OUTPUT_ROOT):
    import shutil
    shutil.rmtree(OUTPUT_ROOT, ignore_errors=True)
os.makedirs(OUTPUT_ROOT, exist_ok=True)
PYTHON = r"C:\Users\86175\AppData\Local\Programs\Python\Python38\python.exe"

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
                    except:
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
                            except:
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
    
    print(f"  快速预检：先检测第1张图是否有水印...")
    need_process = []
    no_watermark = []
    
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    # 快速预检：先检测第1张图
    first_check = _check_watermark_with_glm4v(image_paths[0])
    
    if first_check is False:
        # 第1张没水印，大概率都没有，直接全跳过
        print(f"    {os.path.basename(image_paths[0])}: 无水印，跳过全部图片检测")
        for img_path in image_paths:
            img_name = os.path.basename(img_path)
            dst = os.path.join(output_dir, img_name)
            shutil.copy2(img_path, dst)
            clean_images.append(dst)
        print(f"  ✅ 全部 {len(image_paths)} 张无水印，直接复制（跳过检测）")
        return clean_images
    
    # 第1张有水印，检测剩余图片（并行）
    if first_check is True:
        print(f"    {os.path.basename(image_paths[0])}: 有水印")
        need_process.append(image_paths[0])
    else:
        print(f"    {os.path.basename(image_paths[0])}: 检测失败")
        need_process.append(image_paths[0])
    
    # 检测剩余图片（如果只有1张就不用检测了）
    if len(image_paths) > 1:
        def _check_one(img_path):
            img_name = os.path.basename(img_path)
            has_wm = _check_watermark_with_glm4v(img_path)
            return (img_path, img_name, has_wm)
        
        results_map = {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(_check_one, img): img for img in image_paths[1:]}
            for future in as_completed(futures):
                img_path, img_name, has_wm = future.result()
                results_map[img_path] = (img_name, has_wm)
        
        for img_path in image_paths[1:]:
            img_name, has_wm = results_map[img_path]
            if has_wm is True:
                print(f"    {img_name}: 有水印，需处理")
                need_process.append(img_path)
            elif has_wm is False:
                print(f"    {img_name}: 无水印，跳过")
                no_watermark.append(img_path)
            else:
                print(f"    {img_name}: 检测失败，保守处理")
                need_process.append(img_path)
    
    for img_path in no_watermark:
        img_name = os.path.basename(img_path)
        dst = os.path.join(output_dir, img_name)
        shutil.copy2(img_path, dst)
        clean_images.append(dst)
    
    if need_process:
        print(f"\n  {len(need_process)}张需要去水印，启动LaMa修复...")
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
                except Exception as e:
                    shutil.copy2(img_path, out_path)
                    return (img_path, out_path, False)
            
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(_process_one, img): img for img in need_process}
                for future in as_completed(futures):
                    img_path = futures[future]
                    img_name = os.path.basename(img_path)
                    orig_path, result_path, success = future.result()
                    clean_images.append(result_path)
                    print(f"    {'✓' if success else '⚠(用原图)'} {img_name}")
        except ImportError:
            print(f"  LaMa模块未导入，有水印图片暂用原图")
            for img_path in need_process:
                img_name = os.path.basename(img_path)
                dst = os.path.join(output_dir, img_name)
                shutil.copy2(img_path, dst)
                clean_images.append(dst)
    else:
        print(f"  所有图片均无水印，无需处理")
    
    print(f"  去水印完成: {len(clean_images)}张")
    return clean_images


# ============================================================
# 模块3b：AI文案改写
# ============================================================
from module3_copywriter import generate_versions, regenerate_v1, regenerate_v2, regenerate_v3, filter_banned, post_process

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
from module5_imgsearch_final import search_by_image, download_images, filter_watermarked_images

async def search_extra_images(product_image, output_dir, max_images=15):
    print(f"\n{'='*60}")
    print(f"模块5：百度识图搜补充图 + 水印过滤 + 同款检测（最多{max_images}张）")
    print(f"{'='*60}")
    
    # 搜索更多图片（多搜一些，过滤后可能不够）
    search_count = max_images * 3
    urls, keyword = await search_by_image(product_image, max_images=search_count)
    
    if not urls:
        print("  未搜到相似图片，跳过")
        return [], ""
    
    search_dir = os.path.join(output_dir, "_raw_search")
    downloaded = await download_images(urls, search_dir)
    
    # 传入参考图做同款检测
    clean, watermarked = filter_watermarked_images(downloaded, reference_image=product_image)
    
    os.makedirs(output_dir, exist_ok=True)
    # 清理旧图片
    for old_f in os.listdir(output_dir):
        if old_f.startswith("search_"):
            os.remove(os.path.join(output_dir, old_f))
    
    final_paths = []
    for i, path in enumerate(clean[:max_images]):
        ext = os.path.splitext(path)[1]
        dst = os.path.join(output_dir, f"search_{i+1:02d}{ext}")
        shutil.copy2(path, dst)
        final_paths.append(dst)
    
    if os.path.exists(search_dir):
        shutil.rmtree(search_dir)
    
    print(f"  补充图片: {len(final_paths)}张干净同款（排除{len(watermarked)}张）")
    return final_paths, keyword


# ============================================================
# 保存文案到文件
# ============================================================
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


def save_single_copy(title, text, version, output_dir):
    """保存单个版本文案"""
    os.makedirs(output_dir, exist_ok=True)
    fname = {"v1": "V1_词典替换.txt", "v2": "V2_AI微调.txt", "v3": "V3_AI重写.txt"}[version]
    with open(os.path.join(output_dir, fname), "w", encoding="utf-8") as f:
        f.write(f"标题：{title}\n\n{text}")


# ============================================================
# 打开文件夹
# ============================================================
def open_folder(path):
    """在资源管理器中打开文件夹"""
    if sys.platform == 'win32':
        os.startfile(path)
    elif sys.platform == 'darwin':
        os.system(f'open "{path}"')
    else:
        os.system(f'xdg-open "{path}"')


# ============================================================
# 主流程
# ============================================================
async def run(url, search_max=15):
    """一键全流程
    search_max: 补充图搜索数量上限
    """
    start_time = time.time()
    timings = {}
    
    print("=" * 60)
    print("闲鱼辅助工具 - 一键全流程")
    print(f"输入链接: {url}")
    print("=" * 60)
    
    # 清空上一次的输出，只保留最新一次
    if os.path.exists(OUTPUT_ROOT):
        shutil.rmtree(OUTPUT_ROOT, ignore_errors=True)
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    
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
        copy_result['data'] = generate_copywriting(parsed["title"], parsed["desc"])
        copy_result['elapsed'] = round(time.time() - _t0, 1)
    copy_thread = threading.Thread(target=_run_copywriting, daemon=True)
    copy_thread.start()
    print(f"  ✅ V1/V2/V3后台生成中...")
    
    # 同时执行模块2：下载图片
    t0 = time.time()
    original_dir = os.path.join(output_root, "original")
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
    clean_images = remove_watermarks(original_images, clean_dir)
    timings['模块3a_去水印'] = round(time.time() - t0, 1)
    
    # === 模块3b：等待文案生成完成 ===
    copy_thread.join()  # 等待文案生成线程完成
    copy_elapsed = copy_result.get('elapsed', 0)
    if 'data' in copy_result:
        copies = copy_result['data']
        copies_dir = os.path.join(output_root, "copies")
        save_copies(copies, copies_dir)
    else:
        print("  ✗ 文案生成失败")
        copies = None
    timings['模块3b_文案'] = copy_elapsed
    print(f"  文案生成完成（实际耗时: {copy_elapsed}s，与去水印并行）")
    
    # === 模块5：百度识图搜补充图（改为独立触发，不在主流程跑） ===
    # 补充图太慢，改为用户单独点击触发
    timings['模块5_补充图'] = 0
    
    # === 汇总 ===
    elapsed = time.time() - start_time
    
    result = {
        "product_id": product_id,
        "title": parsed["title"],
        "price": parsed["price"],
        "seller": parsed["seller"],
        "original_desc": parsed["desc"],
        "original_images": original_images,
        "clean_images": clean_images,
        "copies": {
            "v1": copies["v1"],
            "v2": copies["v2"],
            "v3": copies["v3"],
        },
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
    print(f"  文案版本: V1({len(copies['v1'])}字) V2({len(copies['v2'])}字) V3({len(copies['v3'])}字)")
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
