/* 抓539 service worker(2026-09-23)
   目的：讓 Chrome 比較容易判定「可以安裝」而主動跳出安裝提示；順便在沒有網路時還能打開上次看過的畫面。
   規則：
   ・只管同一個網站自己的檔案(index.html、manifest.json、圖示)。雲端開獎資料(Worker)、其他網站的檔案一律不碰，照原本方式連線。
   ・網路優先：有網路就一定拿最新版(上傳新的 index.html 後重新打開就是新版)，順便存一份；沒網路才拿存下來的那份。 */
const CACHE = "zhua539-v1";

self.addEventListener("install", function (e) {
  e.waitUntil(
    caches.open(CACHE)
      .then(function (c) { return c.addAll(["./", "./index.html", "./manifest.json"]).catch(function () {}); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys()
      .then(function (keys) { return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); })); })
      .then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (e) {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; /* 雲端資料、CDN 等外部連線不攔 */
  e.respondWith(
    fetch(req)
      .then(function (res) {
        if (res && res.ok) { const copy = res.clone(); caches.open(CACHE).then(function (c) { c.put(req, copy); }); }
        return res;
      })
      .catch(function () {
        return caches.match(req).then(function (hit) {
          if (hit) return hit;
          if (req.mode === "navigate") return caches.match("./index.html").then(function (h) { return h || caches.match("./"); });
          return Response.error();
        });
      })
  );
});
