# 技术实现说明

各模块的实现方式、设计取舍、以及踩过的坑。普通用户不用看。

运行环境：Python 3.8 / Playwright / PyWebView(WebView2) / PyInstaller 打包。

## 整体架构

```
┌─────────────────────────────────────────────────┐
│                  GUI 层 (PyWebView)               │
│         gui_embed.html + Edge WebView2            │
├─────────────────────────────────────────────────┤
│               API 桥接层 (xianyu_gui.py)           │
│    run_tool / get_images / regenerate_copy ...    │
├─────────────────────────────────────────────────┤
│              主流程编排 (xianyu_tool.py)            │
│   解析 → 下载 → 去水印 ─┐                        │
│                        ├─ 并行 → 汇总             │
│              文案生成 ─┘                          │
├────────┬────────┬──────────┬────────┬───────────┤
│ 模块1  │ 模块2  │ 模块3a   │ 模块3b │  模块5    │
│ 链接   │ 图片   │ 去水印   │ 文案   │  补充图   │
│ 解析   │ 下载   │          │        │           │
├────────┴────────┴──────────┴────────┴───────────┤
│              防封号层 (anti_detect.py)             │
│    频率控制 · 人类行为模拟 · 风控检测               │
└─────────────────────────────────────────────────┘
```

## 模块1：链接解析（module1_parser.py）

**做什么**：输入闲鱼商品链接，提取标题、文案、价格、图片URL、视频URL。

**技术方案**：Playwright + 闲鱼API拦截

**为什么这样设计**：

闲鱼有严格的风控系统，未登录状态下所有API端点（`pc.detail`/`awesome.detail`/`item.web.detail`/`buyer.item.detail`）都会返回"被挤爆啦"（RGV587_ERROR）。所以不能用简单的HTTP请求直接调API。

方案演变过程：
1. ~~直接调API~~ → 风控拦截，未登录不可用
2. ~~移动端H5~~ → 同样需要登录态
3. ~~首页Cookie+签名~~ → 签名算法频繁变化
4. **Playwright + API拦截** → 浏览器有完整登录态，拦截网络响应拿结构化数据

**具体实现**：
- 用 `launch_persistent_context` 启动Playwright自带Chromium，数据目录隔离在 `%LOCALAPPDATA%\XianyuTool_ChromeData`，不碰用户日常浏览器
- 首次运行弹窗扫码登录，Cookie自动持久化，后续无头模式运行
- 通过 `page.on("response", on_response)` 拦截两类响应：
  - **详情API**：匹配URL含 `mtop` + `detail` + 非 `recommend`/`login`，响应体 > 5KB的JSON，提取 `itemDO` 结构化数据（标题/文案/价格/图片URL/视频URL）
  - **商品图片**：匹配URL含 `alicdn.com` + `bao/uploaded` 或 `imgextra`，排除icon/logo/avatar，响应体 > 3KB的二进制图片数据
- 短链接（`m.tb.cn`/`t.cn`）用httpx先跟随重定向拿到真实URL
- 登录态优化：标记文件 `logged_in.flag` 存在时跳过首页检测，直接访问商品页；API有响应=登录有效，没响应才走重新登录流程（省3-5秒）
- DOM兜底：如果API拦截没拿到数据，从页面HTML提取 `<h1>`/`meta[og:title]` 作为标题

**关键代码逻辑**：
```python
# on_response 拦截器（必须在if not ok: return的外面，否则死代码）
async def on_response(response):
    nonlocal detail_api_body, captured_images
    resp_url = response.url
    # 拦截详情API
    if 'mtop' in resp_url and 'detail' in resp_url ...:
        body = await response.text()
        if body and len(body) > 5000:
            detail_api_body = body  # 最大的那个响应体
    # 拦截图片
    if 'alicdn.com' in resp_url and ('bao/uploaded' in resp_url ...):
        body = await response.body()
        if body and len(body) > 3000:
            captured_images[img_id] = body  # 按O1CN0 ID去重
```

## 模块2：图片下载（xianyu_tool.py 内 download_product_images）

**做什么**：下载商品原图到本地。

**技术方案**：Playwright拦截数据优先 + httpx兜底下载

