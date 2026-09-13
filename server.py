#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local bridge: browser page -> result bundle -> optional Codex export."""

import argparse
import csv
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
TARGETS = {
    "obsidian": "Obsidian",
    "wps": "WPS",
    "evernote": "印象笔记",
    "other": "其他软件 / 文件夹",
}
MODES = {
    "ai": "AI 自动识别",
    "local": "无 AI 本地导出",
}
EXPORT_COLUMNS = (
    ("ip", "IP"),
    ("publisher", "出品方"),
    ("release_date", "发售时间"),
    ("series", "系列"),
    ("items", "制品明细"),
    ("spec", "尺寸材质"),
    ("price", "价格"),
    ("images", "图片"),
    ("notes", "备注"),
    ("source_text", "原文"),
)
WEB_COLUMNS = (
    ("publisher", "出品方"),
    ("release_date", "发售时间"),
    ("ip", "IP名称"),
    ("items", "周边明细"),
    ("spec", "尺寸材质"),
    ("price", "价格"),
    ("images", "图片"),
    ("notes", "备注"),
)
DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8768,
    "codex_cli": os.environ.get("CODEX_CLI_PATH", ""),
    "codex_thread": os.environ.get("CODEX_THREAD_ID", ""),
    "output_dir": "output",
}
PRICE_RE = re.compile(
    r"(?:(?:¥|￥)\s*)?(\d+(?:\.\d{1,2})?)\s*元"
    r"(?:\s*[/／]\s*(个|对|套|组|枚|张|盒|款|份))?",
    re.IGNORECASE,
)
WEIBO_BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
IMAGE_BAD_RE = re.compile(r"data:|\.(?:svg|gif)(?:\?|$)", re.I)
IMAGE_AVATAR_RE = re.compile(r"avatar|profile_pic|orj360|thumb150|/(?:30|50)/", re.I)


def merge_defaults(cfg):
    for key, value in DEFAULT_CONFIG.items():
        cfg.setdefault(key, value)
    return cfg


def load_config():
    cfg = {}
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    merge_defaults(cfg)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def resolve_codex_cli(cfg):
    candidates = [cfg.get("codex_cli"), os.environ.get("CODEX_CLI_PATH")]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    exes = sorted(local.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    if exes:
        return str(exes[0])
    return shutil.which("codex.exe") or shutil.which("codex") or ""


def target_name(value):
    return TARGETS.get(str(value or "").lower(), str(value or "指定软件"))


def mode_name(value):
    return MODES.get(str(value or "").lower(), MODES["ai"])


def clean_lines(text):
    lines = []
    for raw in str(text or "").splitlines():
        line = " ".join(raw.replace("\u3000", " ").split()).strip()
        if line and line not in lines:
            lines.append(line)
    return lines


def first_match(lines, pattern):
    rx = re.compile(pattern, re.IGNORECASE)
    for line in lines:
        match = rx.search(line)
        if match:
            value = match.group(1) if match.groups() else match.group(0)
            return value.strip(" ：:；;，,。")
    return ""


def keyword_list(value):
    if isinstance(value, list):
        parts = value
    else:
        parts = re.split(r"[,，、;\s]+", str(value or ""))
    return [str(part).strip() for part in parts if str(part).strip()][:20]


def extract_rows(payload):
    text = str(payload.get("text") or payload.get("desc") or "").strip()
    lines = clean_lines(text)
    title = str(payload.get("title") or "").strip()
    image_paths = [str(path) for path in payload.get("image_paths") or []]
    keywords = keyword_list(payload.get("keywords"))

    ip = first_match(lines, r"(?:^|\b)(?:IP|作品)\s*[:：]\s*([^。；;]+)") or title
    publisher = first_match(
        lines, r"(?:出品方?|发行|制作)\s*[:：]\s*([^。；;]+)")
    series = first_match(lines, r"(?:系列|主题)\s*[:：]\s*([^。；;]+)")
    release_date = first_match(
        lines,
        r"(?:发售|开售|上线|预约|截团|开团)[^0-9]*"
        r"(\d{4}\s*[年./-]\s*\d{1,2}(?:\s*[月./-]\s*\d{1,2})?\s*日?)",
    ) or str(payload.get("published") or "").strip()
    spec_lines = [
        line for line in lines
        if re.search(r"尺寸|规格|材质|面料|大小|cm|mm|克|kg|g\b", line, re.I)
    ]
    note_lines = [
        line for line in lines
        if re.search(r"限定|隐藏|满赠|特典|赠品|盲盒|概率", line)
    ]
    base = {
        "ip": ip,
        "publisher": publisher,
        "release_date": release_date,
        "series": series,
        "items": "",
        "spec": "\n".join(spec_lines),
        "price": "",
        "images": image_paths,
        "notes": "\n".join(note_lines),
        "source_text": text,
    }

    rows = []
    for index, line in enumerate(lines):
        prices = list(PRICE_RE.finditer(line))
        if not prices:
            continue
        prefix = line[:prices[0].start()].strip(" -:：|；;，,")
        item = prefix
        if len(item) < 2 and index:
            item = lines[index - 1].strip(" -:：|；;，,")
        for match in prices:
            row = base.copy()
            row["items"] = item or title
            row["price"] = match.group(0).strip()
            rows.append(row)

    if not rows:
        rows.append(base)
    elif keywords:
        keyword_rows = []
        for line in lines:
            if any(keyword.lower() in line.lower() for keyword in keywords):
                row = base.copy()
                row["items"] = line
                keyword_rows.append(row)
        if keyword_rows:
            rows = keyword_rows
    return rows


def markdown_cell(value):
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value)
    return str(value or "").replace("|", "\\|").replace("\n", "<br>")


