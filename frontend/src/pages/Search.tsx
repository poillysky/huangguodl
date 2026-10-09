import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import PageLoading from "../components/PageLoading";
import PageShell from "../components/PageShell";
import ShowGrid from "../components/ShowGrid";
import {
  useInfiniteCatalog,
  useLoadMoreSentinel,
} from "../hooks/useInfiniteCatalog";
import type { BrowseSource } from "./Browse";

function resolveSource(raw: string | null): BrowseSource {
  if (raw === "huangdou") return "huangdou";
  if (raw === "yeguo") return "yeguo";
  return "huangguo";
}

function searchMeta(source: BrowseSource) {
  if (source === "huangdou") {
    return { back: "/huangdou", title: "搜索黄豆", placeholder: "输入黄豆剧名" };
  }
  if (source === "yeguo") {
    return { back: "/yeguo", title: "搜索野果", placeholder: "输入野果剧名" };
  }
  return { back: "/huangguo", title: "搜索黄果", placeholder: "输入黄果剧名" };
}

export default function SearchPage() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const source = resolveSource(params.get("source"));
  const initialQ = (params.get("q") || "").trim();
  const [draft, setDraft] = useState(initialQ);
  const [keyword, setKeyword] = useState(initialQ);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const { back, title, placeholder } = searchMeta(source);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const active = Boolean(keyword);
  const mode = useMemo(
    () => ({ type: "search" as const, keyword, source }),
    [keyword, source],
  );

  const {
    items,
    loading,
    loadingMore,
    hasMore,
    error,
    loadMore,
    refresh,
  } = useInfiniteCatalog(mode, 20, active);

  const sentinelRef = useLoadMoreSentinel(
    loadMore,
    active && !loading && hasMore && !error,
  );

  const runSearch = () => {
    const q = draft.trim();
    setKeyword(q);
    const next = new URLSearchParams({ source });
    if (q) next.set("q", q);
    nav(`/search?${next}`, { replace: true });
  };

  return (
    <PageShell title={title} back={back} onRefresh={active ? refresh : undefined}>
      <form
        className="search-row search-page-row"
        onSubmit={(e) => {
          e.preventDefault();
          runSearch();
        }}
      >
        <input
          ref={inputRef}
          type="search"
          enterKeyHint="search"
          placeholder={placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          aria-label="搜索剧名"
        />
        <button type="submit" className="btn" disabled={!draft.trim()}>
          搜索
        </button>
      </form>

      {!active ? <p className="empty">输入关键词开始搜索</p> : null}

      {error ? (
        <p className="err">
          {error} <a href="/settings">去设置代理</a>
        </p>
      ) : null}

      {active && !loading && !error && items.length === 0 ? (
        <p className="empty">没有搜到相关剧，换个词试试。</p>
      ) : null}

      {items.length > 0 ? <ShowGrid items={items} /> : null}

      <div ref={sentinelRef} className="load-more" aria-hidden={!loadingMore}>
        {loadingMore ? (
          <>
            <span className="page-loading__spin sm" />
            <span>加载更多…</span>
          </>
        ) : null}
        {active && !loading && !loadingMore && !hasMore && items.length > 0 ? (
          <span>没有更多了</span>
        ) : null}
      </div>

      <PageLoading show={active && loading && items.length === 0} />
    </PageShell>
  );
}
