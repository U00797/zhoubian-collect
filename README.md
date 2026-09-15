# 周边明细生成器 · Zhoubian Collect

一个本地运行的微博/小红书周边宣传页识别、明细生成与归档工具。粘贴帖子网址后，工具会读取正文和商品图片，生成结构化周边明细，并导出为多种笔记软件和表格软件可用的格式。

项目同时提供：

- 本地网页：`http://127.0.0.1:8768/`
- Edge/Chrome 浏览器扩展
- AI 图片识别与自动归档
- 无 AI 本地表格导出
- Markdown、HTML、ZIP、ENEX、Excel、CSV 六种导出格式

> 这是本地工具，不是公共在线网站。其他人需要下载本仓库并在自己的电脑上运行。

## 功能

### 周边明细识别

支持微博和小红书帖子，自动读取正文、长图和商品图，并生成以下字段：

| 字段 | 说明 |
| --- | --- |
| 出品方 | 识别“出品/出品方”主体 |
| 发售时间及地点 | 综合正文和图片整理发售日期、地点和展位 |
| 系列 | 识别商品所属主题或系列 |
| IP名称 | 识别作品或 IP |
| 周边明细 | 每个独立商品或套组生成一行 |
| 尺寸丨材质丨工艺 | 读取商品图小字，保留已识别到的任意项目 |
| 价格 | 保留原文计价单位和售卖方式 |
| 图片 | 自动裁剪对应商品图 |
| 备注 | 汇总 72H 特典、满赠档位、条件和赠品信息 |

### 网页功能

- 白天/夜间模式
- 标题行冻结
- 重复字段自动合并
- 表格单元格完整框线
- 图片列不合并，每行展示对应商品图
- 移动端和桌面端自适应

### 导出格式

| 格式 | 图片 | 推荐用途 |
| --- | --- | --- |
| Markdown | 相对图片链接 | Obsidian、Logseq、Joplin、Notion |
| HTML | 图片以 Base64 内嵌 | 浏览器、OneNote、Apple Notes、通用富文本导入 |
| ZIP | 包含 Markdown、HTML、ENEX、CSV、XLSX 和图片目录 | 完整迁移、备份和导入 Markdown 笔记库 |
| ENEX | 图片作为 Evernote 资源嵌入 | Evernote、印象笔记 |
| Excel（XLSX） | 图片嵌入单元格 | Excel、WPS、Numbers |
| CSV | 图片输出为地址 | 通用表格导入、二次处理 |

## 快速开始

### 环境要求

- Windows 10/11
- Python 3
- Edge 或 Chrome
- 使用 AI 识别时，需要安装并登录 Codex CLI

### 启动

1. 下载或克隆本仓库。
2. 双击 `start-server.cmd`。
3. 脚本会自动检查并安装 `Pillow` 和 `openpyxl`。
4. 看到 `Zhoubian bridge ready` 后，打开：

```text
http://127.0.0.1:8768/
```

也可以手动启动：

```bash
python -m pip install -r requirements.txt
python server.py
```

首次启动会生成 `config.json`。如果使用 AI 模式，需要填写当前 Codex 会话 ID。

## 网页使用

1. 粘贴微博或小红书网址。
2. 关键词可留空，多个关键词用逗号分隔。
3. 点击“生成周边明细”。
4. 检查表格结果。
5. 按需要导出 Markdown、HTML、ZIP、ENEX、Excel 或 CSV。

AI 识别会先切分超长宣传图，避免长图缩放后漏读小字，再将商品图坐标映射回原图进行裁剪。

## 浏览器插件

插件支持 Edge 和 Chrome：

1. 打开浏览器的扩展管理页。
2. 开启“开发人员模式”。
3. 选择“加载已解压的扩展程序”。
4. 选中本仓库目录。

插件提供两种处理方式：

### AI 自动识别并归档

选择目标软件和归档位置，任务会交给当前 Codex 会话。支持：

- Obsidian：Markdown 和图片附件
- WPS：表格或 CSV
- 印象笔记：ENEX 或 HTML
- 其他软件/文件夹：按目标位置选择合适格式

### 无 AI 本地导出

无需 Codex CLI，直接根据正文生成初表并保存原始图片。海报内文字需要人工补录。

## 结果文件

每个任务会生成独立目录：

```text
output/<任务号>/
  source.json
  result.json
  result.csv
  result.xlsx
  result.md
  result.html
  result.enex
  result-bundle.zip
  images/
    crops/
    vision_slices/
```

文件说明：

- `source.json`：原始帖子内容、图片地址和任务配置
- `result.json`：结构化明细，适合程序继续处理
- `result.csv`：通用表格
- `result.xlsx`：带嵌入图片的 Excel
- `result.md`：带图片 Markdown 链接的笔记文件
- `result.html`：图片内嵌的单文件网页
- `result.enex`：Evernote/印象笔记导入文件
- `result-bundle.zip`：包含以上结果和图片的完整压缩包
- `images/crops/`：每条明细对应的裁图
- `images/vision_slices/`：长图识别时使用的切片

## 配置

`config.json` 示例：

```json
{
  "host": "127.0.0.1",
  "port": 8768,
  "codex_cli": "",
  "codex_thread": "",
  "output_dir": "output"
}
```

配置说明：

- `host`：监听地址，默认只允许本机访问
- `port`：本地服务端口，默认 `8768`
- `codex_cli`：Codex CLI 路径，留空时自动查找
- `codex_thread`：AI 模式使用的当前 Codex 会话 ID
- `output_dir`：任务结果目录，默认 `output`

只使用无 AI 模式时，不需要配置 `codex_cli` 和 `codex_thread`。

## 其他用户如何使用

分享 GitHub 仓库只能分享代码。其他用户需要：

1. 下载或克隆仓库。
2. 在自己的电脑运行 `start-server.cmd`。
3. 使用自己的 Codex CLI 登录状态。
4. 打开自己的 `http://127.0.0.1:8768/`。

如果需要所有用户直接打开同一个网址，必须将服务部署到云服务器，并增加登录、限流和文件清理。

## 已知限制

- 仅支持微博和小红书公开帖子。
- AI 识别结果可能受原图清晰度、排版和遮挡影响，建议生成后人工校对。
- CSV 不支持嵌入图片。
- 单独下载 Markdown 文件时，图片需要同时保留 `images/` 目录；使用 ZIP 可避免遗漏。
- 当前服务默认监听 `127.0.0.1`，局域网或公网访问需要额外配置。

## 自检

```bash
python server.py --self-test
```

自检覆盖文本解析、长图切片、图片裁剪、系列回退、结果文件生成、HTML、ENEX、ZIP 和 Excel 图片嵌入。

## 项目结构

```text
app.js              网页交互和导出
index.html          网页界面
style.css           白天/夜间主题和表格样式
server.py           本地服务、识别、裁剪与格式导出
popup.html          浏览器扩展界面
popup.js            浏览器扩展逻辑
manifest.json       扩展配置
start-server.cmd    Windows 启动脚本
requirements.txt    Python 依赖
config.example.json 配置示例
```

## 交给 AI 辅助安装

可以把仓库地址交给支持本地文件和命令操作的 Codex、Claude Code 或同类 Agent，并说明系统、浏览器以及是否使用 AI 模式。Agent 可以完成依赖安装、配置检查、服务启动和自检。

浏览器首次加载未打包扩展仍需用户本人在扩展管理页确认，AI 不能绕过浏览器安全提示。
