/** Detect iOS / standalone (added to Home Screen) and register SW. */

export function isIos(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent;
  const iOS = /iPad|iPhone|iPod/.test(ua);
  const iPadOs = navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
  return iOS || iPadOs;
}

export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const mq = window.matchMedia("(display-mode: standalone), (display-mode: fullscreen)");
    if (mq.matches) return true;
  } catch {
    /* ignore */
  }
  const iosStandalone = (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return iosStandalone;
}

export function applyStandaloneClass(): void {
  const root = document.documentElement;
  if (isStandalone()) root.classList.add("standalone");
  else root.classList.remove("standalone");
  if (isIos()) root.classList.add("ios");
  // 状态栏用 black + theme-color=#16151a，与顶栏同色；不再删 theme-color
  syncSafeTop();
  syncAppHeight();
}

function probeSafeInset(edge: "top" | "bottom"): number {
  if (typeof document === "undefined") return 0;
  const probe = document.createElement("div");
  const prop =
    edge === "top" ? "safe-area-inset-top" : "safe-area-inset-bottom";
  probe.style.cssText =
    `position:fixed;left:0;width:0;visibility:hidden;pointer-events:none;` +
    (edge === "top" ? "top:0;" : "bottom:0;") +
    `height:constant(${prop});height:env(${prop},0px);`;
  document.documentElement.appendChild(probe);
  const h = probe.getBoundingClientRect().height || 0;
  probe.remove();
  return h;
}

/**
 * 锁定 --safe-top。
 * iOS 主屏幕 + status-bar-style=black：系统已预留状态栏，必须为 0，
 * 否则会与系统栏叠出「刘海一层 + 顶栏一层」（见 Red Eye / Progressier）。
 */
export function syncSafeTop(): void {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  const root = document.documentElement;
  if (isStandalone() && isIos()) {
    root.style.setProperty("--safe-top", "0px");
    return;
  }
  const sat = probeSafeInset("top");
  root.style.setProperty("--safe-top", `${Math.round(sat)}px`);
}

/** Measure bottom safe-area and set --app-height so the shell reaches the physical bottom. */
export function syncAppHeight(): void {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  const root = document.documentElement;
  if (!isStandalone()) {
    root.style.setProperty("--app-height", `${window.innerHeight}px`);
    syncSafeTop();
    return;
  }
  const sab = probeSafeInset("bottom");
  // innerHeight is the short viewport on buggy iOS; add sab to reach physical bottom
  root.style.setProperty("--app-height", `${Math.round(window.innerHeight + sab)}px`);
  syncSafeTop();
}

export function watchAppHeight(): void {
  const onResize = () => {
    syncSafeTop();
    syncAppHeight();
  };
  window.addEventListener("resize", onResize);
  window.visualViewport?.addEventListener("resize", onResize);
  window.visualViewport?.addEventListener("scroll", onResize);
  syncSafeTop();
  syncAppHeight();
}

/** Safari <14 has no MediaQueryList.addEventListener — must use addListener. */
export function watchStandalone(): void {
  if (typeof window === "undefined" || !window.matchMedia) return;
  try {
    const mq = window.matchMedia(
      "(display-mode: standalone), (display-mode: fullscreen)",
    );
    const onChange = () => applyStandaloneClass();
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", onChange);
    } else if (typeof mq.addListener === "function") {
      mq.addListener(onChange);
    }
  } catch {
    /* ignore */
  }
}

export function registerServiceWorker(): void {
  if (!("serviceWorker" in navigator)) return;
  // Dev: drop any leftover SW — stale cache → 主屏幕白屏
  if (import.meta.env.DEV) {
    void navigator.serviceWorker.getRegistrations().then((regs) => {
      regs.forEach((r) => void r.unregister());
    });
    if (typeof caches !== "undefined") {
      void caches.keys().then((keys) => keys.forEach((k) => void caches.delete(k)));
    }
    return;
  }
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").catch(() => {
      /* ignore */
    });
  });
}
