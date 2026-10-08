import { useCallback, useEffect, useState } from "react";
import { api, Show } from "../api/client";

/** 单部剧收藏状态（详情页用） */
export function useFavorite(id: string, seed?: Partial<Show> | null) {
  const [favorited, setFavorited] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    void api
      .favoriteStatus(id)
      .then((r) => {
        if (!cancelled) setFavorited(Boolean(r.favorited));
      })
      .catch(() => {
        if (!cancelled) setFavorited(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const toggle = useCallback(
    async (snap?: Partial<Show>) => {
      if (!id || busy) return;
      setBusy(true);
      const next = !favorited;
      setFavorited(next); // 乐观更新
      try {
        if (next) {
          const s = { ...seed, ...snap };
          await api.addFavorite({
            id,
            title: String(s.title || id),
            cover: String(s.cover || ""),
            total: Number(s.total) || 0,
            finished: Boolean(s.finished),
            label: String(s.label || ""),
            tags: Array.isArray(s.tags) ? s.tags : [],
            hot: Number(s.hot) || 0,
          });
        } else {
          await api.removeFavorite(id);
        }
      } catch {
        setFavorited(!next);
      } finally {
        setBusy(false);
      }
    },
    [id, busy, favorited, seed],
  );

  return { favorited, busy, toggle };
}
