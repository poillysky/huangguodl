import type Artplayer from "artplayer";
import type Hls from "hls.js";
import { useEffect, useRef, useState } from "react";

type BufferHud = {
  /** 中央缓冲 HUD */
  show: boolean;
  label: string;
  /** 顶栏连播左侧常驻速度 */
  speed: string;
};

type BufferHooks = {
  onHud: (hud: BufferHud) => void;
};

function formatSpeed(bytesPerSec: number): string {
  if (!Number.isFinite(bytesPerSec) || bytesPerSec <= 0) return "";
  const kb = bytesPerSec / 1024;
  if (kb < 1024) return `${Math.max(1, Math.round(kb))} KB/s`;
  return `${(kb / 1024).toFixed(kb >= 10 ? 1 : 2)} MB/s`;
}

/** 从 hls LoaderStats / 分片耗时算出 B/s */
function bytesPerSecFromStats(stats: {
  total?: number;
  loaded?: number;
  bwEstimate?: number;
  loading?: { start?: number; first?: number; end?: number };
}): number {
  const loaded = Number(stats.loaded || stats.total || 0);
  const start = Number(stats.loading?.start || 0);
  const end = Number(stats.loading?.end || 0);
  const ms = end > start ? end - start : 0;
  if (loaded > 0 && ms > 0) return (loaded * 1000) / ms;
  // bwEstimate 是 bits/s
  const bw = Number(stats.bwEstimate || 0);
  if (bw > 0) return bw / 8;
  return 0;
}

export type ArtBizProps = {
  title: string;
  ep: number;
  total: number;
  autoNext: boolean;
  onBack: () => void;
  onToggleAutoNext: () => void;
  onSelectEp: (n: number) => void;
};

type Props = {
  url: string;
  poster?: string;
  biz: ArtBizProps;
  onEnded?: () => void;
  onError?: (message: string) => void;
  /** 视频真正开始出画（可播/播放）时回调，用于撤掉加载封面底 */
  onVideoReady?: () => void;
};

function syncBizChrome(art: Artplayer, biz: ArtBizProps) {
  const top = art.layers.hgTop as HTMLElement | undefined;
  if (top) {
    const name = top.querySelector(".hg-art-name");
    const epEl = top.querySelector(".hg-art-ep");
    const autoBtn = top.querySelector("[data-auto]");
    if (name) name.textContent = biz.title || "播放";
    if (epEl) epEl.textContent = epLabel(biz.ep, biz.total);
    if (autoBtn) {
      autoBtn.classList.toggle("on", biz.autoNext);
      autoBtn.setAttribute("aria-pressed", String(biz.autoNext));
      autoBtn.setAttribute("title", biz.autoNext ? "连播开" : "连播关");
    }
  }
  const panel = art.layers.hgEps as HTMLElement | undefined;
  if (panel) {
    panel.innerHTML = buildEpsHtml(biz.total, biz.ep);
  }
}

function syncTopSpeed(art: Artplayer | null, speed: string) {
  if (!art) return;
  const el = (art.layers.hgTop as HTMLElement | undefined)?.querySelector(
    "[data-speed]",
  );
  if (el) el.textContent = speed || "—";
}

/* 图标：24 网格、圆头描边；尺寸以 CSS 为准，此处给默认值兜底 */
const ICON_BACK = `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" d="M14.4 5.6 8 12l6.4 6.4"/></svg>`;
const ICON_GRID = `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.7"><rect x="4.2" y="4.2" width="6.2" height="6.2" rx="2"/><rect x="13.6" y="4.2" width="6.2" height="6.2" rx="2"/><rect x="4.2" y="13.6" width="6.2" height="6.2" rx="2"/><rect x="13.6" y="13.6" width="6.2" height="6.2" rx="2"/></g></svg>`;
const ICON_CLOSE = `<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" d="M7.6 7.6l8.8 8.8M16.4 7.6l-8.8 8.8"/></svg>`;
function esc(s: string) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function epLabel(ep: number, total: number) {
  return total ? `第 ${ep} 集 · 共 ${total} 集` : `第 ${ep} 集`;
}

