// Cloudflare Worker「lottery-data-gate」
//
// 路徑：
//   GET  /?key=...                 → 驗證金鑰後，從「私有」GitHub repo 讀 data.json 轉給程式(原本的功能，行為不變)
//   POST /report?key=...&app=&v=   → 程式回傳的螢幕資訊，存進 KV(綁定名稱 SCREEN_KV)
//   POST /ping?key=...&app=&v=     → 使用人數：每支手機每天第一次打開送一筆，記第一次/最後一次使用日與累計使用天數(存同一個 KV)
//   GET  /admin?pw=...             → 你自己看的總表：使用人數＋螢幕資訊(密碼放在 ADMIN_PASSWORD)；加 &format=json 拿原始資料
//
// Cloudflare 上要設定的東西(Settings → Variables and Secrets / Bindings)：
//   ALLOWED_KEYS    允許的程式金鑰(逗號分隔)——原本就有
//   GITHUB_TOKEN    讀私有 repo 的唯讀 Token(Secret)——原本就有
//   ADMIN_PASSWORD  看總表用的密碼(Secret)——新增
//   SCREEN_KV       KV 綁定，指到 SCREEN_REPORTS 這個 KV——新增
//
// 回傳資料只收螢幕尺寸、型號、排版檢查等；不存 IP、不存任何個人資料。

const GITHUB_REPO = "redwinds542688-gif/Lottery-database";
const GITHUB_BRANCH = "main";
const GITHUB_DATA_PATH = "data.json";
const REPORT_PREFIX = "scr:";
const DEVICE_PREFIX = "dev:";
const REPORT_MAX_BYTES = 8000;
const KNOWN_APPS = { main: "主程式", zhua539: "抓539" };

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: Object.assign({ "Content-Type": "application/json; charset=utf-8" }, CORS),
  });
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS });
    }

    if (url.pathname === "/admin") {
      return handleAdmin(url, env);
    }

    const allowedKeys = (env.ALLOWED_KEYS || "").split(",").map(function (s) {
      return s.trim();
    }).filter(Boolean);
    const clientKey = url.searchParams.get("key") || "";
    if (!clientKey || allowedKeys.indexOf(clientKey) === -1) {
      return json({ error: "unauthorized", message: "此版本已不再支援，請更新到最新版" }, 403);
    }

    if (url.pathname === "/ping") {
      if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
      return handlePing(request, env);
    }

    if (url.pathname === "/report") {
      if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
      return handleReport(request, env);
    }

    return handleData(env);
  },
};

// ---------- 原本的功能：轉發開獎資料 ----------
async function handleData(env) {
  if (!env.GITHUB_TOKEN) {
    return json({ error: "server_misconfigured" }, 500);
  }
  const apiUrl =
    "https://api.github.com/repos/" + GITHUB_REPO +
    "/contents/" + GITHUB_DATA_PATH + "?ref=" + GITHUB_BRANCH;
  const upstreamRes = await fetch(apiUrl, {
    headers: {
      "Authorization": "Bearer " + env.GITHUB_TOKEN,
      // application/vnd.github.raw：直接拿到檔案原始內容，不用另外 base64 解碼
      "Accept": "application/vnd.github.raw",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "lottery-data-gate-worker",
    },
    cf: { cacheTtl: 30 },
  });
  if (!upstreamRes.ok) {
    return json({ error: "upstream_error", status: upstreamRes.status }, 502);
  }
  const body = await upstreamRes.text();
  return new Response(body, {
    status: 200,
    headers: Object.assign({ "Content-Type": "application/json" }, CORS),
  });
}

// ---------- 新功能：收螢幕資訊 ----------
async function handleReport(request, env) {
  if (!env.SCREEN_KV) return json({ error: "kv_not_bound", message: "Worker 還沒綁定 SCREEN_KV" }, 503);
  const text = await request.text();
  if (text.length > REPORT_MAX_BYTES) return json({ error: "too_large" }, 413);
  let d;
  try { d = JSON.parse(text); } catch (e) { return json({ error: "bad_json" }, 400); }
  if (!d || typeof d !== "object") return json({ error: "bad_json" }, 400);
  const app = String(d.app || "");
  const deviceId = String(d.deviceId || "");
  const mode = String(d.mode || "");
  if (!KNOWN_APPS[app]) return json({ error: "bad_app" }, 400);
  if (!/^[A-Za-z0-9-]{8,64}$/.test(deviceId)) return json({ error: "bad_device" }, 400);
  if (["app", "web", "file"].indexOf(mode) === -1) return json({ error: "bad_mode" }, 400);

  const record = { t: new Date().toISOString(), data: d };
  const problems = d.layout && Array.isArray(d.layout.problems) ? d.layout.problems.length : 0;
  // metadata 讓總表不用每筆都讀，也方便之後排序
  const meta = { t: record.t, app: app, v: String(d.v || "").slice(0, 20), mode: mode, model: String(d.model || "").slice(0, 40), p: problems };
  await env.SCREEN_KV.put(REPORT_PREFIX + app + ":" + deviceId + ":" + mode, JSON.stringify(record), { metadata: meta });
  return json({ ok: true });
}

