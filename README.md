# 闲鱼辅助工具

粘贴一条闲鱼商品链接，自动完成：解析商品信息、下载图片、去水印、生成三版文案、搜索补充图。

Windows 桌面程序，装完直接用，不需要 Python 或额外浏览器。

## 功能

| 模块 | 说明 |
|------|------|
| 链接解析 | 从分享链接提取标题、价格、卖家、商品描述和全部图片 |
| 去水印 | 视觉模型定位水印区域，用 LaMa 或 OpenCV 填补，边缘羽化过渡 |
| 三版文案 | V1 词典替换 / V2 AI 微调 / V3 AI 重写，三套不重样 |
| 补充图 | 百度识图找同类商品图，自动过滤带水印的 |
| 批量处理 | 多链接排队处理，串行执行，失败的可以重试 |
| 历史记录 | 处理过的商品都保留着，随时能重新打开 |

界面支持深色 / 浅色 / 跟随系统三种主题。

## 截图

![演示](docs/demo_real.gif)

## 安装

### 下载安装包（推荐）

1. 到 [Releases](https://github.com/Qiu-Difeng/xianyu-tool/releases/latest) 下载 `XianyuTool_Setup.exe`
2. 双击安装，可以改安装路径
3. 打开程序，首次会弹出 API Key 配置窗口
4. 粘贴 Key，点「保存并验证」
5. 首次处理商品时会弹出浏览器窗口，扫码登录闲鱼，之后会记住

### 从源码运行

```bash
pip install -r requirements.txt
python -m playwright install chromium
python xianyu_gui.py
```

需要 Python 3.8+。

## 配置 API Key

程序不内置 Key，需要自己填。首次启动会弹窗引导，之后点右上角的「Key 已配置」可以修改。

支持的服务商（都走 OpenAI 兼容协议）：

| 服务商 | 文本模型 | 视觉模型 | 说明 |
|--------|----------|----------|------|
| 智谱 AI | glm-4-flash | glm-4v-flash | 两个都免费不限量，[申请地址](https://open.bigmodel.cn/) |
| 魔搭 ModelScope | Qwen2.5-72B-Instruct | Qwen2-VL-7B-Instruct | 有免费额度 |
| DeepSeek | deepseek-chat | 无 | 不支持图片，去水印要另配视觉模型 |
| 自定义 | 任意 | 任意 | 填任意兼容 `/chat/completions` 的地址 |

**文本模型和视觉模型可以分开配**。勾选配置窗口里的「高级：文本/视觉分开配」，就能让文案走 DeepSeek、去水印走智谱，各用各的 Key。

视觉模型必须支持图片输入，否则去水印会提示不可用。

配置存在 `%LOCALAPPDATA%\XianyuTool\api_config.json`，只在本机读取。也支持环境变量 `ZHIPUAI_API_KEY`。

## 使用

基本流程就一步：粘贴链接，点「开始」。

```
粘贴链接 → 点开始 → 等待 → 查看结果
                        ↓
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
     原图 9 张      去水印图 9 张    三版文案
```

处理过程中：

- 每个版本的文案旁边有刷新按钮，不满意可以单独重新生成
- 图片和文案都能一键保存到指定目录
- 商品有视频的话，视频标签页可以直接下载

**批量处理**在「批量」标签页：每行粘一条链接，点「加入队列」，再点「开始处理」。串行执行，每条之间会间隔几秒。失败的条目可以一键重试。

**历史记录**在页面底部，能看到之前处理过的所有商品，点「加载」可以重新查看图片和文案。

## 常见问题

<details>
<summary><b>需要安装 Chrome 吗？</b></summary>

不需要。程序会优先用 Playwright 自带的 Chromium，没有的话自动用系统 Edge 或 Chrome（Win10/11 都自带）。
</details>

<details>
<summary><b>需要安装 Python 吗？</b></summary>

下载安装包版本不需要。从源码运行需要 Python 3.8+。
</details>

<details>
<summary><b>扫码登录安全吗？</b></summary>

登录数据保存在本机 `%LOCALAPPDATA%\XianyuTool_ChromeData`，不会上传到任何地方。
</details>

<details>
<summary><b>提示 API Key 未配置怎么办？</b></summary>

首次启动会自动弹窗。如果误点了「稍后配置」，点右上角的「Key 未配置」按钮重新打开。
</details>

<details>
<summary><b>提示"缺少 vcruntime140.dll"怎么办？</b></summary>

正常情况下不会出现，安装包已经带了 VC++ 运行库。如果还是报错，装一下
[VC++ 运行库](https://aka.ms/vs/17/release/vc_redist.x64.exe)。
</details>

<details>
<summary><b>界面白屏或提示缺 WebView2</b></summary>

界面基于 WebView2，Win10 1803 以上系统自带。老系统装一下
[WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。
</details>

<details>
<summary><b>去水印效果如何？</b></summary>

视觉模型先判断水印在哪，再用修复算法填补，边缘做羽化过渡。每张图单独检测，没水印的直接保留原样。

环境里没有 LaMa 模型时会降级用 OpenCV 修复，效果弱一点但不会失效。
如果模型只说了"有水印"但给不出具体位置，程序会保留原图，不会乱抹一块。
</details>

<details>
<summary><b>会被封号吗？</b></summary>

工具有防封号设计：每日最多处理 50 条链接、请求间隔 1.5-3 秒随机、模拟人类滚动和鼠标移动、
检测风控关键词。但这些只能降低概率，不能保证。建议控制使用频率。
</details>

<details>
<summary><b>处理速度大概多快？</b></summary>

实测单条 24 秒左右（解析 15 秒 + 下载 0.4 秒 + 去水印 8 秒，文案在后台另算）。
耗时跟商品图片数量、水印多少、模型响应速度都有关系，网速慢或者模型排队时会明显变长。
</details>

<details>
<summary><b>出错了怎么反馈？</b></summary>

页面底部点「运行日志」，弹窗里能一键复制，也可以直接打开日志文件夹。
把日志发到 Issues 里就行。

日志位置：`%LOCALAPPDATA%\XianyuTool\logs\`，按天分文件，保留 14 天。
</details>

## 项目结构

```
xianyu_gui.py          PyWebView 窗口 + Python 与 JS 的桥接
xianyu_tool.py         主流程编排
module1_parser.py      链接解析（Playwright + API 拦截）
module3_copywriter.py  三版文案生成
watermark_cleaner.py   去水印
llm_provider.py        大模型调用（支持任意 OpenAI 兼容服务）
anti_detect.py         防封号：限流、拟人行为
task_queue.py          批量任务队列
app_logger.py          日志落盘
gui_embed.html         界面产物（由 ui/ 合并生成，不要直接改）
ui/                    界面源码：style.css + 8 个 js 模块 + 模板
build_ui.py            把 ui/ 合并成 gui_embed.html
XianyuTool.spec        PyInstaller 打包配置
installer.nsi          NSIS 安装包脚本
```

界面源码是拆开的，但运行时必须是单文件——因为 PyWebView 用 `html=` 加载时页面是
`about:blank`，浏览器不允许这种页面引用外部 JS/CSS。所以改完 `ui/` 要跑一次：

```bash
python build_ui.py
```

打包时会自动执行这一步（已集成进 spec）。

## 开发说明

技术实现细节、各模块设计取舍、踩过的坑都写在 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 免责声明

本工具仅供学习交流。使用时请遵守闲鱼平台规则，因使用本工具产生的后果由使用者自行承担。

## License

MIT