**为什么这样设计**：
- 拦截到的图片二进制数据已经在内存里了，不用再请求一次，省时间和避免触发风控
- 但拦截数据可能不全（页面加载时机问题），所以没拦截到的用 httpx 带 Referer 头直接下载
- alicdn图片可能是WebP/RIFF格式，用Pillow统一转JPEG保存

## 模块3a：AI去水印（watermark_cleaner.py）

**做什么**：自动检测商品图片上的水印文字（店铺名、"禁止盗图"等），修复后看不到修过痕迹。

**技术方案**：GLM-4V多模态AI定位 → LaMa（缺失时降级 OpenCV）图像修复 → 羽化贴回

**为什么这样设计**：

去水印的核心难点是：①怎么知道哪里有水印 ②怎么修掉 ③怎么让修复区域和周围自然过渡。

**三步流程**：

**步骤1：GLM-4V-Flash检测水印位置**
- 用智谱免费的多模态AI（GLM-4V-Flash）看图片，返回水印区域的百分比坐标
- prompt设计：要求返回 `y1,y2,x1,x2` 格式的坐标，支持多块水印（分号分隔）
- 返回 `无水印` / 坐标 / 不确定 三种状态
- 每张图独立检测（3并发，单张失败自动重试一次）。早期实现是"先测第1张，无水印就全跳过"，
  但那会漏掉"第1张干净、第3张有水印"的情况，已改为逐张判断
- 判定含水印与否用短语匹配而非单字匹配：`"没有水印"` 里也含"有"字，
  用 `'有' in answer` 会把干净的图误判成有水印

**步骤2：图像修复（LaMa 优先，OpenCV 兜底）**
- LaMa是专用的图像修复模型（`simple-lama-inpainting`），擅长填充被mask的区域
- 第1轮：mask覆盖所有水印区域（膨胀7×7核×2次迭代防止边缘残留），LaMa填充
- 第2轮：缩小每个区域mask 10%边距，再修一次，修复第1轮的残留瑕疵
- mask膨胀参数选择：7×7核+2次迭代是经验值，太小修不干净，太大会模糊周围内容
- **降级路径**：LaMa 依赖 torch，打包体积会多几百 MB。如果环境里没有
  `simple-lama-inpainting`，自动降级到 OpenCV `inpaint(TELEA)`——效果弱一些，
  但零额外依赖，保证功能不会静默失效
- `get_lama()` 用双重检查锁做单例，避免多线程同时加载多份模型（每份约200MB）

**步骤3：羽化贴回**
- 修复结果和原图可能有色彩/纹理差异，直接贴回去会有明显接缝
- `_feather_blend` 函数：在修复区域中心采用修复结果，向边缘 12px 内渐变回原图
- 羽化半径会按区域尺寸自适应（`radius = min(12, 半高, 半宽)`），
  否则区域较小时中心永远达不到满强度，小水印会残留
- feather=12是经验值，太小有接缝，太大修复效果被稀释

**保守策略**：GLM 判定"有水印"但没给出可用坐标时，**不做修复、直接保留原图**。
早期实现会退回一个默认区域（图片中部 25% 高度整条），一旦误判就把商品主体抹掉，
比不去水印更糟。

**为什么不用OCR方案**：PaddleOCR能识别文字但无法精确定位半透明水印的边界（水印文字和商品图片融合在一起），GLM-4V作为多模态AI能理解"半透明文字覆盖在图片上"这种语义。

## 模块3b：三版文案生成（module3_copywriter.py）

**做什么**：基于原商品文案生成3个差异化版本，支持多账号运营不撞车。

**技术方案**：V1本地词典 + V2 AI微调 + V3 AI重写（智谱GLM-4-Flash）

**为什么三版而不是一版**：
- V1瞬间完成（本地替换），满足"快速改一下"的需求
- V2保持原文结构微调措辞，满足"像原文但不一样"
- V3完全重写，满足"彻底不同"

**V1 词典替换**：
- 维护一个同义词词典（`SYNONYM_DICT`）：如"入手"→"拿下"/"购入"，"赶紧"→"抓紧"/"速来"
- `NO_REPLACE` 集合保护专有名词不被替换（如"USB"、"插线板"）
- `random.choice(synonyms)` 每次刷新选不同同义词，保证结果不同
- 后处理 `post_process`：去emoji + 替换违禁词 + 清理空句（"，。"→"。"）