// ---------- 新功能：使用人數 ----------
function twDay(d) {
  try { return (d || new Date()).toLocaleDateString("sv-SE", { timeZone: "Asia/Taipei" }); } catch (e) { return (d || new Date()).toISOString().slice(0, 10); }
}

async function handlePing(request, env) {
  if (!env.SCREEN_KV) return json({ error: "kv_not_bound", message: "Worker 還沒綁定 SCREEN_KV" }, 503);
  const text = await request.text();
  if (text.length > 2000) return json({ error: "too_large" }, 413);
  let d;
  try { d = JSON.parse(text); } catch (e) { return json({ error: "bad_json" }, 400); }
  const app = String((d && d.app) || "");
  const deviceId = String((d && d.deviceId) || "");
  if (!KNOWN_APPS[app]) return json({ error: "bad_app" }, 400);
  if (!/^[A-Za-z0-9-]{8,64}$/.test(deviceId)) return json({ error: "bad_device" }, 400);
  const key = DEVICE_PREFIX + app + ":" + deviceId;
  const today = twDay();
  const now = new Date().toISOString();
  const old = (await env.SCREEN_KV.get(key, "json")) || null;
  const rec = {
    app: app, deviceId: deviceId,
    first: old ? old.first : now,
    last: now,
    lastDay: today,
    days: old ? (old.lastDay === today ? old.days : (old.days || 0) + 1) : 1,
    v: String(d.v || "").slice(0, 20),
    mode: String(d.mode || "").slice(0, 10),
    model: String(d.model || "").slice(0, 40),
    platform: String(d.platform || "").slice(0, 20),
  };
  await env.SCREEN_KV.put(key, JSON.stringify(rec), { metadata: rec });
  return json({ ok: true });
}

