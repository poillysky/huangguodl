import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Show } from "../api/client";
import PageLoading from "../components/PageLoading";
import PageShell from "../components/PageShell";
import ShowGrid from "../components/ShowGrid";

export default function FavoritesPage() {
  const nav = useNavigate();
  const [items, setItems] = useState<Show[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    setLoading(true);
    setError("");
    return api
      .favorites()
      .then((r) => {
        setItems(r.items || []);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const empty = !loading && !error && items.length === 0;

  return (
    <PageShell title="收藏" onRefresh={refresh}>
      {error ? (
        <div className="fav-banner err" role="alert">
          <p>{error}</p>
          <button
            type="button"
            className="btn ghost"
            onClick={() => nav("/settings")}
          >
            去配置
          </button>
        </div>
      ) : null}

      {empty ? (
        <div className="fav-empty-state">
          <div className="fav-empty-glow" aria-hidden />
          <div className="fav-empty-icon" aria-hidden>
            <svg viewBox="0 0 24 24" width="36" height="36">
              <path
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinejoin="round"
                d="M12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"
              />
            </svg>
          </div>
          <h2 className="fav-empty-title">还没有收藏</h2>
          <p className="fav-empty-desc">
            打开一部剧，在详情页点「收藏」，之后会集中出现在这里。
          </p>
          <button
            type="button"
            className="btn fav-empty-cta"
            onClick={() => nav("/browse")}
          >
            去分类看看
          </button>
        </div>
      ) : null}

      {items.length > 0 ? (
        <>
          <div className="fav-toolbar">
            <span className="fav-count">
              已收藏 <em>{items.length}</em> 部
            </span>
          </div>
          <ShowGrid items={items} />
        </>
      ) : null}

      <PageLoading show={loading && items.length === 0} />
    </PageShell>
  );
}
