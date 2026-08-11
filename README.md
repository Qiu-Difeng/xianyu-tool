# 🐟 闲鱼辅助工具

> 闲鱼卖家效率神器 — 一键解析商品、AI去水印、智能改写文案、搜补充图

## 🎯 解决什么问题？

闲鱼卖家日常痛点：
- 🔄 多账号运营，文案不能撞车 → **一键生成3版差异化文案**
- 🖼️ 商品图有水印，盗图被封号 → **AI检测+LaMa修复，去水印无痕迹**
- 📸 图片不够9张 → **百度识图搜同类商品图，AI过滤带水印的**
- ⏱️ 手动复制粘贴太慢 → **粘贴链接，60秒全自动处理**

## ✨ 功能一览

| 模块 | 功能 | 效果 |
|------|------|------|
| 🔗 链接解析 | 粘贴闲鱼链接，自动提取标题/文案/价格/图片 | 结构化数据，比爬页面更准 |
| 🧽 AI去水印 | GLM-4V多模态检测水印位置 → LaMa修复 → 羽化贴回 | 无痕迹，保账号安全 |
| 📝 三版文案 | V1词典替换 / V2 AI微调 / V3 AI完整重写 | 3个账号3套文案，不撞车 |
| 🔍 补充图搜索 | 百度识图+GLM-4V过滤水印 | 凑齐9张图不用愁 |
| 📦 图片下载 | 并行下载商品原图 | 秒下 |

## 🖼️ 界面预览

![演示动画](docs/demo_real.gif)

> 🎨 蜡笔小新冬夜主题 — 输入链接 → 自动处理 → 展示结果

## 🚀 快速开始

### 下载安装包（推荐，零配置）

