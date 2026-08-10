# -*- coding: utf-8 -*-
"""模块1：闲鱼分享链接解析器（v2 - 扫码登录 + Cookie持久化）

技术方案：
- 使用独立的Chrome用户数据目录（持久化Cookie/登录态）
- 首次运行：弹出Chrome窗口，用户扫码登录闲鱼
- 后续运行：Cookie已保存，直接连接使用
- Cookie过期时：再次弹窗让用户扫码
- Playwright CDP连接本地Chrome（--remote-debugging-port=9222）
"""
import asyncio
import json
import re
import os
import sys
# platform/subprocess 已移除（旧CDP函数已删除）
import time
import random
from urllib.parse import urlparse, parse_qs
from playwright.async_api import async_playwright

# ============================================================
# 路径配置
# ============================================================
if getattr(sys, 'frozen', False):
    WORKSPACE = sys._MEIPASS
else:
    WORKSPACE = os.path.dirname(os.path.abspath(__file__))

# 独立的Chrome用户数据目录（和日常浏览器隔离，避免冲突）
CHROME_USER_DATA = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'XianyuTool_ChromeData')
CHROME_DEBUG_PORT = 9222

# 登录态标记文件
LOGIN_FLAG = os.path.join(CHROME_USER_DATA, 'logged_in.flag')


# ============================================================
# 浏览器管理（旧CDP函数已删除，改用Playwright自带Chromium）
# ============================================================

async def launch_chrome_debug(port=9222, headless=False):
    """
    启动Playwright自带Chromium（独立数据目录，不影响用户日常浏览器）
    headless=True时真正无头模式（不弹窗）
    返回: (playwright_instance, browser, context) 或 (None, None, None)
    """
    from playwright.async_api import async_playwright
    
    os.makedirs(CHROME_USER_DATA, exist_ok=True)
    
    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=CHROME_USER_DATA,
            headless=headless,
            args=[
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-features=TranslateUI',
                '--window-size=1280,800',
            ],
            viewport={'width': 1280, 'height': 800},
        )
        if headless:
            print(f"  ✓ 已启动Chromium（后台无头模式）")
        else:
            print(f"  ✓ 已启动Chromium（独立窗口，请扫码登录）")
        return pw, browser, True
    except Exception as e:
        print(f"  ✗ Chromium启动失败: {e}")
        return None, None, False


def is_logged_in():
    """检查是否已有登录标记"""
    return os.path.exists(LOGIN_FLAG)


def mark_logged_in():
    """写入登录标记"""
    try:
        with open(LOGIN_FLAG, 'w') as f:
            f.write(str(time.time()))
    except:
        pass


# ============================================================
# 链接预处理
# ============================================================
def normalize_url(raw_url):
    """标准化闲鱼链接，提取商品ID"""
    raw_url = raw_url.strip().replace('\u200b', '').replace('\ufeff', '')
    if raw_url.startswith(('¥', '€')):
        return None, None
    url_match = re.search(r'https?://[^\s\u4e00-\u9fff]+', raw_url)
    if not url_match:
        return None, None
    url = url_match.group(0).rstrip('…')
    item_id = None
    for pattern in [r'[?&]id=(\d+)', r'[?&]itemId=(\d+)', r'/item/(\d+)']:
        m = re.search(pattern, url)
        if m:
            item_id = m.group(1)
            break
    return item_id, url


def _fix_img_url(url):
    if not url:
        return ""
    if url.startswith('//'):
        url = 'https:' + url
    return url


# ============================================================
# 检测登录状态
# ============================================================
async def check_login_status(page):
    """在闲鱼页面上检测是否已登录"""
    try:
        # 检查Cookie：cookie2或_m_h5_tk存在说明有登录态
        cookies = await page.context.cookies()
        cookie_names = {c['name'] for c in cookies}
        if 'cookie2' in cookie_names or '_m_h5_tk' in cookie_names:
            return True
        
        body_text = await page.inner_text('body')
        # 未登录的特征（闲鱼PC版未登录时显示这些）
        login_required = any(kw in body_text[:500] for kw in [
            '请登录', '扫码登录', '登录后查看', '手机扫码登录',
            '网络不见了', '被挤爆啦', '请使用手机扫码'
        ])
        if login_required:
            return False
        return None  # 不确定
    except:
        return None