**V2 AI微调**：
- prompt规则：保持原文结构/卖点顺序/价格规格不变，只调整措辞和语气
- 用智谱GLM-4-Flash（免费不限量），temperature=0.7
- max_tokens=1200（原文通常200-400字，1200够用不截断）
- 刷新时temperature随机0.6-0.95，每次结果不同

**V3 AI完整重写**：
- prompt规则：重新组织卖点顺序，用完全不同的表达，加入使用场景描述
- 支持自定义提示词（`v3_ai_custom_rewrite`）：用户可输入"改成学生党风格"等要求
- max_tokens=1000，temperature随机0.6-0.95

**违禁词检测**（`filter_banned`）：
- `BANNED_WORDS` 列表：绝对违禁词（"第一"、"顶级"、"100%正品"等）
- `BANNED_SINGLE` 字典：单字违禁词上下文检查（"最"在"最后"/"最新"中是正常用法）
- `POST_REPLACE` 字典：自动替换（"白菜价"→"实惠价"、"超级"→"特别"）
- `remove_emoji`：用精确的Unicode块范围去emoji，不误伤中文字符

**V2/V3并行优化**：
- 用 `ThreadPoolExecutor(max_workers=2)` 并行调V2和V3，总耗时=max(V2,V3)而非V2+V3
- 主流程中文案生成与图片下载/去水印并行（`threading.Thread`），总耗时进一步缩短

## 模块5：补充图搜索（xianyu_tool.py 内 search_extra_images）

**做什么**：用商品图搜百度识图，下载同类商品图片凑齐9张。

**技术方案**：百度识图Playwright脚本 + GLM-4V过滤

**为什么独立触发不在主流程跑**：
- 百度识图搜索+下载+过滤耗时较长（20-30秒），放在主流程会拖慢整体速度
- 改为用户点"刷新补充图"按钮独立触发，有数量输入（5-30张）和独立刷新

**过滤逻辑**：
- 搜3倍于需要的图片数（多搜多过滤）
- GLM-4V对比参考图和搜索结果，过滤掉带水印的和非同款的
- 保存为 `search_XX.jpg`

## 防封号模块（anti_detect.py）

**做什么**：降低被闲鱼风控系统拦截的概率。

**为什么需要**：
- 频繁请求同一页面 → 触发频率风控
- 纯自动化行为（无滚动、无鼠标移动）→ 触发行为风控
- 批量抓取 → 触发数量风控

**具体策略**：

| 策略 | 实现 | 参数 |
|------|------|------|
| 频率控制 | `RateLimiter` 类，每次请求前检查间隔+日限额 | min_interval=3s, max_interval=6s, daily_limit=30 |
| 人类行为模拟 | `human_like_scroll`：分段滚动（3-6步，每步200-600px，随机停顿0.5-1.5s），偶尔往回滚 | 随机参数 |
| 鼠标模拟 | `random_mouse_move`：随机移动2-5次，坐标随机 | 随机参数 |
| 指数退避 | `retry_with_backoff`：失败后2s→4s→8s重试，带30%抖动 | max_retries=3 |
| 风控检测 | `check_risk_indicators`：检查页面文本是否含验证码/滑块/频繁请求等关键词 | 14个关键词 |
| UA池 | 5个Chrome UA随机轮换 | - |

**计数持久化**：日限额计数存在 `%TEMP%\xianyu_tool\request_count.json`，按日期重置。

## GUI层（xianyu_gui.py + gui_embed.html）

**技术方案**：PyWebView 6.2.1 + Edge WebView2 + HTML/CSS/JS

**为什么不用Electron/Tkinter/PyQt**：
- ~~Electron~~：太重（100MB+运行时），打包后体积大
- ~~Tkinter~~：界面太丑，做不出毛玻璃/动画效果
- ~~PyQt~~：授权协议LGPL有限制，打包复杂
- ~~Flet~~：Flutter客户端网络超时，不稳定
- **PyWebView**：用系统自带WebView2渲染HTML，轻量（6.2.1仅几MB），能做现代CSS动画

**Api桥接层**：
- Python类 `Api` 通过 `js_api` 参数暴露给前端JS
- 前端JS直接调用 `window.pywebview.api.run_tool(url, search_max)`
- 长耗时操作（解析/去水印/文案）在线程内跑asyncio事件循环，避免阻塞UI
- 图片以base64 data URL返回前端显示
- 文案结果通过 `get_copies` 读JSON返回

