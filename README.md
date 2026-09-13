# Zhoubian Collect · 识别并归档

小红书/微博官方周边宣传页的明细生成与归档工具。可以直接使用本地网站，也可以通过浏览器插件提交当前页面。默认走 AI 识别和归档；没有 AI 时会生成可直接打开、编辑和导入的本地结果包。

## 安装

1. 双击 `start-server.cmd` 启动本地桥接服务，窗口显示 `Zhoubian bridge ready`。
2. 浏览器打开 `http://127.0.0.1:8768/`，在“周边明细生成器”中粘贴微博或小红书网址。
3. 如需使用插件模式，在 Edge/Chrome 的扩展管理页开启“开发人员模式”，选择“加载已解压的扩展程序”，选中本目录。

首次启动会生成 `config.json`。也可以先把 `config.example.json` 复制为 `config.json` 再修改。

## 使用

网站模式直接填写网址；关键词可以不填，多个关键词用逗号分隔。生成结果会同时读取正文和商品图片，包含出品方、发售时间及地点、系列、IP名称、周边明细、尺寸丨材质丨工艺、价格、图片和备注，并可导出 CSV。

插件模式需要选择来源平台，处理方式有两种：

- `AI 自动识别并归档`：选择归档软件和位置，任务会交给当前 Codex 会话处理。
- `无 AI 本地导出`：不需要 AI，结果写到 `output/<任务号>/`；也可以在插件里指定其他目录。

无论选择哪种方式，任务都会先生成统一结果包：

```text
output/<任务号>/
  source.json
  result.json
  result.csv
  result.md
  images/
```

其中 `result.csv` 可以直接用 Excel、WPS 打开，`result.md` 可以直接导入 Obsidian、Notion 等支持 Markdown 的工具，`result.json` 可供后续程序或 AI 工作流继续处理。

AI 模式会读取正文和图片并补全、修正 `result.json`、`result.csv`、`result.md`，字段包括：

- IP、出品方、上线时间、系列名
- 制品明细、材质规格、价格（`X元/个`、`X元/对` 等原文写法）
- 图片，以及只包含限定、隐藏、满赠内容的备注

无 AI 模式会先用正文规则生成初表，并完整保存原始图片；海报内文字暂需人工补录。后续接入本地 OCR 时不需要改变结果格式。

这是通用周边识别，不筛选或确认是否与琵琶相关。

归档软件支持 Obsidian、WPS、印象笔记和其他软件/文件夹：

- Obsidian：写 Markdown 并保存图片附件。
- WPS：写表格或 CSV。
- 印象笔记：写可导入的 ENEX 或 HTML。
- 其他：按目标位置选择合适格式。

## 换会话来用

`config.json` 的主要配置如下：

```json
{
  "host": "127.0.0.1",
  "port": 8768,
  "codex_cli": "",
  "codex_thread": "当前 Codex 会话 ID",
  "output_dir": "output"
}
```

`codex_cli` 留空时自动查找本机 Codex CLI；找不到再填写 `codex.exe` 的绝对路径。使用 AI 模式时，把 `codex_thread` 改成当前 Codex 会话 ID。

只用无 AI 模式时，不需要配置 `codex_cli` 和 `codex_thread`。

## 交给 AI 辅助安装

把本仓库的 GitHub 地址交给支持本地文件和命令操作的 Codex、Claude Code 或同类 Agent，并说明新电脑的系统、浏览器，以及是否使用 AI 模式。Agent 可以完成仓库下载、Python 检查、依赖和配置检查、启动服务及自检。

Browser 扩展的“开发者模式加载未打包扩展”通常仍需要用户本人确认，AI 不能绕过浏览器的安全提示。

## 自检

```bash
python server.py --self-test
```