function buildTopHtml(biz: ArtBizProps) {
  return `
    <div class="hg-art-top">
      <button type="button" class="hg-art-btn hg-art-back" aria-label="返回">${ICON_BACK}</button>
      <div class="hg-art-title">
        <div class="hg-art-name">${esc(biz.title || "播放")}</div>
        <div class="hg-art-ep">${esc(epLabel(biz.ep, biz.total))}</div>
      </div>
      <div class="hg-art-actions">
        <span class="hg-art-speed" data-speed aria-live="polite" title="下载速度">测算中…</span>
        <button type="button" class="hg-art-btn hg-art-auto${biz.autoNext ? " on" : ""}" data-auto aria-label="连播" aria-pressed="${biz.autoNext}" title="连播">连播</button>
        <button type="button" class="hg-art-btn hg-art-eps-btn" aria-label="选集">${ICON_GRID}</button>
      </div>
    </div>
  `;
}

function buildEpsHtml(total: number, current: number) {
  if (total < 2) return `<div class="hg-art-eps empty">暂无分集</div>`;
  const cells = Array.from({ length: total }, (_, i) => {
    const n = i + 1;
    const cur = n === current;
    return `<button type="button" class="hg-art-ep-cell${cur ? " current" : ""}" data-ep="${n}" aria-current="${cur}">${n}</button>`;
  }).join("");
  return `
    <div class="hg-art-eps">
      <div class="hg-art-eps-head">
        <span class="hg-art-eps-title">选集</span>
        <em>${current}/${total}</em>
        <button type="button" class="hg-art-btn hg-art-eps-close" data-eps-close aria-label="收起选集">${ICON_CLOSE}</button>
      </div>
      <div class="hg-art-eps-grid">${cells}</div>
    </div>
  `;
}

function wireNativeBufferHud(
  video: HTMLVideoElement,
  art: Artplayer,
  hooks: BufferHooks,
) {
  let lastSpeed = "";
  let waiting = true;
  let hasFrame = false;

  const paint = (label: string, forceShow?: boolean) => {
    const show = forceShow ?? (waiting || video.readyState < 3);
    try {
      art.loading.show = show && !hasFrame;
      const $player = art.template.$player;
      if (hasFrame) $player.classList.add("hg-has-frame");
      $player.classList.toggle("hg-buffering", Boolean(show && hasFrame));
      if (show && hasFrame) art.controls.show = true;
    } catch {
      /* ignore */
    }
    hooks.onHud({
      show,
      label: show ? label : "",
      speed: lastSpeed || (show ? "测算中…" : "—"),
    });
  };

  const onWaiting = () => {
    waiting = true;
    paint("缓冲中");
  };
  const onPlaying = () => {
    hasFrame = true;
    waiting = false;
    paint("", false);
  };
  const onCanPlay = () => {
    if (!video.paused) {
      hasFrame = true;
      waiting = false;
      paint("", false);
    } else if (!hasFrame) {
      paint("就绪");
    }
  };
  const onLoadedData = () => {
    hasFrame = true;
    try {
      art.template.$player.classList.add("hg-has-frame");
      art.loading.show = false;
    } catch {
      /* ignore */
    }
  };
  const onLoadStart = () => {
    waiting = true;
    paint("加载中");
  };

  video.addEventListener("waiting", onWaiting);
  video.addEventListener("playing", onPlaying);
  video.addEventListener("canplay", onCanPlay);
  video.addEventListener("loadeddata", onLoadedData);
  video.addEventListener("loadstart", onLoadStart);
  paint("加载中", true);

  return () => {
    video.removeEventListener("waiting", onWaiting);
    video.removeEventListener("playing", onPlaying);
    video.removeEventListener("canplay", onCanPlay);
    video.removeEventListener("loadeddata", onLoadedData);
    video.removeEventListener("loadstart", onLoadStart);
  };
}