async def wait_for_login(page, timeout=180):
    """
    等待用户扫码登录
    直接导航到淘宝登录页，等待登录完成
    """
    print(f"\n  ╔══════════════════════════════════════════════╗")
    print(f"  ║  🔑 请在Chrome窗口中扫码登录淘宝/闲鱼        ║")
    print(f"  ║  登录成功后工具会自动继续，无需其他操作      ║")
    print(f"  ╚══════════════════════════════════════════════╝\n")

    # 直接导航到闲鱼首页（未登录会自动跳转到淘宝登录）
    try:
        await page.goto("https://www.goofish.com/", wait_until="domcontentloaded", timeout=20000)
    except:
        pass
    await asyncio.sleep(2)
    
    # 检查是否已经跳到了登录页
    current_url = page.url
    print(f"  当前页面: {current_url[:60]}")
    
    # 如果不在登录页，主动跳过去
    if 'login' not in current_url:
        try:
            await page.goto("https://login.taobao.com/member/login.jhtml?style=mini&from=goofish", 
                          wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
        except:
            pass

    for i in range(timeout):
        await asyncio.sleep(1)
        if i % 5 == 0 and i > 0:
            # 每5秒检测一次Cookie和页面
            try:
                status = await check_login_status(page)
                if status is True:
                    print(f"  ✅ 检测到登录成功！继续处理...")
                    mark_logged_in()
                    return True
                
                # 如果页面URL变化了（可能登录后跳转）
                current = page.url
                if 'login' not in current and 'taobao' not in current and i > 10:
                    # 可能已经跳转到闲鱼首页
                    await asyncio.sleep(2)
                    status = await check_login_status(page)
                    if status is True:
                        print(f"  ✅ 登录成功（页面跳转检测）！")
                        mark_logged_in()
                        return True
                    
                if i % 30 == 0:
                    print(f"  ⏳ 仍在等待扫码登录...（已等{i}秒）")
            except:
                pass
    print(f"  ⚠ 等待超时（{timeout}秒），请确保已登录闲鱼")
    return False


# ============================================================
# 核心解析函数
# ============================================================
async def parse_xianyu(url, debug=False):
    """
    解析闲鱼商品链接（v2 扫码登录 + Cookie持久化）
    
    首次运行：弹出Chrome → 用户扫码登录 → 自动继续
    后续运行：Cookie已保存 → 直接连接 → 无需再登录
    
    返回: {success, title, desc, price, images, image_urls, item_id, seller, error, captured_images}
    """
    result = {
        "success": False,
        "title": "", "desc": "", "price": "",
        "images": [], "image_urls": [],
        "item_id": "", "seller": "",
        "error": "", "captured_images": {},
        "video_url": "",
    }

    # 预处理链接
    item_id, clean_url = normalize_url(url)
    if not clean_url:
        result["error"] = "无法识别链接格式，请提供完整的闲鱼商品链接"
        return result
    result["item_id"] = item_id or ""

    # 短链接重定向
    if 'tb.cn' in clean_url or 't.cn' in clean_url:
        print(f"  短链接，解析重定向中...")
        import httpx
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as c:
                r = await c.get(clean_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                })
                final_url = str(r.url)
                print(f"    重定向到: {final_url[:80]}...")
                mid = re.search(r'id=(\d+)', final_url)
                if mid:
                    result["item_id"] = mid.group(1)
                    clean_url = f"https://www.goofish.com/item?id={mid.group(1)}"
                else:
                    clean_url = final_url
        except Exception as e:
            print(f"    重定向失败: {e}")
    elif item_id:
        clean_url = f"https://www.goofish.com/item?id={item_id}"

    # 启动Playwright自带Chromium（独立数据目录）
    logged_in_before = is_logged_in()
    if logged_in_before:
        print(f"  📋 检测到登录记录，后台静默运行...")
    
    use_headless = logged_in_before
    pw, context, ok = await launch_chrome_debug(headless=use_headless)
    
    if not ok:
        result["error"] = "⚠️ 无法启动浏览器，请检查Playwright安装。"
        return result

    detail_api_body = None
    captured_images = {}

    async def on_response(response):
        nonlocal detail_api_body, captured_images
        resp_url = response.url
        # 拦截详情API
        if ('mtop' in resp_url and 'detail' in resp_url
                and 'recommend' not in resp_url and 'login' not in resp_url):
            try:
                body = await response.text()
                if body and len(body) > 5000:
                    if not detail_api_body or len(body) > len(detail_api_body):
                        detail_api_body = body
                        if debug:
                            print(f"  [API] {len(body)}B")
            except:
                pass
        # 拦截商品图片
        if ('alicdn.com' in resp_url
                and ('bao/uploaded' in resp_url or 'imgextra' in resp_url)
                and 'icon' not in resp_url.lower()
                and 'logo' not in resp_url.lower()
                and 'avatar' not in resp_url.lower()):
            try:
                body = await response.body()
                if body and len(body) > 3000:
                    m = re.search(r'(O1CN0\w+)', resp_url)
                    img_id = m.group(1) if m else resp_url
                    if img_id not in captured_images or len(body) > len(captured_images[img_id]):
                        captured_images[img_id] = body
            except:
                pass

    page = await context.new_page()
    page.on("response", on_response)

    # === 防封号：频率控制 ===
    try:
        from anti_detect import get_limiter, check_risk_indicators, human_like_scroll, random_mouse_move
        limiter = get_limiter()
        wait_sec, reason = limiter.check()
        if reason and '限额' in reason:
            result['error'] = reason
            return result
        await limiter.wait()
    except ImportError:
        pass

    # === 检测登录状态 ===
    # 优化：如果之前已登录过（标记文件存在），跳过首页检测，直接访问商品页
    # API有响应 = 登录有效；没有再走登录流程
    if is_logged_in():
        print(f"  ✅ 已登录过，直接解析商品页...")
        # 直接跳到访问商品页
        try:
            await page.goto(clean_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  页面加载超时: {e}")
        
        # 轮询等待API数据（最多15秒，每0.5秒检查）
        for _w in range(30):
            if detail_api_body:
                break
            await asyncio.sleep(0.5)
        
        # 如果拿到了数据，直接跳到解析
        if detail_api_body:
            # 防封号检查
            try:
                await human_like_scroll(page)
                await random_mouse_move(page)
            except:
                pass
            # 跳到解析
            goto_parse = True
        else:
            # 可能Cookie过期，走重新登录流程
            print(f"  ⚠ Cookie可能过期，尝试重新登录...")
            goto_parse = False
    else:
        goto_parse = False
    
    if not goto_parse:
        # 先访问闲鱼首页，等页面加载后检查Cookie
        print(f"  检测登录状态...")
        try:
            await page.goto("https://www.goofish.com/", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1)
        except:
            pass
    
    if not goto_parse:
        # 现在页面已加载，检查Cookie
        cookies = await context.cookies()
        cookie_names = {c['name'] for c in cookies}
        # 闲鱼登录态Cookie：cookie2或_m_h5_tk存在说明有登录态
        has_login = 'cookie2' in cookie_names or '_m_h5_tk' in cookie_names
    
    if not goto_parse:
        if has_login:
            print(f"  ✅ Cookie有效，后台静默解析中...")
            mark_logged_in()
        else:
            # 无头模式下Cookie失效，需要切换到有界面模式让用户扫码
            if use_headless:
                print(f"  🔑 Cookie已过期，需要重新扫码登录")
                await page.close()
                await context.close()
                await pw.stop()
                print(f"  切换到有界面模式，请扫码登录...")
                pw2, context2, ok2 = await launch_chrome_debug(headless=False)
                if not ok2:
                    result["error"] = "无法启动浏览器登录窗口"
                    return result
                page2 = await context2.new_page()
                page2.on("response", on_response)
                logged_in = await wait_for_login(page2, timeout=180)
                if not logged_in:
                    cookies2 = await context2.cookies()
                    cn2 = {c['name'] for c in cookies2}
                    if 'cookie2' in cn2 or '_m_h5_tk' in cn2:
                        logged_in = True
                if logged_in:
                    mark_logged_in()
                    print(f"  ✅ 登录成功，继续解析...")
                    try:
                        await page2.goto(clean_url, wait_until="domcontentloaded", timeout=30000)
                    except:
                        pass
                    # 轮询等待API数据到达（最多等30秒，每0.5秒检查一次）
                    for _w in range(60):
                        if detail_api_body:
                            break
                        await asyncio.sleep(0.5)
                    if not detail_api_body:
                        try:
                            await page2.wait_for_load_state("networkidle", timeout=10000)
                        except:
                            pass
                        await asyncio.sleep(2)
                    else:
                        result["error"] = "登录后仍未能获取商品数据"
                    await page2.close()
                    await context2.close()
                    await pw2.stop()
                else:
                    result["error"] = "登录超时。请重新运行工具并在弹出的窗口中完成扫码登录。"
                    await page2.close()
                    await context2.close()
                    await pw2.stop()
                # 如果拿到了数据，继续后续解析
                if not detail_api_body:
                    return result
            else:
                # 有界面模式，直接弹窗扫码
                print(f"  🔑 未检测到登录态，需要扫码登录")
                logged_in = await wait_for_login(page, timeout=180)
                if not logged_in:
                    cookies = await context.cookies()
                    cookie_names = {c['name'] for c in cookies}
                    has_login = 'cookie2' in cookie_names or '_m_h5_tk' in cookie_names
                    if has_login:
                        print(f"  ✅ 登录成功（Cookie检测）")
                        mark_logged_in()
                    else:
                        result["error"] = "登录超时。请在弹出的Chrome窗口中完成扫码登录后重试。"
                        await page.close()
                        return result

    if not goto_parse:
        # 访问商品页（goto_parse=True时已在上面访问过）
        print(f"\n  加载商品页: {clean_url}")
        try:
            await page.goto(clean_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  页面加载超时: {e}")

        # 防封号：人类行为模拟
        try:
            await human_like_scroll(page)
            await random_mouse_move(page)
        except:
            pass

        # 轮询等待API数据（最多等15秒，每0.5秒检查）
        for _w in range(30):
            if detail_api_body:
                break
            await asyncio.sleep(0.5)

    if not goto_parse:
        # 防封号：检查风控拦截
        try:
            body_text = await page.inner_text('body')
            risk_detected, risk_kw = check_risk_indicators(body_text[:1000])
            if risk_detected:
                print(f"  ⚠ 检测到风控拦截: {risk_kw}")
                result['error'] = f"闲鱼风控拦截（{risk_kw}），请稍后再试或更换网络环境"
                limiter.record()
                return result
        except:
            pass

        # 如果商品页返回错误，检查是否是登录过期
        if not detail_api_body:
            cookies = await context.cookies()
            cookie_names = {c['name'] for c in cookies}
            has_login = 'cookie2' in cookie_names or '_m_h5_tk' in cookie_names
            if not has_login:
                print(f"  🔑 Cookie已过期，需要重新登录")
                logged_in = await wait_for_login(page, timeout=180)
                if logged_in:
                    try:
                        await page.goto(clean_url, wait_until="domcontentloaded", timeout=30000)
                    except:
                        pass
                    # 轮询等待API数据
                    for _w in range(30):
                        if detail_api_body:
                            break
                        await asyncio.sleep(0.5)
                else:
                    result["error"] = "登录超时"
                    await page.close()
                    return result

    # 再轮询等一下（上面可能已拿到，这里快速确认）
    if not detail_api_body:
        for _w in range(10):
            if detail_api_body:
                break
            await asyncio.sleep(0.5)

    # === 解析API数据 ===
    if detail_api_body:
        json_str = detail_api_body
        m = re.match(r'^[\w\.]+\((.+)\)$', detail_api_body, re.DOTALL)
        if m:
            json_str = m.group(1)
        try:
            data = json.loads(json_str)
            ret = data.get("ret", [""])[0]
            if ret and "成功" not in ret and "SUCCESS" not in ret.upper():
                print(f"  API ret: {ret}")

            item_data = data.get("data", {}).get("itemDO", {})
            if not item_data and "data" in data:
                for k, v in data["data"].items():
                    if isinstance(v, dict) and "title" in v:
                        item_data = v
                        break

            if item_data:
                result["title"] = item_data.get("title", "")
                result["desc"] = item_data.get("desc", "")
                result["price"] = str(item_data.get("soldPrice", "") or item_data.get("price", "") or "")
                result["item_id"] = str(item_data.get("itemId", result["item_id"]))

                image_infos = item_data.get("imageInfos", [])
                result["image_urls"] = [
                    _fix_img_url(img.get("url", ""))
                    for img in image_infos if isinstance(img, dict) and img.get("url")
                ]
                if not result["image_urls"] and "images" in item_data:
                    result["image_urls"] = [_fix_img_url(u) for u in item_data["images"] if u]

                # 提取视频URL
                video_infos = item_data.get("videoInfos", [])
                if video_infos:
                    for v in video_infos:
                        if isinstance(v, dict):
                            vurl = v.get("url", "") or v.get("videoUrl", "")
                            if vurl:
                                result["video_url"] = vurl
                                break
                if not result["video_url"]:
                    result["video_url"] = item_data.get("videoUrl", "") or item_data.get("video", "")

                seller_data = data.get("data", {}).get("sellerDO", {})
                if seller_data:
                    result["seller"] = seller_data.get("desensitizationNick", "") or seller_data.get("nick", "")

                print(f"  [API] 标题={result['title'][:30]}, 价格={result['price']}, 图片={len(result['image_urls'])}张")
                if result["video_url"]:
                    print(f"  [API] 视频={result['video_url'][:60]}")
        except json.JSONDecodeError:
            pass

    # === DOM兜底取标题 ===
    if not result["title"]:
        for sel in ['h1', '[class*="title"]', '[class*="Title"]', 'meta[property="og:title"]']:
            el = await page.query_selector(sel)
            if el:
                text = (await el.get_attribute('content') if sel.startswith('meta')
                        else (await el.inner_text()).strip())
                if text and len(text) > 3 and "页面不存在" not in text:
                    result["title"] = text
                    break

    # === 匹配图片 ===
    if result["image_urls"]:
        for img_url in result["image_urls"]:
            m = re.search(r'(O1CN0\w+)', img_url)
            if m:
                img_id = m.group(1)
                if img_id in captured_images:
                    result["captured_images"][img_url] = captured_images[img_id]
        if debug:
            print(f"  [IMG] 拦截 {len(captured_images)}张, 匹配 {len(result['captured_images'])}张")
    elif captured_images:
        print(f"  [IMG] 未从API获取URL，用拦截的 {len(captured_images)} 张")
        result["image_urls"] = list(captured_images.keys())
        result["captured_images"] = captured_images

    result["images"] = result["image_urls"]

    # === 结果汇总 ===
    if result["title"] or result["image_urls"]:
        result["success"] = True
        print(f"\n  ✅ 解析成功！")
        print(f"  商品ID: {result['item_id']}")
        print(f"  标题: {result['title'][:40]}")
        print(f"  价格: {result['price']}")
        print(f"  卖家: {result['seller']}")
        print(f"  文案: {len(result['desc'])}字")
        print(f"  图片: {len(result['image_urls'])}张")
    else:
        result["error"] = "未能提取商品信息。可能原因：1) 未登录闲鱼 2) 商品已下架 3) 页面加载超时"

    await page.close()
    await context.close()
    await pw.stop()

    return result


# ============================================================
# 主函数（测试用）
# ============================================================
if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    
    if len(sys.argv) < 2:
        print("用法: python module1_parser.py <闲鱼链接>")
        sys.exit(1)

    result = asyncio.run(parse_xianyu(sys.argv[1], debug=True))
    if result["success"]:
        save_result = {k: v for k, v in result.items() if k != "captured_images"}
        with open("module1_result.json", "w", encoding="utf-8") as f:
            json.dump(save_result, f, ensure_ascii=False, indent=2)
        print("\n✓ 结果已保存到 module1_result.json")
    else:
        print(f"\n✗ 解析失败: {result['error']}")
