# 🐟 闲鱼辅助工具

> 闲鱼商品文案与图片一站式处理桌面工具

## ✨ 功能

| 模块 | 功能 | 技术 |
|------|------|------|
| 🔗 链接解析 | 输入闲鱼商品链接，自动提取标题、文案、价格、图片 | Playwright + 闲鱼API拦截 |
| 📦 图片下载 | 并行下载商品原图 | httpx异步 |
| 🧽 去水印 | AI检测水印位置 → LaMa修复 → 羽化贴回 | GLM-4V + LaMa + OpenCV |
| 📝 三版文案 | V1词典替换 / V2 AI微调 / V3 AI重写（可自定义提示词） | 智谱GLM-4-Flash |
| 🔍 补充图 | 百度识图搜相似商品图，凑齐9张 | Playwright + GLM-4V过滤 |

## 🚀 快速开始

### 方式一：下载安装包（推荐，零配置）

1. 前往 [Releases页面](https://github.com/Qiu-Difeng/xianyu-tool/releases/latest)
2. 下载 `XianyuTool_Setup.exe`
3. 双击安装，可选择安装路径
4. 桌面出现 `XianyuTool` 快捷方式，双击运行
5. 首次运行会弹出Chromium窗口 → 扫码登录闲鱼
6. 后续运行自动复用登录态，无需重新扫码

**不需要安装Python、Chrome或任何依赖，安装即用。**

### 方式二：从源码运行

#### 环境要求
- Windows 10/11
- Python 3.8+
- 网络环境能访问闲鱼和智谱API

#### 安装依赖
```bash
pip install -r requirements.txt
python -m playwright install chromium
```

#### 配置API Key
设置智谱API Key环境变量（免费申请：https://open.bigmodel.cn/）：
```bash
set ZHIPUAI_API_KEY=你的API Key
```

#### 运行
```bash
python xianyu_gui.py
```

### 打包（目录模式 + NSIS安装包）
```bash
# PyInstaller目录模式
pyinstaller --noconfirm --windowed --name "XianyuTool" \
  --icon="xianyu_icon.ico" \
  --add-data "gui_embed.html;." \
  --add-data "wallpaper.jpg;." \
  --add-data "cacert.pem;." \
  --hidden-import=playwright.async_api \
  --hidden-import=anti_detect \
  --hidden-import=watermark_cleaner \
  --hidden-import=simple_lama_inpainting \
  --hidden-import=certifi \
  --collect-data certifi \
  xianyu_gui.py

# NSIS安装包
makensis installer.nsi
```

## 🏗️ 项目结构
```
├── xianyu_gui.py          # 主入口，PyWebView GUI
├── gui_embed.html         # 前端界面（蜡笔小新冬夜主题）
├── xianyu_tool.py         # 主流程编排（5大模块串联）
├── module1_parser.py      # 模块1：闲鱼链接解析
├── module3_copywriter.py  # 模块3：三版文案生成
├── watermark_cleaner.py   # 去水印：GLM-4V检测 + LaMa修复
├── anti_detect.py         # 防封号：频率控制 + 人类行为模拟
├── wallpaper.jpg          # 界面壁纸
├── xianyu_icon.ico        # 应用图标
└── requirements.txt       # 依赖清单
```

## 🔧 技术架构

- **GUI**：PyWebView 6.2.1 + Edge WebView2 + HTML/CSS/JS
- **浏览器自动化**：Playwright（自带Chromium，独立数据目录）
- **去水印**：GLM-4V-Flash多模态检测（免费）+ LaMa图像修复 + OpenCV羽化贴回
- **文案生成**：智谱GLM-4-Flash（免费不限量）
- **打包**：PyInstaller（目录模式，启动快）

## 📋 使用流程

1. 首次运行 → 弹出Chromium窗口 → 扫码登录闲鱼
2. 后续运行 → 后台无头模式，自动复用Cookie
3. 粘贴闲鱼商品链接 → 点击"开始处理"
4. 等待5大模块自动完成（约60-80秒）
5. 查看：原图 / 去水印图 / 三版文案 / 补充图 / 视频
6. 可独立刷新文案（V1/V2/V3各自不同结果）和补充图

## ❓ 常见问题

**Q: 需要安装Chrome浏览器吗？**
A: 不需要。工具内置Playwright自带的Chromium，与日常浏览器完全独立。

**Q: 需要安装Python吗？**
A: 下载exe版不需要。从源码运行需要Python 3.8+。

**Q: 首次使用要扫码登录安全吗？**
A: 安全。登录数据保存在本地 `%LOCALAPPDATA%\XianyuTool_ChromeData`，不会上传任何地方。

## ⚠️ 免责声明

本工具仅供学习交流使用。使用者需遵守闲鱼平台规则，对使用本工具产生的任何后果自行负责。

## 📄 License

MIT License - 可自由使用、修改、分发
