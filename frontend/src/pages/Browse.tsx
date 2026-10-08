import { useMemo, useState } from "react";
import PageLoading from "../components/PageLoading";
import PageShell from "../components/PageShell";
import ShowGrid from "../components/ShowGrid";
import {
  useInfiniteCatalog,
  useLoadMoreSentinel,
} from "../hooks/useInfiniteCatalog";

/** 官方频道 /api/videos/category/{slug}，都能拉到不同列表 */
const KINDS = [
  { id: "all", label: "全部" },
  { id: "ai-manju", label: "成人漫剧" },
  { id: "ai-duanju", label: "AI短剧" },
  { id: "ai-huanlian", label: "换脸" },
  { id: "ai-mogai", label: "魔改" },
] as const;

const STATUSES = [
  { id: "all", label: "全部" },
  { id: "done", label: "完结" },
  { id: "air", label: "连载" },
] as const;

const SORTS = [
  { id: "hot", label: "热度" },
  { id: "new", label: "最新" },
] as const;

/** 官方 /tag/{slug}/ 题材页（huangguoai.com 现网可打开的 tag 全集） */
const GENRES = [
  { id: "all", label: "全部" },
  { id: "dushi", label: "都市" },
  { id: "xiandai", label: "现代" },
  { id: "xiaoyuan", label: "校园" },
  { id: "zhichang", label: "职场" },
  { id: "haomen", label: "豪门" },
  { id: "hougong", label: "后宫" },
  { id: "shunv", label: "熟女" },
  { id: "nianxia", label: "年下" },
  { id: "jiedi", label: "姐弟" },
  { id: "muzi", label: "母子" },
  { id: "dananzhu", label: "大男主" },
  { id: "danvzhu", label: "大女主" },
  { id: "nixi", label: "逆袭" },
  { id: "quanmou", label: "权谋" },
  { id: "bazong", label: "霸总" },
  { id: "yulequan", label: "娱乐圈" },
  { id: "mingxing", label: "明星" },
  { id: "tianchong", label: "甜宠" },
  { id: "gufeng", label: "古风" },
  { id: "xianxia", label: "仙侠" },
  { id: "qihuan", label: "奇幻" },
  { id: "xuanhuan", label: "玄幻" },
  { id: "chaonengli", label: "超能力" },
  { id: "xitong", label: "系统" },
  { id: "naodong", label: "脑洞" },
  { id: "youxi", label: "游戏" },
  { id: "huangdao", label: "荒岛" },
  { id: "tongshi", label: "同事" },
  { id: "lvmao", label: "绿帽" },
  { id: "ntr", label: "NTR" },
  { id: "luanlun", label: "乱伦" },
] as const;

const GENRE_LABEL: Record<string, string> = Object.fromEntries(
  GENRES.filter((g) => g.id !== "all").map((g) => [g.id, g.label]),
);

function catalogKey(kind: string, genre: string, sort: "hot" | "new") {
  if (kind !== "all") return kind;
  if (genre !== "all") return `tag:${genre}`;
  return sort;
}

export default function BrowsePage() {
  const [kind, setKind] = useState("all");
  const [status, setStatus] = useState("all");
  const [genre, setGenre] = useState("all");
  const [sort, setSort] = useState<"hot" | "new">("hot");

  const category = catalogKey(kind, genre, sort);
  const mode = useMemo(
    () => ({ type: "catalog" as const, category, sort }),
    [category, sort],
  );

  const {
    items: source,
    loading,
    loadingMore,
    hasMore,
    error,
    loadMore,
    refresh,
  } = useInfiniteCatalog(mode);
  const sentinelRef = useLoadMoreSentinel(
    loadMore,
    !loading && hasMore && !error,
  );

  const items = useMemo(() => {
    const genreLabel = genre === "all" ? "" : GENRE_LABEL[genre] || genre;
    return source.filter((s) => {
      if (status === "done" && !s.finished) return false;
      if (status === "air" && s.finished) return false;
      // 频道 + 题材：频道走官方接口，题材再按 tags 收窄
      if (kind !== "all" && genreLabel) {
        const blob = `${s.title} ${(s.tags || []).join(" ")}`;
        if (!blob.includes(genreLabel)) return false;
      }
      return true;
    });
  }, [source, status, kind, genre]);

  return (
    <PageShell title="分类" onRefresh={refresh}>
      <div className="page-sticky filters-sticky">
        <div className="filters">
          <FilterRow
            label="分类"
            options={KINDS}
            value={kind}
            onChange={setKind}
          />
          <FilterRow
            label="排序"
            options={SORTS}
            value={sort}
            onChange={(v) => setSort(v === "new" ? "new" : "hot")}
          />
          <FilterRow
            label="状态"
            options={STATUSES}
            value={status}
            onChange={setStatus}
          />
          <FilterRow
            label="题材"
            options={GENRES}
            value={genre}
            onChange={setGenre}
            scrollRows={2}
          />
        </div>
      </div>

      {error && (
        <p className="err">
          {error} <a href="/settings">去设置代理</a>
        </p>
      )}
      {!loading && !error && items.length === 0 && (
        <p className="empty">没有符合筛选的剧，换条件试试。</p>
      )}

      {(items.length > 0 || !loading) && <ShowGrid items={items} />}

      <div ref={sentinelRef} className="load-more" aria-hidden={!loadingMore}>
        {loadingMore && (
          <>
            <span className="page-loading__spin sm" />
            <span>加载更多…</span>
          </>
        )}
        {!loading && !loadingMore && !hasMore && source.length > 0 && (
          <span>没有更多了</span>
        )}
      </div>

      <PageLoading show={loading && source.length === 0} />
    </PageShell>
  );
}

function FilterRow({
  label,
  options,
  value,
  onChange,
  scrollRows,
}: {
  label: string;
  options: readonly { id: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
  /** 固定行数 + 横向滚动（题材用） */
  scrollRows?: 2;
}) {
  return (
    <div className={`filter-row${scrollRows ? " filter-row-scroll" : ""}`}>
      <span className="filter-lab">{label}</span>
      <div
        className={scrollRows === 2 ? "chips chips-scroll-2" : "chips"}
      >
        {options.map((o) => (
          <button
            key={o.id}
            type="button"
            className={value === o.id ? "chip on" : "chip"}
            onClick={() => onChange(o.id)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