**前端界面**（gui_embed.html）：
- 蜡笔小新冬夜主题：深蓝星空背景 + 飘雪动画 + 毛玻璃卡片
- 6个Tab：商品信息 / 原图 / 去水印 / 文案 / 补充图 / 视频
- CSS动画：snowfall（飘雪）、twinkle（星星闪烁）、fadeInUp（卡片入场）、breathe（状态呼吸）
- 检查更新功能：标题栏按钮，3种状态（绿点=最新/黄点呼吸=有新版/旋转=检查中），支持"跳过此版本"
- 首次使用6步引导弹窗（看过一次后不再弹出，记录在 localStorage）

## 打包方案（PyInstaller + NSIS）

**为什么选这个组合**：
- ~~PyInstaller单文件exe~~：每次启动解压到临时目录，慢3-5秒
- ~~目录模式~~：秒开但一堆文件看着乱
- **PyInstaller目录模式 + NSIS安装包**：秒开 + 正规安装体验 + 可卸载

**PyInstaller配置**（XianyuTool.spec）：
- `--windowed`：无控制台窗口
- `--add-data`：只打包 gui_embed.html / wallpaper.jpg / cacert.pem / xianyu_icon.ico
- `--hidden-import`：playwright.async_api / anti_detect / watermark_cleaner / simple_lama_inpainting / certifi
- `--collect-data certifi`：收集certifi证书数据
- `excludes`：matplotlib / PyQt5 / PyQt6 / PySide2 / PySide6 / jedi / IPython / jupyter 系列 / Pythonwin
  （均未使用，排除后体积从 378MB 降到 268MB；注意**不能**排除 tkinter，保存文件的对话框依赖它）
- `upx=False`：UPX 压缩过的 PyInstaller 产物在国内杀软里误报率很高，用户下载即被隔离
- **不打包 api_config.json 和任何 .py 源码**：前者会泄露开发者自己的 Key，
  后者 PyInstaller 已编译进 pyz，多放一份只是把源码明文暴露给最终用户

**NSIS安装包**（installer.nsi）：
- 全ASCII脚本（含中文会 `Bad text encoding` 编译失败）
- `MUI_PAGE_DIRECTORY`：支持自定义安装路径
- `RequestExecutionLevel User`：免UAC，默认装到 `%LOCALAPPDATA%\XianyuTool`
- 注册表 `HKCU\Software\XianyuTool` 记录安装路径+版本号（单反斜杠，与读取端一致）
- 自动创建桌面快捷方式 + 开始菜单
- 三处卸载入口：安装目录/开始菜单/系统设置
- 注意：`InstallDirRegKey` 的优先级高于命令行 `/D=` 参数，想换安装目录要先清掉注册表里的旧路径

**SSL证书修复**：
- 问题：PyInstaller打包后Python找不到系统CA证书，httpx请求GitHub API报 `CERTIFICATE_VERIFY_FAILED`
- 方案：把 `cacert.pem`（238KB）直接打包进exe，代码设 `os.environ['SSL_CERT_FILE']` 和 `REQUESTS_CA_BUNDLE`

## 性能优化

| 优化点 | 优化前 | 优化后 | 节省 |
|--------|--------|--------|------|
| 模块1：sleep改轮询 | sleep(8)+sleep(3) | 0.5s轮询最多30次 | ~20s |
| 模块3a：GLM-4V并行检测 | 串行8张 | ThreadPoolExecutor 3线程 | ~18s |
| 模块3b：V2/V3并行 | 串行调API | ThreadPoolExecutor 2线程 | ~10s |
| 模块3b：文案与去水印并行 | 等去水印完再生成文案 | 后台线程同时跑 | ~25s |
| 模块1：已登录跳过首页 | 每次访问首页检测Cookie | 标记文件存在直接访问商品页 | ~3s |

> 注：早期版本有一个"先测第1张图，无水印则全套跳过"的预检优化，省约20秒，
> 但会漏掉"第1张干净、后面某张有水印"的情况，现已移除，改为逐张判断。
| **总计** | **~150s** | **~60s** | **~90s** |

---