function bindHls(
  video: HTMLVideoElement,
  src: string,
  art: Artplayer,
  HlsCtor: typeof Hls,
  hooks: BufferHooks,
  onFatal?: (msg: string) => void,
): Hls | null {
  if (HlsCtor.isSupported()) {
    const prev = (art as Artplayer & { hls?: Hls }).hls;
    if (prev) {
      prev.destroy();
    }
    // 加长前向缓冲 + 分片预取，减少卡顿；保留播放器内 loading HUD
    const hls = new HlsCtor({
      enableWorker: true,
      startFragPrefetch: true,
      maxBufferLength: 60,
      maxMaxBufferLength: 180,
      maxBufferSize: 80 * 1000 * 1000,
      backBufferLength: 30,
      abrEwmaDefaultEstimate: 1_500_000,
      abrBandWidthFactor: 0.9,
      abrBandWidthUpFactor: 0.7,
      maxStarvationDelay: 2,
      fragLoadingTimeOut: 20000,
      fragLoadingMaxRetry: 6,
      manifestLoadingMaxRetry: 3,
    });
    hls.loadSource(src);
    hls.attachMedia(video);
    (art as Artplayer & { hls?: Hls }).hls = hls;

    let lastBps = 0;
    let ewmaBps = 0;
    let buffering = true;
    let started = false;
    let hudLabel = "加载中";
    let inflight = 0;
    let fragStartedAt = 0;
    let speedTimer: ReturnType<typeof setInterval> | null = null;

    const noteBps = (bps: number) => {
      if (!Number.isFinite(bps) || bps <= 0) return;
      ewmaBps = ewmaBps > 0 ? ewmaBps * 0.55 + bps * 0.45 : bps;
      lastBps = ewmaBps;
    };

    const speedText = () => {
      if (lastBps > 0) return formatSpeed(lastBps);
      if (hls.bandwidthEstimate > 0) {
        return formatSpeed(hls.bandwidthEstimate / 8);
      }
      return "";
    };

    const emitHud = (show: boolean) => {
      const spd = speedText();
      hooks.onHud({
        show,
        label: show ? hudLabel : "",
        // 顶栏常驻：有样本用实测，加载中用测算中，否则占位
        speed: spd || (show || !started ? "测算中…" : "—"),
      });
    };

    const paint = (label: string, forceShow?: boolean) => {
      if (label) hudLabel = label;
      const show = forceShow ?? (buffering || !started);
      try {
        // 仅「尚未出画」时用 Art 官方 loading（会盖海报）。
        art.loading.show = show && !started;
        const $player = art.template.$player;
        if (started) $player.classList.add("hg-has-frame");
        $player.classList.toggle("hg-buffering", Boolean(show && started));
        if (show && started) art.controls.show = true;
      } catch {
        /* ignore */
      }
      emitHud(show);
      if (show) {
        try {
          art.emit("video:progress");
        } catch {
          /* ignore */
        }
      }
    };

    // 顶栏速度常驻：持续采样 bandwidthEstimate
    speedTimer = setInterval(() => {
      if (hls.bandwidthEstimate > 0) {
        noteBps(hls.bandwidthEstimate / 8);
      }
      emitHud(buffering || !started);
    }, 500);

    hls.on(HlsCtor.Events.MANIFEST_PARSED, () => {
      paint("缓冲中", true);
      void video.play().catch(() => {
        /* 浏览器拦截自动播放时，点一下即可 */
      });
    });

    hls.on(HlsCtor.Events.FRAG_LOADING, () => {
      inflight += 1;
      fragStartedAt = performance.now();
      if (buffering || !started) paint(started ? "缓冲中" : "加载中");
      else emitHud(false);
    });

    hls.on(HlsCtor.Events.FRAG_LOADED, (_evt, data) => {
      const bytes = data.payload?.byteLength || 0;
      const elapsed = fragStartedAt > 0 ? performance.now() - fragStartedAt : 0;
      if (bytes > 0 && elapsed > 0) noteBps((bytes * 1000) / elapsed);
      const fragStats = data.frag?.stats;
      if (fragStats) noteBps(bytesPerSecFromStats(fragStats));
      if (hls.bandwidthEstimate > 0) noteBps(hls.bandwidthEstimate / 8);
      inflight = Math.max(0, inflight - 1);
      if (buffering || !started) {
        paint(started ? "缓冲中" : "加载中");
      } else {
        emitHud(false);
      }
    });

    hls.on(HlsCtor.Events.FRAG_BUFFERED, (_evt, data) => {
      if (data.stats) noteBps(bytesPerSecFromStats(data.stats));
      if (!started) paint("即将播放", true);
      else if (inflight > 0) emitHud(false);
    });

    hls.on(HlsCtor.Events.LEVEL_LOADED, (_evt, data) => {
      if (data.stats) noteBps(bytesPerSecFromStats(data.stats));
      if (buffering || !started) paint(hudLabel || "加载中");
    });

    const onWaiting = () => {
      // 卡顿：停在当前帧缓冲，不换海报、不跳进度
      buffering = true;
      paint("缓冲中", true);
    };
    const onPlaying = () => {
      started = true;
      buffering = false;
      try {
        art.template.$player.classList.add("hg-has-frame");
      } catch {
        /* ignore */
      }
      paint("", false);
    };
    const onCanPlay = () => {
      if (!video.paused && !video.ended) {
        started = true;
        buffering = false;
        paint("", false);
      }
    };
    // 首帧出来即标记，后续缓冲不再盖封面
    const onLoadedData = () => {
      started = true;
      try {
        art.template.$player.classList.add("hg-has-frame");
        art.loading.show = false;
      } catch {
        /* ignore */
      }
    };

    video.addEventListener("waiting", onWaiting);
    video.addEventListener("stalled", onWaiting);
    video.addEventListener("playing", onPlaying);
    video.addEventListener("canplay", onCanPlay);
    video.addEventListener("loadeddata", onLoadedData);
    paint("加载中", true);

    hls.on(HlsCtor.Events.ERROR, (_evt, data) => {
      if (!data.fatal) {
        if (started) paint("缓冲中", true);
        return;
      }
      if (data.type === HlsCtor.ErrorTypes.NETWORK_ERROR) {
        paint(started ? "缓冲中" : "网络重试中", true);
        hls.startLoad();
      } else if (data.type === HlsCtor.ErrorTypes.MEDIA_ERROR) {
        paint(started ? "缓冲中" : "恢复中", true);
        hls.recoverMediaError();
      } else {
        const msg = "播放失败，请重试";
        art.notice.show = msg;
        onFatal?.(msg);
        if (speedTimer) {
          clearInterval(speedTimer);
          speedTimer = null;
        }
        hooks.onHud({ show: false, label: "", speed: "—" });
      }
    });

    art.on("destroy", () => {
      if (speedTimer) {
        clearInterval(speedTimer);
        speedTimer = null;
      }
      video.removeEventListener("waiting", onWaiting);
      video.removeEventListener("stalled", onWaiting);
      video.removeEventListener("playing", onPlaying);
      video.removeEventListener("canplay", onCanPlay);
      video.removeEventListener("loadeddata", onLoadedData);
      hls.destroy();
      (art as Artplayer & { hls?: Hls }).hls = undefined;
    });
    return hls;
  }

  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    const unwire = wireNativeBufferHud(video, art, hooks);
    video.src = src;
    void video.play().catch(() => {});
    art.on("destroy", unwire);
    return null;
  }

  const msg = "当前浏览器不支持 HLS 播放";
  art.notice.show = msg;
  onFatal?.(msg);
  return null;
}