def write_result_bundle(job_dir, payload, rows):
    public_rows = []
    for row in rows:
        public_rows.append({
            key: row.get(key, []) if key == "images" else row.get(key, "")
            for key, _ in EXPORT_COLUMNS
        })
    bundle = {
        "job_id": payload["job_id"],
        "mode": payload["mode"],
        "source": {
            "platform": payload["platform"],
            "url": payload["url"],
            "title": payload["title"],
            "author": payload["author"],
            "published": payload["published"],
        },
        "rows": public_rows,
    }
    json_path = job_dir / "result.json"
    json_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = job_dir / "result.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([label for _, label in EXPORT_COLUMNS])
        for row in public_rows:
            writer.writerow([
                "; ".join(row[key]) if isinstance(row[key], list) else row[key]
                for key, _ in EXPORT_COLUMNS
            ])

    md_path = job_dir / "result.md"
    headers = [label for _, label in EXPORT_COLUMNS]
    md_lines = [
        f"# {payload['title'] or '周边识别结果'}",
        "",
        f"- 来源：{payload['url']}",
        f"- 平台：{payload['platform']}",
        f"- 模式：{mode_name(payload['mode'])}",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in public_rows:
        md_lines.append(
            "| " + " | ".join(markdown_cell(row[key]) for key, _ in EXPORT_COLUMNS)
            + " |")
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return json_path, csv_path, md_path


def sniff_ext(path):
    head = path.read_bytes()[:16]
    if head[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


def download_images(urls, referer, outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    curl = shutil.which("curl.exe") or shutil.which("curl") or "curl"
    paths = []
    failed = []
    for i, url in enumerate(urls[:40], start=1):
        tmp = outdir / f"{i:02d}.download"
        cmd = [
            curl, "-L", "--fail", "--silent", "--show-error",
            "--max-time", "60",
            "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "-e", referer or url,
            "-o", str(tmp),
            url,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if proc.returncode or not tmp.exists() or tmp.stat().st_size == 0:
                failed.append(url)
                continue
            final = outdir / f"{i:02d}{sniff_ext(tmp)}"
            tmp.replace(final)
            paths.append(str(final))
        except (OSError, subprocess.TimeoutExpired):
            failed.append(url)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
    return paths, failed


def allowed_source_url(url):
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https"):
        return False
    return (
        host == "xiaohongshu.com"
        or host.endswith(".xiaohongshu.com")
        or host == "weibo.com"
        or host.endswith(".weibo.com")
        or host == "weibo.cn"
        or host.endswith(".weibo.cn")
    )


def fetch_text(url, accept="text/html,application/xhtml+xml"):
    req = Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": accept,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Referer": "https://www.xiaohongshu.com/" if "xiaohongshu" in url else "https://weibo.com/",
    })
    try:
        with urlopen(req, timeout=30) as response:
            raw = response.read(5 * 1024 * 1024 + 1)
            if len(raw) > 5 * 1024 * 1024:
                raise RuntimeError("页面内容超过 5MB，无法处理")
            final_url = response.geturl()
            if not allowed_source_url(final_url):
                raise RuntimeError("页面跳转到了不支持的域名")
            charset = response.headers.get_content_charset() or "utf-8"
            return final_url, raw.decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"页面请求失败：HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"页面无法访问：{exc.reason}") from exc


class SourceHTMLParser(HTMLParser):
    BLOCK_TAGS = {
        "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
        "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "li",
        "main", "nav", "p", "section", "td", "th", "tr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.title = ""
        self.text = []
        self.images = []
        self.scripts = []
        self._script = None
        self._title = False

    def handle_starttag(self, tag, attrs):
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key and values.get("content"):
                self.meta[key] = values["content"].strip()
        elif tag == "img":
            source = (
                values.get("src") or values.get("data-src")
                or values.get("data-original") or values.get("data-lazy-src")
            )
            if source:
                self.images.append(source.strip())
        elif tag == "script":
            self._script = []
        elif tag == "title":
            self._title = True
        if tag in self.BLOCK_TAGS:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.scripts.append("".join(self._script))
            self._script = None
        elif tag == "title":
            self._title = False
        elif tag in self.BLOCK_TAGS:
            self.text.append("\n")

    def handle_data(self, data):
        if self._script is not None:
            self._script.append(data)
        elif self._title:
            self.title += data
        else:
            self.text.append(data)


def json_object_at(text, start):
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return ""


def embedded_json(scripts):
    objects = []
    markers = ("__INITIAL_STATE__", "__NEXT_DATA__")
    for script in scripts:
        raw = script.strip()
        if not raw:
            continue
        if "application/json" in raw[:80]:
            raw = raw.split(">", 1)[-1]
        candidates = []
        if raw.startswith("{"):
            candidates.append(raw)
        for marker in markers:
            pos = raw.find(marker)
            if pos >= 0:
                brace = raw.find("{", pos)
                if brace >= 0:
                    candidates.append(json_object_at(raw, brace))
        for candidate in candidates:
            if not candidate:
                continue
            try:
                objects.append(json.loads(candidate))
            except json.JSONDecodeError:
                pass
    return objects


def dict_score(value):
    keys = {
        "desc", "description", "content", "text", "title", "imageList",
        "image_list", "images", "pics", "user", "created_at", "time",
    }
    return sum(1 for key in value if key in keys)


def best_content_dict(value):
    best = None
    best_score = 0
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            score = dict_score(item)
            if score > best_score:
                best = item
                best_score = score
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return best or {}


def nested_text(value):
    if isinstance(value, str):
        return unescape(value)
    if isinstance(value, dict):
        for key in ("text", "content", "desc", "description", "value"):
            if value.get(key):
                return nested_text(value[key])
    return ""


def collect_image_values(value, images):
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            images.append(value)
    elif isinstance(value, list):
        for item in value:
            collect_image_values(item, images)
    elif isinstance(value, dict):
        for key in ("urlDefault", "urlPre", "url", "large", "original", "origin"):
            if key in value:
                collect_image_values(value[key], images)


def state_content(objects):
    content = {}
    for obj in objects:
        item = best_content_dict(obj)
        if not item:
            continue
        text = nested_text(item.get("desc") or item.get("description")
                           or item.get("content") or item.get("text"))
        title = nested_text(item.get("title"))
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        author = nested_text(
            item.get("nickname") or user.get("nickname")
            or user.get("screen_name") or item.get("author")
        )
        published = nested_text(
            item.get("created_at") or item.get("createTime") or item.get("time")
        )
        images = []
        for key in ("imageList", "image_list", "images", "pics"):
            if key in item:
                collect_image_values(item[key], images)
        if text or title or images:
            content = {
                "text": text,
                "title": title,
                "author": author,
                "published": published,
                "images": images,
            }
            if text and images:
                break
    return content


def html_text(raw):
    parser = SourceHTMLParser()
    parser.feed(raw or "")
    return "\n".join(clean_lines("".join(parser.text)))


def weibo_mid_to_id(mid):
    value = 0
    for char in str(mid or ""):
        if char not in WEIBO_BASE62:
            return ""
        value = value * 62 + WEIBO_BASE62.index(char)
    return str(value) if value else ""


def weibo_status_id(url):
    parsed = urlparse(url)
    query_id = parse_qs(parsed.query).get("id", [""])[0]
    if query_id.isdigit():
        return query_id
    patterns = (
        r"/status/(\d+)",
        r"/detail/(\d+)",
        r"/statuses/show/(\d+)",
        r"/\d+/([0-9A-Za-z]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, parsed.path)
        if match:
            value = match.group(1)
            return value if value.isdigit() else weibo_mid_to_id(value)
    return ""


def fetch_weibo_post(url):
    status_id = weibo_status_id(url)
    if not status_id:
        return {}
    _, raw = fetch_text(
        f"https://m.weibo.cn/statuses/show?id={quote(status_id)}",
        accept="application/json,text/plain,*/*",
    )
    try:
        data = json.loads(raw).get("data") or {}
    except json.JSONDecodeError:
        return {}
    if not data:
        return {}
    images = []
    for item in data.get("pics") or []:
        if not isinstance(item, dict):
            continue
        images.append(
            nested_text(item.get("large") or item.get("original") or item.get("url"))
        )
    return {
        "platform": "weibo",
        "title": html_text(data.get("text")) or "微博周边宣传",
        "text": html_text(data.get("text")),
        "author": nested_text((data.get("user") or {}).get("screen_name")),
        "published": nested_text(data.get("created_at")),
        "images": images,
    }


def normalize_images(urls, base_url):
    seen = set()
    result = []
    for value in urls:
        raw = str(value or "").strip()
        if not raw:
            continue
        image_url = urljoin(base_url, raw)
        if not image_url.startswith(("http://", "https://")):
            continue
        image_host = (urlparse(image_url).hostname or "").lower()
        if not any(
            image_host == host or image_host.endswith("." + host)
            for host in ("xhscdn.com", "xiaohongshu.com", "sinaimg.cn",
                         "weibo.com", "weibo.cn", "qpic.cn")
        ):
            continue
        if IMAGE_BAD_RE.search(image_url) or IMAGE_AVATAR_RE.search(image_url):
            continue
        if image_url in seen:
            continue
        seen.add(image_url)
        result.append(image_url)
        if len(result) >= 40:
            break
    return result


def analyze_source(url, keywords):
    if not allowed_source_url(url):
        raise RuntimeError("只支持小红书或微博网址")
    platform = "xiaohongshu" if "xiaohongshu" in urlparse(url).hostname else "weibo"
    if platform == "weibo":
        try:
            source = fetch_weibo_post(url)
            if source:
                source["images"] = normalize_images(source.get("images") or [], url)
                source["url"] = url
                return source
        except RuntimeError:
            pass

    final_url, raw = fetch_text(url)
    parser = SourceHTMLParser()
    parser.feed(raw)
    state = state_content(embedded_json(parser.scripts))
    text = state.get("text") or "\n".join(clean_lines("".join(parser.text)))
    title = (
        state.get("title") or parser.meta.get("og:title")
        or parser.title or "周边宣传"
    )
    author = (
        state.get("author") or parser.meta.get("og:author")
        or parser.meta.get("author") or ""
    )
    published = (
        state.get("published")
        or parser.meta.get("article:published_time") or ""
    )
    images = normalize_images(
        (state.get("images") or []) + [parser.meta.get("og:image", "")]
        + parser.images,
        final_url,
    )
    if not text and not images:
        raise RuntimeError("未读取到正文或图片，请确认帖子可公开访问")
    return {
        "platform": platform,
        "url": final_url,
        "title": title.strip(),
        "author": author.strip(),
        "published": published.strip(),
        "text": text.strip()[:50000],
        "images": images,
    }


def web_analyze(data):
    url = str(data.get("url") or "").strip()
    keywords = keyword_list(data.get("keywords"))
    source = analyze_source(url, keywords)
    payload = {
        "mode": "local",
        "platform": source["platform"],
        "url": source["url"],
        "title": source["title"],
        "author": source["author"],
        "published": source["published"],
        "text": source["text"],
        "images": source["images"],
        "keywords": keywords,
    }
    job = archive_job(payload)
    bundle = json.loads(Path(job["result_json"]).read_text(encoding="utf-8"))
    rows = []
    for row in bundle.get("rows") or []:
        item = {}
        for key, _ in WEB_COLUMNS:
            value = row.get(key) or ""
            if key == "images":
                links = []
                for path in value:
                    try:
                        relative = Path(path).resolve().relative_to(ROOT).as_posix()
                    except (OSError, ValueError):
                        continue
                    links.append("/" + quote(relative))
                item[key] = links
            else:
                item[key] = value
        rows.append(item)
    return {
        "ok": True,
        "job_id": job["job_id"],
        "source": {
            "platform": source["platform"],
            "url": source["url"],
            "title": source["title"],
        },
        "rows": rows,
    }


def queue_to_codex(cfg, source_path, job_dir, data):
    cli = resolve_codex_cli(cfg)
    thread = cfg.get("codex_thread") or ""
    if not cli or not Path(cli).exists():
        raise RuntimeError("未找到 codex 命令，请配置 config.json 的 codex_cli")
    if not thread:
        raise RuntimeError("config.json 未配置 codex_thread（当前 Codex 会话 ID）")

    result_file = job_dir / "result.txt"
    target = target_name(data.get("archive_target"))
    archive_dir = str(Path(data.get("archive_dir") or "").expanduser())
    msg = (
        f"浏览器插件提交了一页周边宣传。源数据在 {source_path}，"
        f"图片已下载到 {job_dir / 'images'}，统一结果包在 {job_dir / 'result.json'}。\n"
        "请读取正文和图片，识别官方宣传中的周边信息，并直接完成归档。\n"
        "先补全或修正 result.json 的 rows，再同步更新 result.csv 和 result.md。\n"
        "识别字段：IP、出品方、上线时间、系列名、制品明细、材质规格、"
        "价格（写成 X元/个 或 X元/对 等原文形式）、图片、备注。"
        "备注只填写限定、隐藏、满赠内容，没有就留空。\n"
        "这是通用周边识别：不要确认或筛选是否与琵琶相关，也不要因为题材不是琵琶而跳过。\n"
        f"归档目标：{target}；归档位置：{archive_dir}。"
        "按目标软件可用格式写入：Obsidian 用 Markdown 并保存图片附件；"
        "WPS 用表格或 CSV；印象笔记用可导入的 ENEX 或 HTML；其他软件选择合适格式。\n"
        f"完成后把归档文件的绝对路径写入 {result_file}，并简要汇报结果。"
    )
    proc = subprocess.run(
        [cli, "queue", "--thread", thread, "--message", msg],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    if proc.returncode:
        detail = (proc.stderr or proc.stdout or "").strip()[:500]
        raise RuntimeError(f"Codex queue 失败：{detail}")


def archive_job(data):
    cfg = load_config()
    mode = str(data.get("mode") or "ai").strip().lower()
    if mode not in MODES:
        raise RuntimeError("未知的处理方式")
    text = (data.get("text") or data.get("desc") or "").strip()
    images = data.get("images") or []
    target = str(data.get("archive_target") or "").strip()
    archive_dir = str(data.get("archive_dir") or "").strip()
    if not text and not images:
        raise RuntimeError("没有正文也没有图片，无法归档")
    if mode == "ai":
        if not target:
            raise RuntimeError("请在插件里选择归档软件")
        if not archive_dir:
            raise RuntimeError("请在插件里填写归档位置")

    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + os.urandom(3).hex()
    base_dir = Path(
        (archive_dir if mode == "local" else "") or cfg.get("output_dir")
        or (ROOT / "output")
    ).expanduser()
    if not base_dir.is_absolute():
        base_dir = ROOT / base_dir
    job_dir = base_dir / job_id
    image_dir = job_dir / "images"
    job_dir.mkdir(parents=True, exist_ok=True)

    image_paths, failed = download_images(images, data.get("url") or "", image_dir)
    payload = {
        "job_id": job_id,
        "mode": mode,
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_type": "zhoubian-edge-collector",
        "platform": data.get("platform") or "unknown",
        "url": data.get("url") or "",
        "title": data.get("title") or "",
        "author": data.get("author") or "",
        "published": data.get("published") or "",
        "text": text,
        "desc": data.get("desc") or "",
        "image_urls": images,
        "image_paths": image_paths,
        "download_failed": failed,
        "archive_target": target,
        "archive_dir": archive_dir,
        "keywords": keyword_list(data.get("keywords")),
    }
    source_path = job_dir / "source.json"
    source_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = extract_rows(payload)
    json_path, csv_path, md_path = write_result_bundle(job_dir, payload, rows)

    if mode == "ai":
        queue_to_codex(cfg, source_path, job_dir, payload)
        note = f"；{len(failed)} 张图下载失败，Codex 会用原始链接补" if failed else ""
        message = (
            f"已交给 Codex（任务 {job_id}，图片 {len(image_paths)} 张，"
            f"归档到 {target_name(target)}）{note}"
        ).rstrip()
    else:
        note = f"；{len(failed)} 张图下载失败" if failed else ""
        message = (
            f"已生成 {len(rows)} 行本地结果（任务 {job_id}，"
            f"图片 {len(image_paths)} 张{note}）。结果：{job_dir}"
        )
    return {
        "ok": True,
        "job_id": job_id,
        "mode": mode,
        "job_dir": str(job_dir),
        "result_json": str(json_path),
        "result_csv": str(csv_path),
        "result_md": str(md_path),
        "images": len(image_paths),
        "message": message,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "ZhoubianBridge/0.3"

    def _allowed_origin(self):
        origin = self.headers.get("Origin") or ""
        parsed = urlparse(origin)
        return (
            not origin
            or origin.startswith("chrome-extension://")
            or origin.startswith("moz-extension://")
            or (
                parsed.scheme in ("http", "https")
                and parsed.hostname in ("127.0.0.1", "localhost")
            )
        )

    def _cors_headers(self):
        origin = self.headers.get("Origin") or ""
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        else:
            self.send_header("Access-Control-Allow-Origin", "*")

    def _json(self, status, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _file(self, path):
        try:
            raw = Path(path).read_bytes()
        except OSError:
            self._json(404, {"ok": False, "error": "not found"})
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in (
            "application/javascript", "application/json",
        ):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _output_file(self, request_path):
        cfg = load_config()
        output_dir = Path(cfg.get("output_dir") or "output").expanduser()
        if not output_dir.is_absolute():
            output_dir = ROOT / output_dir
        relative = unquote(request_path.removeprefix("/output/"))
        target = (output_dir / relative).resolve()
        try:
            target.relative_to(output_dir.resolve())
        except ValueError:
            self._json(403, {"ok": False, "error": "forbidden"})
            return
        self._file(target)

    def do_OPTIONS(self):
        if not self._allowed_origin():
            self._json(403, {"ok": False, "error": "origin not allowed"})
            return
        self.send_response(204)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if not self._allowed_origin():
            self._json(403, {"ok": False, "error": "origin not allowed"})
            return
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._file(ROOT / "index.html")
        elif path == "/style.css":
            self._file(ROOT / "style.css")
        elif path == "/app.js":
            self._file(ROOT / "app.js")
        elif path == "/health":
            cfg = load_config()
            self._json(200, {
                "ok": True,
                "service": "zhoubian-edge-collector bridge",
                "codex_thread": bool(cfg.get("codex_thread")),
                "codex_cli": bool(resolve_codex_cli(cfg)),
            })
        elif path.startswith("/output/"):
            self._output_file(path)
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        try:
            if not self._allowed_origin():
                raise PermissionError("请求来源不受信任")
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 3 * 1024 * 1024:
                raise RuntimeError("请求体为空或超过 3MB")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if self.path == "/api/queue":
                self._json(200, archive_job(data))
            elif self.path == "/api/analyze":
                self._json(200, web_analyze(data))
            else:
                self._json(404, {"ok": False, "error": "not found"})
        except json.JSONDecodeError as exc:
            self._json(400, {"ok": False, "error": "请求不是有效 JSON：" + str(exc)})
        except PermissionError as exc:
            self._json(403, {"ok": False, "error": str(exc)})
        except RuntimeError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._json(500, {"ok": False, "error": str(exc)})

    def log_message(self, fmt, *args):
        sys.stdout.write(f"[zhoubian-bridge] {self.address_string()} - {fmt % args}\n")


def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        sample = Path(tmp) / "a.download"
        sample.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 20)
        assert sniff_ext(sample) == ".jpg"
        sample.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
        assert sniff_ext(sample) == ".png"
        payload = {
            "job_id": "test",
            "mode": "local",
            "platform": "weibo",
            "url": "https://example.com/post",
            "title": "测试系列 周边",
            "author": "",
            "published": "",
            "text": (
                "IP：测试作品\n"
                "系列：测试系列\n"
                "亚克力立牌\n"
                "尺寸：10cm\n"
                "材质：亚克力\n"
                "价格：39元/个\n"
                "满赠：购买套装赠送贴纸"
            ),
            "image_paths": [str(Path(tmp) / "01.jpg")],
        }
        rows = extract_rows(payload)
        assert len(rows) == 1
        assert rows[0]["ip"] == "测试作品"
        assert rows[0]["price"] == "39元/个"
        assert "尺寸：10cm" in rows[0]["spec"]
        assert "满赠" in rows[0]["notes"]
        json_path, csv_path, md_path = write_result_bundle(
            Path(tmp), payload, rows)
        assert json.loads(json_path.read_text(encoding="utf-8"))["rows"]
        assert "39元/个" in csv_path.read_text(encoding="utf-8-sig")
        assert "测试系列" in md_path.read_text(encoding="utf-8")
    assert target_name("wps") == "WPS"
    assert target_name("evernote") == "印象笔记"
    assert mode_name("local") == "无 AI 本地导出"
    assert allowed_source_url("https://www.xiaohongshu.com/explore/example")
    assert allowed_source_url("https://m.weibo.cn/detail/123")
    assert not allowed_source_url("https://example.com/post")
    assert weibo_mid_to_id("10") == "62"
    state = embedded_json([
        'window.__INITIAL_STATE__={"note":{"desc":"立牌 39元/个",'
        '"imageList":[{"urlDefault":"https://example.com/a.jpg"}]}}'
    ])
    parsed = state_content(state)
    assert parsed["text"] == "立牌 39元/个"
    assert parsed["images"] == ["https://example.com/a.jpg"]
    assert normalize_images([
        "https://sns-webpic.xhscdn.com/a.jpg",
        "http://127.0.0.1/private.jpg",
    ], "https://www.xiaohongshu.com/") == [
        "https://sns-webpic.xhscdn.com/a.jpg"
    ]
    keyword_rows = extract_rows({
        "text": "徽章 10元/个\n亚克力立牌 39元/个",
        "title": "测试周边",
        "keywords": ["立牌"],
    })
    assert len(keyword_rows) == 1
    assert "立牌" in keyword_rows[0]["items"]
    print("self-test OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    cfg = load_config()
    if not cfg.get("codex_thread"):
        print(
            "config.json 缺 codex_thread，AI 模式不可用；无 AI 模式不受影响。",
            file=sys.stderr,
        )
    httpd = ThreadingHTTPServer((cfg["host"], cfg["port"]), Handler)
    print(f"Zhoubian bridge ready: http://{cfg['host']}:{cfg['port']}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
