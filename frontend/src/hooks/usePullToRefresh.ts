import { RefObject, useEffect, useRef, useState } from "react";

const THRESHOLD = 68;
const MAX_PULL = 120;

type Options = {
  enabled?: boolean;
  onRefresh: () => void | Promise<void>;
  /** Indicator + body moved via transform (no React re-render while dragging) */
  ptrRef: RefObject<HTMLElement | null>;
  bodyRef: RefObject<HTMLElement | null>;
};

function damp(dy: number) {
  // rubber-band: strong at first, soft near max
  const x = Math.max(0, dy);
  return Math.min(MAX_PULL, x * 0.5);
}

/** Pull-to-refresh: DOM transforms only while dragging for 60fps feel. */
export function usePullToRefresh(
  scrollerRef: RefObject<HTMLElement | null>,
  { enabled = true, onRefresh, ptrRef, bodyRef }: Options,
) {
  const [refreshing, setRefreshing] = useState(false);
  const startX = useRef(0);
  const startY = useRef(0);
  /** none until gesture clarifies; x = horizontal scroll wins, ignore PTR */
  const axis = useRef<"none" | "x" | "y">("none");
  const pulling = useRef(false);
  const armed = useRef(false);
  const pull = useRef(0);
  const refreshingRef = useRef(false);
  const onRefreshRef = useRef(onRefresh);
  const raf = useRef(0);
  onRefreshRef.current = onRefresh;

  useEffect(() => {
    refreshingRef.current = refreshing;
  }, [refreshing]);

  useEffect(() => {
    const el = scrollerRef.current;
    const ptr = ptrRef.current;
    const body = bodyRef.current;
    if (!el || !ptr || !body || !enabled) return;

    const textEl = ptr.querySelector(".ptr-text");
    const spinEl = ptr.querySelector(".ptr-spin");

    const paint = (dist: number, opts?: { animate?: boolean }) => {
      pull.current = dist;
      const animate = Boolean(opts?.animate);
      const ease = animate ? "transform 0.22s ease-out" : "none";
      body.style.transition = ease;
      ptr.style.transition = ease;
      // 仅下拉时写 transform；闲时清空，避免 sticky 被包含块带跑
      if (dist) {
        body.style.willChange = "transform";
        body.style.transform = `translate3d(0,${dist}px,0)`;
      } else {
        body.style.transform = "";
        body.style.willChange = "";
      }
      // indicator sits just above content; slides in with pull
      ptr.style.transform = `translate3d(0,${dist - THRESHOLD}px,0)`;
      ptr.style.opacity = dist > 2 || refreshingRef.current ? "1" : "0";
      const isArmed = dist >= THRESHOLD || refreshingRef.current;
      ptr.classList.toggle("armed", isArmed);
      ptr.classList.toggle("refreshing", refreshingRef.current);
      spinEl?.classList.toggle("on", isArmed);
      if (textEl) {
        textEl.textContent = refreshingRef.current
          ? "刷新中…"
          : isArmed
            ? "松开刷新"
            : "下拉刷新";
      }
    };

    const schedulePaint = (dist: number) => {
      cancelAnimationFrame(raf.current);
      raf.current = requestAnimationFrame(() => paint(dist));
    };

    const onStart = (e: TouchEvent) => {
      if (refreshingRef.current) return;
      if (el.scrollTop > 1) {
        pulling.current = false;
        return;
      }
      const target = e.target as Element | null;
      // 题材两行横滑区：手势留给横向滚动，不进下拉刷新
      if (target?.closest?.(".chips-scroll-2, [data-no-ptr]")) {
        pulling.current = false;
        return;
      }
      const t = e.touches[0];
      startX.current = t?.clientX ?? 0;
      startY.current = t?.clientY ?? 0;
      axis.current = "none";
      pulling.current = true;
      armed.current = false;
      body.style.transition = "none";
      ptr.style.transition = "none";
    };

    const onMove = (e: TouchEvent) => {
      if (!pulling.current || refreshingRef.current) return;
      if (el.scrollTop > 1) {
        pulling.current = false;
        schedulePaint(0);
        return;
      }
      const t = e.touches[0];
      const x = t?.clientX ?? 0;
      const y = t?.clientY ?? 0;
      const dx = x - startX.current;
      const dy = y - startY.current;

      // 横滑题材芯片时勿当成下拉刷新
      if (axis.current === "none") {
        if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
        axis.current = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
        if (axis.current === "x") {
          pulling.current = false;
          armed.current = false;
          schedulePaint(0);
          return;
        }
      } else if (axis.current === "x") {
        return;
      }

      if (dy <= 0) {
        armed.current = false;
        schedulePaint(0);
        return;
      }
      const dist = damp(dy);
      armed.current = dist >= THRESHOLD;
      if (dist > 6) e.preventDefault();
      schedulePaint(dist);
    };

    const finishPull = (dist: number) => {
      paint(dist, { animate: true });
    };

    const runRefresh = async () => {
      if (refreshingRef.current) return;
      refreshingRef.current = true;
      setRefreshing(true);
      finishPull(THRESHOLD);
      try {
        await onRefreshRef.current();
      } finally {
        refreshingRef.current = false;
        setRefreshing(false);
        finishPull(0);
        // clear will-change hints after settle
        window.setTimeout(() => {
          body.style.transition = "";
          ptr.style.transition = "";
          body.style.transform = "";
          body.style.willChange = "";
          ptr.style.transform = `translate3d(0,-${THRESHOLD}px,0)`;
        }, 240);
      }
    };

    const onEnd = () => {
      if (!pulling.current) {
        axis.current = "none";
        return;
      }
      pulling.current = false;
      const wasArmed = armed.current && axis.current === "y";
      armed.current = false;
      axis.current = "none";
      if (wasArmed && !refreshingRef.current) {
        void runRefresh();
      } else if (!refreshingRef.current) {
        finishPull(0);
      }
    };

    // initial hidden position
    ptr.style.transform = `translate3d(0,-${THRESHOLD}px,0)`;
    ptr.style.opacity = "0";

    el.addEventListener("touchstart", onStart, { passive: true });
    el.addEventListener("touchmove", onMove, { passive: false });
    el.addEventListener("touchend", onEnd);
    el.addEventListener("touchcancel", onEnd);
    return () => {
      cancelAnimationFrame(raf.current);
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", onEnd);
      el.removeEventListener("touchcancel", onEnd);
    };
  }, [scrollerRef, ptrRef, bodyRef, enabled]);

  return { refreshing };
}
