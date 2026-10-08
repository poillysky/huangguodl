/* Service worker — shell only; never cache API / media / hashed assets aggressively. */
const CACHE = "hg-dl-shell-v3";
const PRECACHE = [
  "/",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))),
      )
      .then(() => self.clients.claim()),
  );
});

function isShellPath(pathname) {
  return (
    pathname === "/" ||
    pathname === "/manifest.webmanifest" ||
    pathname.startsWith("/icons/")
  );
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // API / HLS 代理 / 媒体：一律网络，不进 Cache
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/hls/") ||
    url.pathname.startsWith("/media/")
  ) {
    return;
  }

  // Vite 带 hash 的 JS/CSS：网络优先，失败才回退（不写入 Cache，避免旧包残留）
  if (
    url.pathname.startsWith("/assets/") ||
    url.pathname.endsWith(".js") ||
    url.pathname.endsWith(".css")
  ) {
    event.respondWith(fetch(req).catch(() => caches.match("/")));
    return;
  }

  // 导航导航与壳资源：网络优先，成功再更新 shell cache
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok && isShellPath(url.pathname)) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() =>
        caches.match(req).then((hit) => hit || caches.match("/")),
      ),
  );
});
