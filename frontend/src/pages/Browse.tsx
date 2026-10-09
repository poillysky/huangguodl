import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { api, type BrowseFilters } from "../api/client";
import PageLoading from "../components/PageLoading";
import PageShell from "../components/PageShell";
import ShowGrid from "../components/ShowGrid";
import {
  useInfiniteCatalog,
  useLoadMoreSentinel,
} from "../hooks/useInfiniteCatalog";

type Opt = { id: string; label: string };

/** 黄果 · 分类（大类 / 官方频道；热门走「排序」，不放排行榜） */
const GUO_KINDS: Opt[] = [
  { id: "all", label: "全部" },
  { id: "ai-manju", label: "成人漫剧" },
  { id: "ai-duanju", label: "AI短剧" },
  { id: "ai-huanlian", label: "AI换脸" },
  { id: "ai-mogai", label: "AI魔改" },
];

const STATUSES: Opt[] = [
  { id: "all", label: "全部" },
  { id: "done", label: "完结" },
  { id: "air", label: "连载" },
];

const SORTS: Opt[] = [
  { id: "hot", label: "热度" },
  { id: "new", label: "最新" },
];

/** 野果 · theme 分类（热门/最新走「排序」） */
const YE_FALLBACK: Opt[] = [
  { id: "theme:7", label: "野果原创" },
  { id: "theme:8", label: "真人短剧" },
  { id: "theme:9", label: "魔改漫剧" },
  { id: "theme:10", label: "网红改编" },
  { id: "theme:11", label: "PMV裸舞" },
];

/** 黄豆 · 频道大类（热门/最新走「排序」，不放分类里） */
const DOU_FALLBACK: Opt[] = [
  { id: "yuandou", label: "黄豆原创" },
  { id: "mod", label: "魔改短剧" },
  { id: "caibian", label: "擦边短剧" },
  { id: "zhenren", label: "真人短剧" },
  { id: "erciyuan", label: "动漫" },
  { id: "aiman", label: "影院" },
  { id: "zongyi", label: "贤者" },
  { id: "heiliao", label: "黑料" },
];

function guoCatalogKey(kind: string, genre: string, sort: "hot" | "new") {
  // 题材优先：具体 tag 覆盖大类
  if (genre !== "all") return `tag:${genre}`;
  if (kind !== "all") return kind;
  return sort;
}

function douCatalogKey(kind: string, sort: "hot" | "new") {
  if (kind && kind !== "all") return kind;
  return sort;
}

function yeguoCatalogKey(kind: string, sort: "hot" | "new") {
  if (kind && kind !== "all") return kind;
  return sort;
}

/** 只保留黄豆频道；去掉热门/最新（与排序重复）和黄果噪声 */
function sanitizeDouKinds(raw: Opt[]): Opt[] {
  const noise = new Set([
    "hot",
    "new",
    "all",
    "rank",
    "ai-duanju",
    "ai-manju",
    "ai-huanlian",
    "ai-mogai",
  ]);
  const out: Opt[] = [];
  const seen = new Set<string>();
  for (const c of raw) {
    const id = c.id.trim().toLowerCase();
    if (!id || seen.has(id) || noise.has(id)) continue;
    if (id.startsWith("tag:")) continue;
    if (!/^[a-z][a-z0-9_-]{0,31}$/.test(id)) continue;
    seen.add(id);
    out.push({ id, label: c.label || id });
  }
  return out.length ? out : [...DOU_FALLBACK];
}

function sanitizeYeKinds(raw: Opt[]): Opt[] {
  const noise = new Set(["hot", "new", "all", "rank"]);
  const out: Opt[] = [];
  const seen = new Set<string>();
  for (const c of raw) {
    const id = c.id.trim();
    if (!id || seen.has(id) || noise.has(id)) continue;
    seen.add(id);
    out.push({ id, label: c.label || id });
  }
  return out.length ? out : [...YE_FALLBACK];
}

const YE_EXTRA_DIMS = ["setting", "background", "time"] as const;
type YeExtraDim = (typeof YE_EXTRA_DIMS)[number];

function parseYeExtraFilters(raw: BrowseFilters | undefined): YeFilterDim[] {
  if (!raw) return [];
  return YE_EXTRA_DIMS.flatMap((id) => {
    const block = raw[id];
    if (!block?.options?.length) return [];
    const opts = block.options
      .map((o) => ({
        id: String(o.value ?? "").trim() || "all",
        label: String(o.title || o.value || "").trim(),
      }))
      .filter((o) => o.id && o.label);
    if (!opts.length) return [];
    const hasAll = opts.some((o) => o.id === "all" || o.id === "0");
    return [
      {
        id,
        label: block.title || id,
        options: hasAll
          ? opts.map((o) => ({
              ...o,
              id: o.id === "0" ? "all" : o.id,
            }))
          : [{ id: "all", label: "全部" }, ...opts],
      },
    ];
  });
}

