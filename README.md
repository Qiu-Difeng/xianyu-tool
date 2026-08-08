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

### 环境要求
- Windows 10/11
- Python 3.8+
- 网络环境能访问闲鱼和智谱API

### 安装依赖
```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### 配置
设置智谱API Key环境变量（免费申请：https://open.bigmodel.cn/）：
```bash
set ZHIPUAI_API_KEY=你的API Key
```

### 运行
```bash
python xianyu_gui.py
```

### 打包
```bash
pyinstaller --noconfirm --windowed --name "闲鱼辅助工具" \
  --icon="xianyu_icon.ico" \
  --add-data "gui_embed.html;." \
  --add-data "wallpaper.jpg;." \
  --hidden-import=playwright.async_api \
  --hidden-import=anti_detect \
  --hidden-import=watermark_cleaner \
  --hidden-import=simple_lama_inpainting \
  xianyu_gui.py
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

1. 首次运行 → 弹出浏览器窗口 → 扫码登录闲鱼
2. 后续运行 → 后台无头模式，自动复用Cookie
3. 粘贴闲鱼商品链接 → 点击"开始处理"
4. 等待5大模块自动完成（约60-80秒）
5. 查看：原图 / 去水印图 / 三版文案 / 补充图 / 视频
6. 可独立刷新文案（V1/V2/V3各自不同结果）和补充图

## ⚠️ 免责声明

本工具仅供学习交流使用。使用者需遵守闲鱼平台规则，对使用本工具产生的任何后果自行负责。

## 📄 License

MIT License - 可自由使用、修改、分发
