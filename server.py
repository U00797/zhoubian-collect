#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local bridge: browser page -> result bundle -> optional Codex export."""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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


def extract_rows(payload):
    text = str(payload.get("text") or payload.get("desc") or "").strip()
    lines = clean_lines(text)
    title = str(payload.get("title") or "").strip()
    image_paths = [str(path) for path in payload.get("image_paths") or []]

    ip = first_match(lines, r"(?:^|\b)(?:IP|作品)\s*[:：]\s*([^。；;]+)") or title
    publisher = first_match(
        lines, r"(?:出品方?|发行|制作)\s*[:：]\s*([^。；;]+)")
    series = first_match(lines, r"(?:系列|主题)\s*[:：]\s*([^。；;]+)")
    release_date = first_match(
        lines,
        r"(?:发售|开售|上线|预约|截团|开团)[^0-9]*"
        r"(\d{4}\s*[年./-]\s*\d{1,2}(?:\s*[月./-]\s*\d{1,2})?\s*日?)",
    )
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
        return (
            not origin
            or origin.startswith("chrome-extension://")
            or origin.startswith("moz-extension://")
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
        if self.path in ("/", "/health"):
            cfg = load_config()
            self._json(200, {
                "ok": True,
                "service": "zhoubian-edge-collector bridge",
                "codex_thread": bool(cfg.get("codex_thread")),
                "codex_cli": bool(resolve_codex_cli(cfg)),
            })
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