/**
 * ArtPlayer + hls.js（动态 import，不进首屏包）；业务栏用官方 layers。
 */
export default function ArtHlsPlayer({
  url,
  poster,
  biz,
  onEnded,
  onError,
  onVideoReady,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const artRef = useRef<Artplayer | null>(null);
  const bizRef = useRef(biz);
  const onEndedRef = useRef(onEnded);
  const onErrorRef = useRef(onError);
  const onVideoReadyRef = useRef(onVideoReady);
  bizRef.current = biz;
  onEndedRef.current = onEnded;
  onErrorRef.current = onError;
  onVideoReadyRef.current = onVideoReady;
  const epsOpenRef = useRef(false);
  const videoReadySent = useRef(false);
  const [bufHud, setBufHud] = useState<BufferHud>({
    show: true,
    label: "加载中",
    speed: "测算中…",
  });
  const hudRef = useRef(setBufHud);
  hudRef.current = setBufHud;

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !url) return;
    let cancelled = false;
    let art: Artplayer | null = null;
    videoReadySent.current = false;
    setBufHud({ show: true, label: "加载中", speed: "测算中…" });

    const epsOpen = { current: false };
    const emitVideoReady = () => {
      if (videoReadySent.current) return;
      videoReadySent.current = true;
      onVideoReadyRef.current?.();
    };
    const bufferHooks: BufferHooks = {
      onHud: (hud) => {
        if (cancelled) return;
        hudRef.current(hud);
        syncTopSpeed(artRef.current || art, hud.speed);
      },
    };

    void (async () => {
      const [{ default: ArtplayerCtor }, { default: HlsCtor }] =
        await Promise.all([import("artplayer"), import("hls.js")]);
      if (cancelled || !containerRef.current) return;

      const setEpsOpen = (inst: Artplayer, open: boolean) => {
        epsOpen.current = open;
        epsOpenRef.current = open;
        const panel = inst.layers.hgEps as HTMLElement | undefined;
        if (!panel) return;
        panel.classList.toggle("is-open", open);
        if (!open) return;
        inst.controls.show = true;
        const cur = panel.querySelector<HTMLElement>(".hg-art-ep-cell.current");
        if (cur) {
          requestAnimationFrame(() => {
            cur.scrollIntoView({ block: "nearest", inline: "nearest" });
          });
        }
      };

      const wireTop = (inst: Artplayer, layerEl: HTMLElement) => {
        layerEl.style.pointerEvents = "none";
        const top = layerEl.querySelector(".hg-art-top") as HTMLElement | null;
        if (top) top.style.pointerEvents = "auto";

        layerEl.querySelector(".hg-art-back")?.addEventListener("click", (e) => {
          e.stopPropagation();
          bizRef.current.onBack();
        });
        layerEl.querySelector("[data-auto]")?.addEventListener("click", (e) => {
          e.stopPropagation();
          bizRef.current.onToggleAutoNext();
        });
        layerEl
          .querySelector(".hg-art-eps-btn")
          ?.addEventListener("click", (e) => {
            e.stopPropagation();
            setEpsOpen(inst, !epsOpen.current);
          });
      };

      const wireEps = (inst: Artplayer, layerEl: HTMLElement) => {
        layerEl.addEventListener("click", (e) => {
          const t = e.target as HTMLElement | null;
          if (t?.closest?.("[data-eps-close]")) {
            e.stopPropagation();
            setEpsOpen(inst, false);
            return;
          }
          const btn = t?.closest?.("[data-ep]") as HTMLElement | null;
          if (!btn) return;
          e.stopPropagation();
          const n = Number(btn.getAttribute("data-ep"));
          if (!Number.isFinite(n)) return;
          setEpsOpen(inst, false);
          bizRef.current.onSelectEp(n);
        });
      };

      // 默认 35px 行高 + 内联 style，文字/图标会显得偏下且被裁；与 CSS 行高对齐
      ArtplayerCtor.SETTING_ITEM_HEIGHT = 40;

      art = new ArtplayerCtor({
        container: el,
        url,
        type: "m3u8",
        poster: poster || "",
        theme: "#f5f1ea",
        lang: "zh-cn",
        autoplay: true,
        volume: 0.85,
        autoSize: false,
        autoMini: false,
        playbackRate: true,
        aspectRatio: false,
        setting: true,
        fullscreen: true,
        fullscreenWeb: true,
        pip: false,
        mutex: true,
        backdrop: true,
        playsInline: true,
        lock: true,
        fastForward: true,
        autoOrientation: true,
        moreVideoAttr: {
          playsInline: true,
        },
        layers: [
          {
            name: "hgTop",
            html: buildTopHtml(bizRef.current),
            style: {
              position: "absolute",
              left: "0",
              top: "0",
              right: "0",
              width: "100%",
              height: "auto",
              zIndex: "60",
              pointerEvents: "none",
            },
            mounted(layerEl) {
              wireTop(this, layerEl);
            },
          },
          {
            name: "hgEps",
            html: buildEpsHtml(bizRef.current.total, bizRef.current.ep),
            style: {
              position: "absolute",
              top: "calc(var(--hg-safe-top, 10px) + var(--hg-bar-h, 48px) + 6px)",
              right: "var(--p-safe-right, 12px)",
              width: "min(320px, calc(100% - 24px))",
              zIndex: "70",
              pointerEvents: "auto",
            },
            mounted(layerEl) {
              wireEps(this, layerEl);
            },
          },
        ],
        customType: {
          m3u8(video, src, instance) {
            bindHls(
              video as HTMLVideoElement,
              src,
              instance,
              HlsCtor,
              bufferHooks,
              (msg) => onErrorRef.current?.(msg),
            );
          },
        },
      });

      if (cancelled) {
        art.destroy(false);
        return;
      }

      art.on("control", (state) => {
        const on = Boolean(state);
        if (art && art.layers.show !== on) {
          art.layers.show = on;
        }
        if (!on && epsOpen.current && art) {
          setEpsOpen(art, false);
        }
      });

      art.on("ready", () => {
        if (art) {
          art.layers.show = art.controls.show;
          // 异步创建完成后，用最新 biz 刷一次顶栏/选集（防连播竞态）
          syncBizChrome(art, bizRef.current);
        }
      });

      art.on("video:canplay", emitVideoReady);
      art.on("video:playing", emitVideoReady);

      art.on("video:ended", () => {
        onEndedRef.current?.();
      });

      art.on("error", () => {
        onErrorRef.current?.("播放失败，请重试");
      });

      artRef.current = art;
      syncBizChrome(art, bizRef.current);
    })();

    return () => {
      cancelled = true;
      epsOpen.current = false;
      epsOpenRef.current = false;
      const inst = artRef.current || art;
      if (inst) {
        const hls = (inst as Artplayer & { hls?: Hls }).hls;
        hls?.destroy();
        inst.destroy(false);
      }
      artRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  useEffect(() => {
    const art = artRef.current;
    if (!art) return;
    syncBizChrome(art, biz);
  }, [biz.title, biz.ep, biz.total, biz.autoNext]);

  useEffect(() => {
    syncTopSpeed(artRef.current, bufHud.speed);
  }, [bufHud.speed]);

  return (
    <div className="art-hls-player">
      <div ref={containerRef} className="art-hls-player-stage" />
      <div
        className={`hg-buffer-hud${bufHud.show ? " show" : ""}`}
        aria-live="polite"
        aria-hidden={!bufHud.show}
      >
        <span className="hg-buffer-spin" aria-hidden />
        <span className="hg-buffer-label">{bufHud.label || "加载中"}</span>
      </div>
    </div>
  );
}