1. 👉 [前往下载](https://github.com/Qiu-Difeng/xianyu-tool/releases/latest)
2. 下载 `XianyuTool_Setup.exe`
3. 双击安装，可选安装路径
4. 桌面出现 `XianyuTool` 快捷方式，双击运行
5. 首次运行弹出Chromium窗口 → 扫码登录闲鱼
6. 以后自动复用登录，不用再扫码

> **不需要安装Python、Chrome或任何依赖，装了就能用。**

### 从源码运行

```bash
# 1. 安装依赖
pip install -r requirements.txt
python -m playwright install chromium

# 2. 配置API Key（免费申请：https://open.bigmodel.cn/）
set ZHIPUAI_API_KEY=你的API Key

# 3. 运行
python xianyu_gui.py
```

## 📋 使用流程

```
粘贴闲鱼链接 → 点「开始」→ 等60秒 → 搞定
                    ↓
        ┌──────────┼──────────┐
        ▼          ▼          ▼
   原图9张    去水印图9张   3版文案
                    ↓
            补充图（独立触发）
```

- 🔄 **V1/V2/V3各有独立刷新按钮**，每次结果不同
- 💾 **一键保存**图片和文案到自选目录
- 🎬 支持下载商品视频

---

## 🏗️ 技术架构与设计思路

### 整体架构

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

### 模块1：链接解析（module1_parser.py）

**做什么**：输入闲鱼商品链接，提取标题、文案、价格、图片URL、视频URL。

**技术方案**：Playwright + 闲鱼API拦截

**为什么这样设计**：

闲鱼有严格的风控系统，未登录状态下所有API端点（`pc.detail`/`awesome.detail`/`item.web.detail`/`buyer.item.detail`）都会返回"被挤爆啦"（RGV587_ERROR）。所以不能用简单的HTTP请求直接调API。

方案演变过程：
1. ~~直接调API~~ → 风控拦截，未登录不可用
2. ~~移动端H5~~ → 同样需要登录态
3. ~~首页Cookie+签名~~ → 签名算法频繁变化
4. **✅ Playwright + API拦截** → 浏览器有完整登录态，拦截网络响应拿结构化数据

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

### 模块2：图片下载（xianyu_tool.py 内 download_product_images）

**做什么**：下载商品原图到本地。

**技术方案**：Playwright拦截数据优先 + httpx兜底下载

**为什么这样设计**：
- 拦截到的图片二进制数据已经在内存里了，不用再请求一次，省时间和避免触发风控
- 但拦截数据可能不全（页面加载时机问题），所以没拦截到的用 httpx 带 Referer 头直接下载
- alicdn图片可能是WebP/RIFF格式，用Pillow统一转JPEG保存

### 模块3a：AI去水印（watermark_cleaner.py）

**做什么**：自动检测商品图片上的水印文字（店铺名、"禁止盗图"等），修复后看不到修过痕迹。

**技术方案**：GLM-4V多模态AI定位 → LaMa图像修复 → 羽化贴回

**为什么这样设计**：

去水印的核心难点是：①怎么知道哪里有水印 ②怎么修掉 ③怎么让修复区域和周围自然过渡。

**三步流程**：

**步骤1：GLM-4V-Flash检测水印位置**
- 用智谱免费的多模态AI（GLM-4V-Flash）看图片，返回水印区域的百分比坐标
- prompt设计：要求返回 `y1,y2,x1,x2` 格式的坐标，支持多块水印（分号分隔）
- 返回 `无水印` / 坐标 / 不确定 三种状态
- 快速预检优化：先只检测第1张图，无水印就全跳过（1秒完成），有水印才并行检测剩余图片（ThreadPoolExecutor max_workers=6）

**步骤2：LaMa双轮修复**
- LaMa是专用的图像修复模型（`simple-lama-inpainting`），擅长填充被mask的区域
- 第1轮：mask覆盖所有水印区域（膨胀7×7核×2次迭代防止边缘残留），LaMa填充
- 第2轮：缩小每个区域mask 10%边距，再修一次，修复第1轮的残留瑕疵
- mask膨胀参数选择：7×7核+2次迭代是经验值，太小修不干净，太大会模糊周围内容

**步骤3：羽化贴回**
- LaMa修复的水印区域可能和原图有色彩/纹理差异，直接贴回去会有明显接缝
- `_feather_blend` 函数：在修复区域和原图之间做12px的渐变过渡（边缘alpha从0到1线性变化）
- 效果：修复区域的核心保持LaMa结果，边缘逐渐过渡到原图，看不出接缝
- feather=12是经验值，太小有接缝，太大修复效果被稀释

**为什么不用OCR方案**：PaddleOCR能识别文字但无法精确定位半透明水印的边界（水印文字和商品图片融合在一起），GLM-4V作为多模态AI能理解"半透明文字覆盖在图片上"这种语义。

### 模块3b：三版文案生成（module3_copywriter.py）

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

### 模块5：补充图搜索（xianyu_tool.py 内 search_extra_images）

**做什么**：用商品图搜百度识图，下载同类商品图片凑齐9张。

**技术方案**：百度识图Playwright脚本 + GLM-4V过滤

**为什么独立触发不在主流程跑**：
- 百度识图搜索+下载+过滤耗时较长（20-30秒），放在主流程会拖慢整体速度
- 改为用户点"刷新补充图"按钮独立触发，有数量输入（5-30张）和独立刷新

**过滤逻辑**：
- 搜3倍于需要的图片数（多搜多过滤）
- GLM-4V对比参考图和搜索结果，过滤掉带水印的和非同款的
- 保存为 `search_XX.jpg`

### 防封号模块（anti_detect.py）

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

### GUI层（xianyu_gui.py + gui_embed.html）

**技术方案**：PyWebView 6.2.1 + Edge WebView2 + HTML/CSS/JS

**为什么不用Electron/Tkinter/PyQt**：
- ~~Electron~~：太重（100MB+运行时），打包后体积大
- ~~Tkinter~~：界面太丑，做不出毛玻璃/动画效果
- ~~PyQt~~：授权协议LGPL有限制，打包复杂
- ~~Flet~~：Flutter客户端网络超时，不稳定
- **✅ PyWebView**：用系统自带WebView2渲染HTML，轻量（6.2.1仅几MB），能做现代CSS动画

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
- 首次使用6步引导弹窗

### 打包方案（PyInstaller + NSIS）

**为什么选这个组合**：
- ~~PyInstaller单文件exe~~：每次启动解压到临时目录，慢3-5秒
- ~~目录模式~~：秒开但一堆文件看着乱
- **✅ PyInstaller目录模式 + NSIS安装包**：秒开 + 正规安装体验 + 可卸载

**PyInstaller配置**（XianyuTool.spec）：
- `--windowed`：无控制台窗口
- `--add-data`：打包 gui_embed.html / wallpaper.jpg / cacert.pem
- `--hidden-import`：playwright.async_api / anti_detect / watermark_cleaner / simple_lama_inpainting / certifi
- `--collect-data certifi`：收集certifi证书数据

**NSIS安装包**（installer.nsi）：
- 全ASCII脚本（中文编码会导致NSIS编译失败）
- `MUI_PAGE_DIRECTORY`：支持自定义安装路径
- `RequestExecutionLevel User`：免UAC，默认装到 `%LOCALAPPDATA%\XianyuTool`
- 注册表 `HKCU\Software\XianyuTool` 记录安装路径+版本号
- 自动创建桌面快捷方式 + 开始菜单
- 三处卸载入口：安装目录/开始菜单/系统设置

**SSL证书修复**：
- 问题：PyInstaller打包后Python找不到系统CA证书，httpx请求GitHub API报 `CERTIFICATE_VERIFY_FAILED`
- 方案：把 `cacert.pem`（238KB）直接打包进exe，代码设 `os.environ['SSL_CERT_FILE']` 和 `REQUESTS_CA_BUNDLE`

### 性能优化

| 优化点 | 优化前 | 优化后 | 节省 |
|--------|--------|--------|------|
| 模块1：sleep改轮询 | sleep(8)+sleep(3) | 0.5s轮询最多30次 | ~20s |
| 模块3a：去水印快速预检 | 每张都检测 | 先检测第1张，无水印全跳过 | ~20s |
| 模块3a：GLM-4V并行检测 | 串行8张 | ThreadPoolExecutor 6线程 | ~18s |
| 模块3b：V2/V3并行 | 串行调API | ThreadPoolExecutor 2线程 | ~10s |
| 模块3b：文案与去水印并行 | 等去水印完再生成文案 | 后台线程同时跑 | ~25s |
| 模块1：已登录跳过首页 | 每次访问首页检测Cookie | 标记文件存在直接访问商品页 | ~3s |
| **总计** | **~150s** | **~60s** | **~90s** |

---

## 📁 项目结构

```
├── xianyu_gui.py          # 🚪 主入口，PyWebView GUI + API桥接
├── gui_embed.html         # 🎨 前端界面（蜡笔小新冬夜主题）
├── xianyu_tool.py         # ⚙️ 主流程编排（5大模块串联 + 并行优化）
├── module1_parser.py      # 🔗 链接解析（Playwright + API拦截）
├── module3_copywriter.py  # 📝 三版文案（V1词典/V2微调/V3重写 + 违禁词检测）
├── watermark_cleaner.py   # 🧽 去水印（GLM-4V检测 + LaMa双轮修复 + 羽化贴回）
├── anti_detect.py         # 🛡️ 防封号（频率控制 + 行为模拟 + 风控检测）
├── installer.nsi          # 📦 NSIS安装包脚本
├── XianyuTool.spec        # 📋 PyInstaller打包配置
├── cacert.pem             # 🔒 SSL证书（打包进exe）
├── wallpaper.jpg          # 🖼️ 界面壁纸
├── xianyu_icon.ico        # 🎯 应用图标
├── requirements.txt       # 📋 依赖清单
└── docs/                  # 📸 截图
```

## ❓ 常见问题

<details>
<summary><b>需要安装Chrome吗？</b></summary>
不需要。工具内置Playwright自带的Chromium，与日常浏览器完全独立。
</details>

<details>
<summary><b>需要安装Python吗？</b></summary>
下载exe版不需要。从源码运行需要Python 3.8+。
</details>

<details>
<summary><b>首次扫码登录安全吗？</b></summary>
安全。登录数据保存在本地 `%LOCALAPPDATA%\XianyuTool_ChromeData`，不会上传任何地方。
</details>

<details>
<summary><b>API Key怎么申请？</b></summary>
智谱AI开放平台（https://open.bigmodel.cn/）免费注册即可，GLM-4-Flash和GLM-4V-Flash都是免费不限量的。
</details>

<details>
<summary><b>去水印效果怎么样？</b></summary>
GLM-4V多模态AI定位水印区域 → LaMa图像修复算法填补 → 12px羽化贴回保证边缘过渡自然。无水印图片自动跳过（1秒完成）。
</details>

<details>
<summary><b>会被封号吗？</b></summary>
工具有防封号模块：每日限额30个链接、请求间隔3-6秒随机、模拟人类滚动和鼠标移动、风控关键词检测。但不能100%保证，建议控制使用频率。
</details>

## ⚠️ 免责声明

本工具仅供学习交流使用。使用者需遵守闲鱼平台规则，对使用本工具产生的任何后果自行负责。

## 📄 License

MIT License - 可自由使用、修改、分发

---

<div align="center">

**如果这个工具帮到了你，点个 ⭐ Star 支持一下！**

[下载安装包](https://github.com/Qiu-Difeng/xianyu-tool/releases/latest) · [报告问题](https://github.com/Qiu-Difeng/xianyu-tool/issues) · [查看源码](https://github.com/Qiu-Difeng/xianyu-tool)

</div>
