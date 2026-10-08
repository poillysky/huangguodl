import { FormEvent, useMemo, useState } from "react";
import PageLoading from "../components/PageLoading";
import PageShell from "../components/PageShell";
import ShowGrid from "../components/ShowGrid";
import {
  useInfiniteCatalog,
  useLoadMoreSentinel,
} from "../hooks/useInfiniteCatalog";

type Tab = "hot" | "new";

export default function HomePage() {
  const [tab, setTab] = useState<Tab>("hot");
  const [q, setQ] = useState("");
  const [keyword, setKeyword] = useState("");

  const mode = useMemo(
    () =>
      keyword
        ? ({ type: "search" as const, keyword })
        : ({ type: "catalog" as const, category: tab === "hot" ? "hot" : "new" }),
    [keyword, tab],
  );

  const { items, loading, loadingMore, hasMore, error, loadMore, refresh } =
    useInfiniteCatalog(mode);
  const sentinelRef = useLoadMoreSentinel(
    loadMore,
    !loading && hasMore && !error,
  );

  function onSearch(e: FormEvent) {
    e.preventDefault();
    setKeyword(q.trim());
  }

  function switchTab(next: Tab) {
    if (next === tab && !keyword) return;
    setKeyword("");
    setQ("");
    setTab(next);
  }

  return (
    <PageShell title="首页" onRefresh={refresh}>
      <div className="page-sticky">
        <header className="page-head">
          <form className="search-row" onSubmit={onSearch}>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜剧名"
            />
            <button className="btn" type="submit">
              搜索
            </button>
            {keyword && (
              <button
                className="btn ghost"
                type="button"
                onClick={() => {
                  setQ("");
                  setKeyword("");
                }}
              >
                清除
              </button>
            )}
          </form>
        </header>

        {!keyword ? (
          <div className="block-head tabs">
            <button
              type="button"
              className={tab === "hot" ? "tab on" : "tab"}
              onClick={() => switchTab("hot")}
            >
              热门
            </button>
            <button
              type="button"
              className={tab === "new" ? "tab on" : "tab"}
              onClick={() => switchTab("new")}
            >
              最近更新
            </button>
          </div>
        ) : (
          <div className="block-head sticky-sub">
            <h2>搜索结果</h2>
            <span className="muted">「{keyword}」</span>
          </div>
        )}
      </div>

      {error && (
        <p className="err">
          {error} <a href="/settings">去设置代理</a>
        </p>
      )}

      {(items.length > 0 || !loading) && <ShowGrid items={items} />}

      <div ref={sentinelRef} className="load-more" aria-hidden={!loadingMore}>
        {loadingMore && (
          <>
            <span className="page-loading__spin sm" />
            <span>加载更多…</span>
          </>
        )}
        {!loading && !loadingMore && !hasMore && items.length > 0 && (
          <span>没有更多了</span>
        )}
      </div>

      <PageLoading show={loading && items.length === 0} />
    </PageShell>
  );
}
