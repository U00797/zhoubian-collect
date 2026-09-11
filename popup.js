const $ = (s) => document.querySelector(s);
const BRIDGE = "http://127.0.0.1:8768";

function status(msg, isError = false) {
  const el = $("status");
  el.textContent = msg;
  el.style.color = isError ? "#b3261e" : "#888";
}

function activeTab(timeout = 8000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("读取当前标签页超时，请重新打开插件再试")), timeout);
    try {
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        clearTimeout(timer);
        const err = chrome.runtime.lastError;
        if (err) reject(new Error(err.message));
        else resolve(tabs && tabs[0] ? tabs[0] : null);
      });
    } catch (err) {
      clearTimeout(timer);
      reject(err);
    }
  });
}

function collectPage(want) {
  const abs = (u) => {
    try { return new URL(u, location.href).href; } catch (e) { return u; }
  };
  const meta = (sel) => {
    const e = document.querySelector(sel);
    return e ? (e.content || e.getAttribute("content") || "").trim() : "";
  };
  const textOf = (sels) => {
    for (const sel of sels) {
      const e = document.querySelector(sel);
      if (e && (e.innerText || e.textContent || "").trim().length >= 8) {
        return (e.innerText || e.textContent).trim();
      }
    }
    return "";
  };
  const host = location.hostname.toLowerCase();
  const platform = want === "auto"
    ? (host.includes("xiaohongshu") ? "xiaohongshu" : host.includes("weibo") ? "weibo" : "unknown")
    : want;
  const title = meta('meta[property="og:title"]') || document.title;
  const desc = meta('meta[property="og:description"]') || meta('meta[name="description"]') || "";
  const author = meta('meta[property="og:author"]')
    || textOf(["[class*='username']", "[class*='author']", "[class*='name']"]);
  const published = meta('meta[property="article:published_time"]');
  const text = textOf([
    "#detail-desc",
    "[class*='note-text']",
    "[class*='note-content']",
    "[node-type='feed_list_content']",
    "[class*='wbpro-feed-content']",
    "[class*='weibo-text']",
    "[class*='WB_text']",
    "article"
  ]) || desc;

  const cand = [];
  document.querySelectorAll('meta[property="og:image"]').forEach((e) => {
    if (e.content) cand.push(e.content);
  });
  document.querySelectorAll("img, source").forEach((e) => {
    const s = e.currentSrc || e.src || e.getAttribute("srcset")
      || e.getAttribute("data-src") || e.getAttribute("data-original")
      || e.getAttribute("data-lazy-src") || "";
    if (s) cand.push(String(s).split(",")[0].trim());
  });

  const CDN = /xhscdn\.com|sns-webpic|ci\.xiaohongshu|sinaimg\.cn|weibo|pstatp|byteimg|qpic\.cn|qq\.com/i;
  const BAD = /data:|\.(svg|gif)(\?|$)/i;
  const AVATAR = /avatar|profile_pic|orj360|thumb150|\/(30|50)\//i;
  const seen = new Set();
  const images = [];
  for (const c of cand) {
    const u = abs(c);
    if (!/^https?:/i.test(u) || BAD.test(u) || AVATAR.test(u)) continue;
    if (!CDN.test(u) || seen.has(u)) continue;
    seen.add(u);
    images.push(u);
    if (images.length >= 40) break;
  }

  const videos = [];
  const ov = meta('meta[property="og:video"]');
  if (ov) videos.push(abs(ov));
  document.querySelectorAll("video, video source").forEach((e) => {
    if (e.src) videos.push(abs(e.src));
  });
  return { platform, url: location.href, title, author, published, text, desc, images, videos };
}

async function archive() {
  const btn = $("go");
  const mode = $("mode").value;
  const target = $("target").value;
  const archiveDir = $("archiveDir").value.trim();
  if (mode === "ai" && !archiveDir) {
    status("请先填写归档位置。", true);
    return;
  }
  btn.disabled = true;
  status("正在采集当前页…");
  try {
    const current = await activeTab();
    if (!current || !current.id) throw new Error("取不到当前标签页");
    const href = current.url || "";
    if (!/xiaohongshu\.com|weibo\.com|weibo\.cn/i.test(href)) {
      throw new Error("当前页面不是小红书或微博");
    }
    const res = await chrome.scripting.executeScript({
      target: { tabId: current.id },
      func: collectPage,
      args: [$("platformSel").value]
    });
    const data = res && res[0] && res[0].result;
    if (!data) throw new Error("页面无内容");
    if (data.platform === "unknown") throw new Error("当前页面不是小红书或微博");
    if (!data.text && !data.images.length) throw new Error("未读取到正文或图片，请等页面加载完再试");
    data.mode = mode;
    data.archive_target = target;
    data.archive_dir = archiveDir;

    status("已采集，正在提交本地服务…");
    const resp = await fetch(`${BRIDGE}/api/queue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });
    const result = await resp.json();
    if (!resp.ok) throw new Error(result.error || `服务返回 ${resp.status}`);
    localStorage.setItem("zhoubianMode", mode);
    localStorage.setItem("zhoubianTarget", target);
    localStorage.setItem("zhoubianArchiveDir", archiveDir);
    localStorage.setItem("zhoubianPlatform", $("platformSel").value);
    status(result.message || "处理完成。");
  } catch (err) {
    const hint = String(err.message).includes("fetch")
      ? "本地服务未启动，请先运行 zhoubian-edge-collector\\start-server.cmd"
      : "";
    status("归档失败：" + err.message + (hint ? "，" + hint : ""), true);
  } finally {
    btn.disabled = false;
  }
}

$("go").addEventListener("click", archive);

function syncMode() {
  const isAI = $("mode").value === "ai";
  $("aiOptions").hidden = !isAI;
  $("archiveDirLabel").textContent = isAI ? "归档位置" : "结果目录（可选）";
  $("archiveDir").placeholder = isAI
    ? "例如 C:\\Users\\me\\Documents\\周边归档"
    : "留空则保存到项目 output 目录";
  $("go").textContent = isAI ? "识别并归档" : "生成结果包";
}

$("mode").addEventListener("change", syncMode);

const savedMode = localStorage.getItem("zhoubianMode");
const savedTarget = localStorage.getItem("zhoubianTarget");
const savedDir = localStorage.getItem("zhoubianArchiveDir");
const savedPlatform = localStorage.getItem("zhoubianPlatform");
if (savedMode) $("mode").value = savedMode;
if (savedTarget) $("target").value = savedTarget;
if (savedDir) $("archiveDir").value = savedDir;
if (savedPlatform) $("platformSel").value = savedPlatform;
syncMode();

activeTab().then((tab) => {
  const href = tab && tab.url ? tab.url : "";
  $("url").textContent = tab ? (tab.title || "") + (href ? " · " + href : "") : "无当前标签页";
  $("go").disabled = !/xiaohongshu\.com|weibo\.com|weibo\.cn/i.test(href);
  if ($("go").disabled) status("当前页不是小红书或微博。", true);
}).catch((err) => status("读取标签页失败：" + err.message, true));