type YeFilterDim = { id: YeExtraDim; label: string; options: Opt[] };

function buildYeFilterTab(values: Record<YeExtraDim, string>) {
  const parts: string[] = [];
  for (const id of YE_EXTRA_DIMS) {
    const v = values[id];
    if (v && v !== "all" && v !== "0") parts.push(`${id}:${v}`);
  }
  return parts.length ? parts.join(",") : undefined;
}

export type BrowseSource = "huangguo" | "huangdou" | "yeguo";

function IconSearch() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden>
      <circle
        cx="11"
        cy="11"
        r="6.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        d="M16.5 16.5 20 20"
      />
    </svg>
  );
}

export default function BrowsePage({ source }: { source: BrowseSource }) {
  const nav = useNavigate();
  const isDou = source === "huangdou";
  const isYe = source === "yeguo";
  const [kind, setKind] = useState("all");
  const [status, setStatus] = useState("all");
  const [genre, setGenre] = useState("all");
  const [sort, setSort] = useState<"hot" | "new">("hot");
  const [douTab, setDouTab] = useState("");
  const [douTabs, setDouTabs] = useState<Opt[]>([]);
  const [douKinds, setDouKinds] = useState<Opt[]>(() => [...DOU_FALLBACK]);
  const [yeKinds, setYeKinds] = useState<Opt[]>(() => [...YE_FALLBACK]);
  const [yeExtraFilters, setYeExtraFilters] = useState<YeFilterDim[]>([]);
  const [yeSetting, setYeSetting] = useState("all");
  const [yeBackground, setYeBackground] = useState("all");
  const [yeTime, setYeTime] = useState("all");
  const [guoGenres, setGuoGenres] = useState<Opt[]>([
    { id: "all", label: "全部" },
  ]);

  useEffect(() => {
    let cancelled = false;
    void api
      .config(source)
      .then((cfg) => {
        if (cancelled) return;
        if (cfg.source && cfg.source !== source) {
          return;
        }
        if (isDou) {
          setDouKinds(
            sanitizeDouKinds(
              (cfg.categories || []).map((c) => ({
                id: String(c.value || "").trim(),
                label: String(c.title || c.value || "").trim(),
              })),
            ),
          );
          return;
        }
        if (isYe) {
          setYeKinds(
            sanitizeYeKinds(
              (cfg.categories || []).map((c) => ({
                id: String(c.value || "").trim(),
                label: String(c.title || c.value || "").trim(),
              })),
            ),
          );
          setYeExtraFilters(parseYeExtraFilters(cfg.filters));
          return;
        }
        const tags = (cfg.tags || [])
          .map((c) => ({
            id: String(c.value || "")
              .trim()
              .toLowerCase()
              .replace(/^tag:/, ""),
            label: String(c.title || c.value || "").trim(),
          }))
          .filter((c) => c.id && c.id !== "all");
        setGuoGenres([{ id: "all", label: "全部" }, ...tags]);
      })
      .catch(() => {
        /* 保留当前列表 */
      });
    return () => {
      cancelled = true;
    };
  }, [source, isDou, isYe]);

  // 黄豆：选中分类后拉官方子 Tab
  useEffect(() => {
    if (!isDou || !kind || kind === "all") {
      setDouTabs([]);
      setDouTab("");
      return;
    }
    let cancelled = false;
    setDouTabs([]);
    setDouTab("");
    void api
      .navTabs(kind, "huangdou")
      .then((r) => {
        if (cancelled) return;
        const tabs = (r.tabs || [])
          .map((t) => ({
            id: String(t.value || "").trim(),
            label: String(t.title || t.value || "").trim(),
          }))
          .filter((t) => t.id);
        setDouTabs(tabs);
        if (tabs[0]) setDouTab(tabs[0].id);
      })
      .catch(() => {
        if (!cancelled) {
          setDouTabs([]);
          setDouTab("");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isDou, kind]);

  useEffect(() => {
    setKind("all");
    setGenre("all");
    setStatus("all");
    setSort("hot");
    setDouTab("");
    setDouTabs([]);
    setYeSetting("all");
    setYeBackground("all");
    setYeTime("all");
  }, [source]);

  const yeFilterTab = useMemo(
    () =>
      buildYeFilterTab({
        setting: yeSetting,
        background: yeBackground,
        time: yeTime,
      }),
    [yeSetting, yeBackground, yeTime],
  );

  const category = isDou
    ? douCatalogKey(kind, sort)
    : isYe
      ? yeguoCatalogKey(kind, sort)
      : guoCatalogKey(kind, genre, sort);

  const mode = useMemo(
    () => ({
      type: "catalog" as const,
      category,
      sort,
      source,
      tab: isDou
        ? kind !== "all" && douTab
          ? douTab
          : undefined
        : isYe
          ? yeFilterTab
          : undefined,
    }),
    [category, sort, source, isDou, isYe, kind, douTab, yeFilterTab],
  );

  const {
    items: catalogItems,
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
    return catalogItems.filter((s) => {
      if (status === "done" && !s.finished) return false;
      if (status === "air" && s.finished) return false;
      return true;
    });
  }, [catalogItems, status]);

  const title = isDou ? "黄豆" : isYe ? "野果" : "黄果";
  const kindOptions = isDou
    ? [{ id: "all", label: "全部" }, ...douKinds]
    : isYe
      ? [{ id: "all", label: "全部" }, ...yeKinds]
      : GUO_KINDS;
  const kindValue = kind;

  return (
    <PageShell
      title={title}
      onRefresh={refresh}
      right={
        <button
          type="button"
          className="topbar-btn"
          aria-label="搜索"
          onClick={() => nav(`/search?source=${source}`)}
        >
          <IconSearch />
        </button>
      }
    >
      <div className="filters">
        <FilterRow
          label="分类"
          options={kindOptions}
          value={kindValue}
          onChange={(v) => {
            setKind(v);
            // 换大类时清题材 / 子类
            setGenre("all");
            setDouTab("");
            setDouTabs([]);
          }}
          scroll
        />

        {isDou && kind !== "all" && douTabs.length > 0 ? (
          <FilterRow
            label="子类"
            options={douTabs}
            value={douTab || douTabs[0]?.id || ""}
            onChange={setDouTab}
            scroll
          />
        ) : null}

        {isYe
          ? yeExtraFilters.map((dim) => (
              <FilterRow
                key={dim.id}
                label={dim.label}
                options={dim.options}
                value={
                  dim.id === "setting"
                    ? yeSetting
                    : dim.id === "background"
                      ? yeBackground
                      : yeTime
                }
                onChange={(v) => {
                  if (dim.id === "setting") setYeSetting(v);
                  else if (dim.id === "background") setYeBackground(v);
                  else setYeTime(v);
                }}
                scroll
              />
            ))
          : null}

        {!isDou && !isYe ? (
          <FilterRow
            label="题材"
            options={guoGenres}
            value={genre}
            onChange={setGenre}
            scroll
          />
        ) : null}

        <FilterRow
          label="排序"
          options={SORTS}
          value={sort}
          onChange={(v) => setSort(v === "new" ? "new" : "hot")}
          variant="segment"
        />
        <FilterRow
          label="状态"
          options={STATUSES}
          value={status}
          onChange={setStatus}
          variant="segment"
        />
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
        {!loading && !loadingMore && !hasMore && catalogItems.length > 0 && (
          <span>没有更多了</span>
        )}
      </div>

      <PageLoading show={loading && catalogItems.length === 0} />
    </PageShell>
  );
}

function FilterRow({
  label,
  options,
  value,
  onChange,
  variant = "chips",
  scroll = false,
}: {
  label: string;
  options: readonly Opt[];
  value: string;
  onChange: (v: string) => void;
  variant?: "chips" | "segment";
  /** 单行横滑，不换行 */
  scroll?: boolean;
}) {
  if (variant === "segment") {
    return (
      <div className="filter-row filter-row-seg">
        <span className="filter-lab">{label}</span>
        <div
          className="seg"
          role="radiogroup"
          aria-label={label}
          style={{ "--seg-n": options.length } as CSSProperties}
        >
          {options.map((o) => {
            const on = value === o.id;
            return (
              <button
                key={o.id}
                type="button"
                role="radio"
                aria-checked={on}
                className={on ? "seg-item on" : "seg-item"}
                onClick={() => onChange(o.id)}
              >
                {o.label}
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className={`filter-row${scroll ? " filter-row-scroll" : ""}`}>
      <span className="filter-lab">{label}</span>
      <div className={scroll ? "chips chips-scroll" : "chips"}>
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
