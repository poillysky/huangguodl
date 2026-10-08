import { useCallback, useEffect, useRef, useState } from "react";
import { api, Show } from "../api/client";

type Mode =
  | { type: "catalog"; category: string; sort?: "hot" | "new" }
  | { type: "search"; keyword: string };

function mergeUnique(prev: Show[], next: Show[]) {
  const seen = new Set(prev.map((s) => s.id));
  const out = [...prev];
  for (const s of next) {
    if (seen.has(s.id)) continue;
    seen.add(s.id);
    out.push(s);
  }
  return out;
}

export function useInfiniteCatalog(mode: Mode, pageSize = 20) {
  const [items, setItems] = useState<Show[]>([]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState("");
  const [reloadId, setReloadId] = useState(0);
  const lock = useRef(false);
  const refreshWaiters = useRef<Array<() => void>>([]);
  const modeKey =
    mode.type === "search"
      ? `search:${mode.keyword}`
      : `cat:${mode.category}:${mode.sort || ""}`;

  const resetKey = useRef(modeKey);
  // 切换分类/关键词时置位：用于丢弃"仍持有旧 page"的那一轮请求
  const justReset = useRef(false);
  // 每次切换/刷新自增，用于废弃所有在途请求
  const gen = useRef(0);

  useEffect(() => {
    if (resetKey.current === modeKey) return;
    resetKey.current = modeKey;
    gen.current += 1;
    justReset.current = true;
    setItems([]);
    setPage(1);
    setHasMore(true);
    setError("");
    setLoading(true);
    lock.current = false;
  }, [modeKey]);

  useEffect(() => {
    // 本 effect 与上面的重置 effect 在同一次提交里按声明顺序执行，但闭包里的
    // `page` 还是旧值。若此时按旧页码去请求新分类，会多跑一次请求、并把结果
    // 塞进列表（resetKey 已更新，旧的 modeKey 校验拦不住）。这里直接跳过这一轮，
    // 等 setPage(1) 触发的那一轮再发请求。
    if (justReset.current) {
      if (page !== 1) return;
      justReset.current = false;
    }
    const genAtStart = gen.current;
    let cancelled = false;
    const isFirst = page === 1;
    if (isFirst) setLoading(true);
    else setLoadingMore(true);
    setError("");
    lock.current = true;

    const req =
      mode.type === "search"
        ? api.search(mode.keyword, page)
        : api.catalog(mode.category, page, pageSize, mode.sort);

    const stale = () =>
      cancelled || genAtStart !== gen.current || resetKey.current !== modeKey;

    req
      .then((r) => {
        if (stale()) return;
        const batch = r.items || [];
        setItems((prev) => (page === 1 ? batch : mergeUnique(prev, batch)));
        setHasMore(batch.length >= pageSize);
      })
      .catch((e: Error) => {
        if (!stale()) setError(e.message);
      })
      .finally(() => {
        if (stale()) return;
        setLoading(false);
        setLoadingMore(false);
        lock.current = false;
        const waiters = refreshWaiters.current.splice(0);
        waiters.forEach((w) => w());
      });

    return () => {
      cancelled = true;
    };
    // mode fields covered by modeKey
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modeKey, page, pageSize, reloadId]);

  const loadMore = useCallback(() => {
    if (lock.current || loading || loadingMore || !hasMore || error) return;
    setPage((p) => p + 1);
  }, [loading, loadingMore, hasMore, error]);

  /** Pull-to-refresh / reconnect: reload first page and clear error. */
  const refresh = useCallback(() => {
    return new Promise<void>((resolve) => {
      refreshWaiters.current.push(resolve);
      setItems([]);
      setHasMore(true);
      setError("");
      setLoading(true);
      lock.current = false;
      setPage(1);
      setReloadId((n) => n + 1);
    });
  }, []);

  return {
    items,
    loading,
    loadingMore,
    hasMore,
    error,
    loadMore,
    refresh,
  };
}

export function useLoadMoreSentinel(
  onLoadMore: () => void,
  enabled: boolean,
) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !enabled) return;
    const root = el.closest(".page-scroll") as Element | null;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) onLoadMore();
      },
      { root, rootMargin: "240px 0px", threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [onLoadMore, enabled]);

  return ref;
}
