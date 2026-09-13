const sourceUrl = document.querySelector("#sourceUrl");
const keywords = document.querySelector("#keywords");
const generateButton = document.querySelector("#generateButton");
const exportButton = document.querySelector("#exportButton");
const status = document.querySelector("#status");
const tableWrap = document.querySelector("#tableWrap");
const resultsBody = document.querySelector("#resultsBody");
const themeToggle = document.querySelector("#themeToggle");

const columns = [
  ["publisher", "出品方"],
  ["release_date", "发售时间及地点"],
  ["ip", "IP名称"],
  ["series", "系列"],
  ["items", "周边明细"],
  ["spec", "尺寸丨材质丨工艺"],
  ["price", "价格"],
  ["images", "图片"],
  ["notes", "备注"]
];

let rows = [];

function setStatus(message, type = "") {
  status.textContent = message;
  status.className = "status" + (type ? ` ${type}` : "");
}

function formatSpec(value) {
  return String(value ?? "")
    .split(/[；;]+/)
    .map((part) => {
      let text = part.trim().replace(/\s+/g, " ");
      text = text.replace(/^(【[^】]+】)\s*/, "$1\n");
      text = text.replace(/\s*(尺寸|材质|工艺)\s*[:：]?\s*/g, "\n$1 ");
      return text.trim();
    })
    .filter(Boolean)
    .join("\n");
}

function emptyCell(cell, value) {
  const text = String(value ?? "").trim();
  if (text) {
    cell.textContent = text;
  } else {
    cell.textContent = "\\";
    cell.classList.add("empty-value");
  }
}

function imageCell(cell, images) {
  if (!images || !images.length) {
    cell.textContent = "\\";
    cell.className = "empty-value";
    return;
  }
  const list = document.createElement("div");
  list.className = "image-list";
  for (const path of images) {
    const link = document.createElement("a");
    link.href = path;
    link.target = "_blank";
    link.rel = "noopener";
    const image = document.createElement("img");
    image.src = path;
    image.alt = "周边图片";
    image.loading = "lazy";
    link.append(image);
    list.append(link);
  }
  cell.append(list);
}

function rowCellValue(row, key) {
  if (key === "images") {
    return JSON.stringify(row.images || []);
  }
  if (key === "spec") {
    return formatSpec(row[key]);
  }
  return String(row[key] ?? "").trim();
}

function buildRowSpans() {
  return columns.map(([key]) => {
    const spans = Array(rows.length).fill(1);
    if (["items", "spec", "price", "images"].includes(key)) {
      return spans;
    }
    let start = 0;
    while (start < rows.length) {
      let end = start + 1;
      const value = rowCellValue(rows[start], key);
      while (end < rows.length && rowCellValue(rows[end], key) === value) {
        end += 1;
      }
      if (end - start > 1) {
        spans[start] = end - start;
        for (let index = start + 1; index < end; index += 1) {
          spans[index] = 0;
        }
      }
      start = end;
    }
    return spans;
  });
}

function renderRows() {
  resultsBody.replaceChildren();
  const rowSpans = buildRowSpans();
  for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
    const row = rows[rowIndex];
    const tr = document.createElement("tr");
    for (let columnIndex = 0; columnIndex < columns.length; columnIndex += 1) {
      const [key] = columns[columnIndex];
      const span = rowSpans[columnIndex][rowIndex];
      if (!span) {
        continue;
      }
      const td = document.createElement("td");
      td.rowSpan = span;
      td.classList.add(`cell-${key}`);
      if (key === "images") {
        imageCell(td, row.images);
      } else {
        emptyCell(td, key === "spec" ? formatSpec(row[key]) : row[key]);
      }
      tr.append(td);
    }
    resultsBody.append(tr);
  }
  tableWrap.hidden = rows.length === 0;
  exportButton.disabled = rows.length === 0;
}

function csvValue(value) {
  let text = String(value ?? "");
  if (/^\s*[=+\-@]/.test(text)) {
    text = "'" + text;
  }
  return `"${text.replace(/"/g, '""')}"`;
}

function exportCsv() {
  if (!rows.length) return;
  const lines = [columns.map(([, label]) => csvValue(label)).join(",")];
  for (const row of rows) {
    lines.push(columns.map(([key]) => {
      let value;
      if (key === "images") {
        value = (row.images || [])
          .map((path) => new URL(path, location.origin).href)
          .join("; ") || "\\";
      } else if (key === "spec") {
        value = formatSpec(row[key]) || "\\";
      } else {
        value = row[key] || "\\";
      }
      return csvValue(value);
    }).join(","));
  }
  const blob = new Blob(["\ufeff" + lines.join("\r\n")], {
    type: "text/csv;charset=utf-8"
  });
  const link = document.createElement("a");
  const stamp = new Date().toISOString().replace(/\D/g, "").slice(0, 12);
  link.href = URL.createObjectURL(blob);
  link.download = `周边明细_${stamp}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

async function generate() {
  const url = sourceUrl.value.trim();
  if (!url) {
    setStatus("请先填写微博或小红书网址。", "error");
    sourceUrl.focus();
    return;
  }

  generateButton.disabled = true;
  exportButton.disabled = true;
  tableWrap.hidden = true;
  rows = [];
  setStatus("正在获取链接并生成明细…", "loading");

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, keywords: keywords.value })
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || `服务返回 ${response.status}`);
    }
    rows = result.rows || [];
    renderRows();
    setStatus(
      `已生成 ${rows.length} 行明细。` +
      (result.notice ? ` ${result.notice}` : "")
    );
  } catch (error) {
    renderRows();
    setStatus(`生成失败：${error.message}`, "error");
  } finally {
    generateButton.disabled = false;
    exportButton.disabled = rows.length === 0;
  }
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const dark = theme === "dark";
  themeToggle.textContent = dark ? "白天模式" : "夜间模式";
  themeToggle.setAttribute("aria-pressed", String(dark));
  localStorage.setItem("zhoubianTheme", theme);
}

const savedTheme = localStorage.getItem("zhoubianTheme");
setTheme(savedTheme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));

themeToggle.addEventListener("click", () => {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});
generateButton.addEventListener("click", generate);
exportButton.addEventListener("click", exportCsv);
sourceUrl.addEventListener("keydown", (event) => {
  if (event.key === "Enter") generate();
});
