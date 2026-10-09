import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/** 底栏主页，左右滑切换 */
export const TAB_PATHS = ["/huangguo", "/huangdou", "/yeguo", "/me"] as const;

const IGNORE =
  ".chips-scroll, .chips-scroll-2, .poster-rail, .ep-grid, [data-no-tab-swipe], input, textarea, select";

/**
 * 底栏主 Tab（黄果 / 黄豆 / 野果 / 我的）左右滑切换。
 * 详情、播放、收藏、下载页不启用；横滑列表区域忽略。
 */
export function useTabSwipe(enabled = true) {
  const loc = useLocation();
  const nav = useNavigate();
  const idx = TAB_PATHS.indexOf(loc.pathname as (typeof TAB_PATHS)[number]);
  const idxRef = useRef(idx);
  idxRef.current = idx;

  useEffect(() => {
    if (!enabled || idx < 0) return;

    let startX = 0;
    let startY = 0;
    let axis: "none" | "x" | "y" | "skip" = "none";

    const onStart = (e: TouchEvent) => {
      const target = e.target as Element | null;
      if (target?.closest?.(IGNORE)) {
        axis = "skip";
        return;
      }
      const t = e.touches[0];
      startX = t?.clientX ?? 0;
      startY = t?.clientY ?? 0;
      axis = "none";
    };

    const onMove = (e: TouchEvent) => {
      if (axis === "skip" || axis === "x" || axis === "y") return;
      const t = e.touches[0];
      if (!t) return;
      const dx = t.clientX - startX;
      const dy = t.clientY - startY;
      if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
      axis = Math.abs(dx) > Math.abs(dy) * 1.15 ? "x" : "y";
    };

    const onEnd = (e: TouchEvent) => {
      if (axis === "skip" || axis === "y") {
        axis = "none";
        return;
      }
      const t = e.changedTouches[0];
      if (!t) {
        axis = "none";
        return;
      }
      const dx = t.clientX - startX;
      const dy = t.clientY - startY;
      axis = "none";
      if (Math.abs(dx) < 64) return;
      if (Math.abs(dx) < Math.abs(dy) * 1.2) return;
      const i = idxRef.current;
      if (i < 0) return;
      if (dx < 0 && i < TAB_PATHS.length - 1) {
        nav(TAB_PATHS[i + 1]);
      } else if (dx > 0 && i > 0) {
        nav(TAB_PATHS[i - 1]);
      }
    };

    const root = document.querySelector(".app-shell");
    if (!root) return;
    const start = onStart as EventListener;
    const move = onMove as EventListener;
    const end = onEnd as EventListener;
    root.addEventListener("touchstart", start, { passive: true });
    root.addEventListener("touchmove", move, { passive: true });
    root.addEventListener("touchend", end);
    root.addEventListener("touchcancel", end);
    return () => {
      root.removeEventListener("touchstart", start);
      root.removeEventListener("touchmove", move);
      root.removeEventListener("touchend", end);
      root.removeEventListener("touchcancel", end);
    };
  }, [enabled, idx, nav]);
}