// ---------- 新功能：你看的總表 ----------
async function handleAdmin(url, env) {
  if (!env.ADMIN_PASSWORD) return new Response("尚未設定 ADMIN_PASSWORD", { status: 503 });
  if ((url.searchParams.get("pw") || "") !== env.ADMIN_PASSWORD) return new Response("密碼錯誤", { status: 403 });
  if (!env.SCREEN_KV) return new Response("Worker 還沒綁定 SCREEN_KV", { status: 503 });

  const keys = [];
  let cursor;
  do {
    const page = await env.SCREEN_KV.list({ prefix: REPORT_PREFIX, cursor: cursor });
    page.keys.forEach(function (k) { keys.push(k.name); });
    cursor = page.list_complete ? null : page.cursor;
  } while (cursor);

  const rows = [];
  for (const name of keys) {
    const v = await env.SCREEN_KV.get(name, "json");
    if (v && v.data) rows.push(v);
  }
  rows.sort(function (a, b) { return a.t < b.t ? 1 : -1; });

  // 使用人數：dev: 前綴每支手機一筆，list 帶 metadata，不用逐筆讀
  const devices = [];
  cursor = undefined;
  do {
    const page = await env.SCREEN_KV.list({ prefix: DEVICE_PREFIX, cursor: cursor });
    page.keys.forEach(function (k) { if (k.metadata) devices.push(k.metadata); });
    cursor = page.list_complete ? null : page.cursor;
  } while (cursor);
  devices.sort(function (a, b) { return a.last < b.last ? 1 : -1; });

  if (url.searchParams.get("format") === "json") return json({ devices: devices, screens: rows });

  const today = twDay();
  const daysAgo = function (day) { return Math.round((Date.parse(today) - Date.parse(day)) / 86400000); };
  const stat = function (list) {
    return {
      total: list.length,
      today: list.filter(function (x) { return daysAgo(x.lastDay) === 0; }).length,
      d7: list.filter(function (x) { return daysAgo(x.lastDay) < 7; }).length,
      d30: list.filter(function (x) { return daysAgo(x.lastDay) < 30; }).length,
      newToday: list.filter(function (x) { return twDay(new Date(x.first)) === today; }).length,
    };
  };
  const statRows = [["全部", devices]].concat(Object.keys(KNOWN_APPS).map(function (a) {
    return [KNOWN_APPS[a], devices.filter(function (x) { return x.app === a; })];
  })).map(function (p) {
    const st = stat(p[1]);
    return "<tr><td><b>" + esc(p[0]) + "</b></td><td>" + st.total + "</td><td>" + st.today + "</td><td>" + st.d7 + "</td><td>" + st.d30 + "</td><td>" + st.newToday + "</td></tr>";
  }).join("");
  const verCount = {};
  devices.forEach(function (x) { const k = (KNOWN_APPS[x.app] || x.app) + " " + (x.v || "?"); verCount[k] = (verCount[k] || 0) + 1; });
  const verText = Object.keys(verCount).sort().map(function (k) { return esc(k) + "：" + verCount[k] + " 支"; }).join("　") || "—";

  const fmtTime = function (iso) {
    try { return new Date(iso).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }); } catch (e) { return iso; }
  };
  const modeName = { app: "桌面App", web: "瀏覽器", file: "檔案" };
  const tr = rows.map(function (r) {
    const d = r.data || {};
    const s = d.screen || {}, ph = d.physical || {}, vp = d.viewport || {}, sa = d.safeArea || {}, lo = d.layout || {};
    const probs = Array.isArray(lo.problems) ? lo.problems : [];
    const bad = probs.length > 0;
    return "<tr" + (bad ? ' class="bad"' : "") + ">" +
      "<td>" + esc(fmtTime(r.t)) + "</td>" +
      "<td>" + esc(KNOWN_APPS[d.app] || d.app) + "<br><small>" + esc(d.v) + "</small></td>" +
      "<td>" + esc(modeName[d.mode] || d.mode) + "</td>" +
      "<td>" + esc(d.model || "-") + "<br><small>" + esc((d.platform || "") + " " + (d.platformVersion || "")) + "</small></td>" +
      "<td>" + esc(ph.w + "×" + ph.h) + "</td>" +
      "<td>" + esc(d.dpr) + "</td>" +
      "<td>" + esc(s.w + "×" + s.h) + "</td>" +
      "<td>" + esc(vp.docW + "×" + vp.h) + "</td>" +
      "<td>" + esc("上" + sa.t + " 下" + sa.b) + "</td>" +
      "<td>" + esc((lo.cellW || "-") + "×" + (lo.cellH || "-")) + "<br><small>字 " + esc(lo.fontPx || "-") + "px・縮放 " + esc(d.uiScale || "-") + "</small></td>" +
      "<td>" + (bad ? esc(probs.join("、")) : "正常") + "</td>" +
      "<td><small>" + esc(String(d.deviceId || "").slice(0, 8)) + "</small></td>" +
      "</tr>";
  }).join("");

  const devTr = devices.map(function (x) {
    return "<tr><td>" + esc(fmtTime(x.last)) + "</td><td>" + esc(KNOWN_APPS[x.app] || x.app) + "<br><small>" + esc(x.v) + "</small></td><td>" + esc(modeName[x.mode] || x.mode) + "</td><td>" + esc(x.model || "-") + "<br><small>" + esc(x.platform || "") + "</small></td><td>" + esc(fmtTime(x.first)) + "</td><td>" + esc(x.days) + "</td><td><small>" + esc(String(x.deviceId || "").slice(0, 8)) + "</small></td></tr>";
  }).join("");
  const html = '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    "<title>抓539 總表</title><style>" +
    "body{font-family:-apple-system,'Noto Sans TC','PingFang TC',sans-serif;margin:12px;background:#f4f4f4;color:#111}" +
    "h1{font-size:20px;margin:0 0 6px}p{margin:0 0 10px;color:#555;font-size:13px}" +
    ".wrap{overflow-x:auto;background:#fff;border:1px solid #ddd;border-radius:8px}" +
    "table{border-collapse:collapse;font-size:13px;min-width:1000px;width:100%}" +
    "th,td{border-bottom:1px solid #eee;padding:6px 8px;text-align:left;vertical-align:top;white-space:nowrap}" +
    "th{background:#fafafa;position:sticky;top:0}small{color:#777}tr.bad td{background:#fdecea}tr.bad td:nth-child(11){color:#c62828;font-weight:700}" +
    "h2{font-size:17px;margin:18px 0 6px}.stats{min-width:0;width:auto}.stats td,.stats th{text-align:right}.stats td:first-child,.stats th:first-child{text-align:left}" +
    "</style></head><body><h1>抓539／主程式 總表</h1><p>時間為台灣時間（今天 " + esc(today) + "）。人數＝手機支數：同一個人兩支手機算 2；清除瀏覽器資料、或 iPhone 上 Safari 與桌面 App 各算一支。</p>" +
    '<h2>使用人數</h2><div class="wrap"><table class="stats"><thead><tr><th>程式</th><th>總人數</th><th>今天</th><th>近 7 天</th><th>近 30 天</th><th>今天新加入</th></tr></thead><tbody>' + statRows + "</tbody></table></div>" +
    "<p style=\"margin-top:6px\">版本分布：" + verText + "</p>" +
    '<h2>每支手機</h2><div class="wrap"><table><thead><tr><th>最後使用</th><th>程式</th><th>開啟方式</th><th>型號</th><th>第一次使用</th><th>使用天數</th><th>裝置</th></tr></thead><tbody>' +
    (devTr || '<tr><td colspan="7">還沒有資料</td></tr>') + "</tbody></table></div>" +
    "<h2>螢幕資訊</h2><p>共 " + rows.length + " 筆（每支手機、每種開啟方式各留最新一筆）；紅底＝程式量到排版問題。</p>" +
    '<div class="wrap"><table><thead><tr><th>最後回傳</th><th>程式</th><th>開啟方式</th><th>型號</th><th>實體解析度</th><th>倍率</th><th>螢幕尺寸</th><th>可用畫面</th><th>安全距離</th><th>格子／字</th><th>排版檢查</th><th>裝置</th></tr></thead><tbody>' +
    (tr || '<tr><td colspan="12">還沒有資料</td></tr>') + "</tbody></table></div></body></html>";
  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}
