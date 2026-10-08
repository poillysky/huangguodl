import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api, Show, ShowDetail } from "../api/client";
import PageLoading from "../components/PageLoading";
import PageShell from "../components/PageShell";
import ShowGrid from "../components/ShowGrid";
import { useFavorite } from "../hooks/useFavorite";

function formatHot(n?: number) {
  const v = Number(n) || 0;
  if (v <= 0) return "";
  if (v >= 10000) {
    const wan = v / 10000;
    return `${wan >= 100 ? Math.round(wan) : wan.toFixed(wan >= 10 ? 0 : 1)}万`;
  }
  return String(v);
}

export default function ShowDetailPage() {
  const { id = "" } = useParams();
  const loc = useLocation();
  const nav = useNavigate();
  const seed = (loc.state as Show | null) || null;

  const [detail, setDetail] = useState<ShowDetail | null>(null);
  const [related, setRelated] = useState<Show[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(false);
  const [relatedErr, setRelatedErr] = useState("");
  const [loading, setLoading] = useState(!seed);
  const [descOpen, setDescOpen] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [epOpen, setEpOpen] = useState(false);
  const [epNeedFold, setEpNeedFold] = useState(false);
  const epGridRef = useRef<HTMLDivElement | null>(null);
  const { favorited, busy: favBusy, toggle: toggleFav } = useFavorite(id, seed);

  // 详情：只跟 id，不跟 seed（避免反复重建把推荐请求冲掉）
  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError("");
    setDescOpen(false);
    setMsg("");
    if (!seed) setLoading(true);
    const scroller = document.querySelector(".page-scroll");
    if (scroller) scroller.scrollTo({ top: 0, behavior: "smooth" });
    else window.scrollTo({ top: 0, behavior: "smooth" });

    void api
      .show(id)
      .then((r) => {
        if (!cancelled) setDetail(r);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps -- seed 仅作首屏占位

  // 猜你喜欢：详情就绪后再拉，与首屏解耦
  useEffect(() => {
    const sid = detail?.id;
    if (!sid) {
      setRelated([]);
      setRelatedLoading(false);
      setRelatedErr("");
      return;
    }
    let cancelled = false;
    setRelated([]);
    setRelatedErr("");
    setRelatedLoading(true);
    void api
      .showRelated(sid, detail?.tags || seed?.tags || [])
      .then((r) => {
        if (cancelled) return;
        setRelated(Array.isArray(r.items) ? r.items : []);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setRelated([]);
        setRelatedErr(e.message || "推荐加载失败");
      })
      .finally(() => {
        if (!cancelled) setRelatedLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [detail?.id]);

  const refresh = useCallback(() => {
    setLoading(true);
    setError("");
    return api
      .show(id)
      .then((r) => setDetail(r))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    setEpOpen(false);
  }, [id]);

  const eps = detail?.episodes || [];
  const title = detail?.title || seed?.title || id;

  useLayoutEffect(() => {
    const el = epGridRef.current;
    if (!el || !eps.length) {
      setEpNeedFold(false);
      return;
    }
    const GAP = 5;
    const MIN = 34;
    const layout = () => {
      const w = el.clientWidth;
      if (w <= 0) return;
      const cols = Math.max(1, Math.floor((w + GAP) / (MIN + GAP)));
      const size = (w - (cols - 1) * GAP) / cols;
      el.style.setProperty("--ep-cols", String(cols));
      el.style.setProperty("--ep-gap", `${GAP}px`);
      el.style.setProperty("--ep-size", `${size}px`);
      setEpNeedFold(Math.ceil(eps.length / cols) > 2);
    };
    layout();
    const ro = new ResizeObserver(layout);
    ro.observe(el);
    return () => ro.disconnect();
  }, [eps.length]);
  const cover = detail?.cover || seed?.cover || "";
  const hotText = formatHot(detail?.hot ?? seed?.hot);
  const coverSrc = cover ? api.coverUrl(cover) : "";

  function goPlay(n: number) {
    // 点选集时就开始拉播放器包，进页少等一轮
    void import("artplayer");
    void import("hls.js");
    nav(`/play/${encodeURIComponent(id)}/${n}`, {
      state: {
        title,
        cover,
        total: detail?.total || eps.length,
      },
    });
  }

  async function downloadAll() {
    if (!eps.length || busy) return;
    setBusy(true);
    setMsg("");
    setError("");
    try {
      const res = await api.download({
        title,
        id: id || undefined,
        episodes: eps.map((e) => e.n),
        cover: true,
        follow: !(detail?.finished ?? seed?.finished),
      });
      if (!res.ok) {
        setError(res.error || "下载启动失败");
        return;
      }
      if (res.skipped) {
        setMsg(res.message || "完成记录显示已全部下过");
        return;
      }
      if (res.reused) {
        setMsg(res.message || "已有进行中的任务");
        nav(res.taskId ? `/tasks/${encodeURIComponent(res.taskId)}` : "/tasks");
        return;
      }
      const pending = res.task?.plan?.length ?? eps.length;
      setMsg(res.message || `已加入队列，待下 ${pending} 集`);
      nav("/tasks");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function onToggleFav() {
    void toggleFav({
      id,
      title,
      cover,
      total: detail?.total || eps.length || seed?.total || 0,
      finished: detail?.finished ?? seed?.finished ?? false,
      label: detail?.label || seed?.label || "",
      tags: detail?.tags || seed?.tags || [],
      hot: detail?.hot ?? seed?.hot ?? 0,
    });
  }

  return (
    <PageShell
      className="detail-page"
      title={title}
      back="/"
      subtitle={detail?.channel || undefined}
      onRefresh={() => refresh()}
    >
      <div className="detail-hero">
        <div className="detail-cover">
          <span className="ph" aria-hidden>
            {title.slice(0, 8)}
          </span>
          {coverSrc ? (
            <img
              src={coverSrc}
              alt=""
              fetchPriority="high"
              decoding="async"
              onError={(e) => {
                e.currentTarget.style.display = "none";
              }}
            />
          ) : null}
          <span className="mark">18+</span>
          {(detail?.finished ?? seed?.finished) ? (
            <span className="status-badge done">完结</span>
          ) : (
            <span className="status-badge air">连载</span>
          )}
        </div>

        <div className="detail-meta">
          <h1>
            <span className="detail-title-text">{title}</span>
            {detail?.author ? (
              <span className="author-badge">{detail.author}</span>
            ) : null}
          </h1>

          <div className="stat-row">
            {detail?.score ? (
              <span className="stat">
                <em>{detail.score}</em>分
              </span>
            ) : null}
            {hotText ? (
              <span className="stat">
                <em>{hotText}</em>热度
              </span>
            ) : null}
            <span className="stat">
              <em>{detail?.total || eps.length || seed?.total || "?"}</em>集
            </span>
          </div>

          {!!(detail?.tags?.length || seed?.tags?.length) && (
            <div className="tag-row">
              {(detail?.tags || seed?.tags || []).map((t) => (
                <span key={t} className="tag-pill">
                  {t}
                </span>
              ))}
            </div>
          )}

          <div className="detail-hero-cta">
            <button
              className="btn"
              type="button"
              disabled={busy || !eps.length || loading}
              onClick={downloadAll}
            >
              {busy ? "加入中…" : `加入下载 · ${eps.length || 0}集`}
            </button>
            <button
              type="button"
              className={`btn ghost detail-fav-btn${favorited ? " on" : ""}`}
              aria-label={favorited ? "取消收藏" : "收藏"}
              aria-pressed={favorited}
              disabled={favBusy || !id}
              onClick={onToggleFav}
            >
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                {favorited ? (
                  <path
                    fill="currentColor"
                    d="M12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"
                  />
                ) : (
                  <path
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinejoin="round"
                    d="M12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"
                  />
                )}
              </svg>
              <span>{favorited ? "已收藏" : "收藏"}</span>
            </button>
          </div>
        </div>
      </div>

      {detail?.description ? (
        <div className="detail-desc-box">
          <p className={descOpen ? "detail-desc open" : "detail-desc"}>
            {detail.description}
          </p>
          {detail.description.length > 72 ? (
            <button
              type="button"
              className="desc-toggle"
              onClick={() => setDescOpen((v) => !v)}
            >
              {descOpen ? "收起" : "展开简介"}
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="detail-section play-section">
        <div className="block-head">
          <h2>在线播放</h2>
          {epNeedFold ? (
            <button
              type="button"
              className="ep-fold"
              onClick={() => setEpOpen((v) => !v)}
            >
              {epOpen ? "收起" : `展开全部 ${eps.length} 集`}
            </button>
          ) : null}
        </div>
        <div
          ref={epGridRef}
          className={`ep-grid${epNeedFold && !epOpen ? " is-collapsed" : ""}`}
        >
          {eps.map((e) => (
            <button
              key={e.n}
              type="button"
              className="ep-chip"
              disabled={loading}
              onClick={() => goPlay(e.n)}
              title={`播放第${e.n}集`}
            >
              <span className="ep-n">{e.n}</span>
            </button>
          ))}
        </div>
      </div>

      {error && <p className="err banner">{error}</p>}
      {msg && <p className="ok banner">{msg}</p>}

      {detail ? (
        <div className="detail-section related-section">
          <div className="block-head">
            <h2>猜你喜欢</h2>
            {relatedLoading ? <span className="muted">加载中…</span> : null}
          </div>
          {related.length > 0 ? (
            <ShowGrid items={related} variant="rail" />
          ) : relatedLoading ? (
            <p className="muted related-placeholder">正在拉取推荐…</p>
          ) : (
            <p className="muted related-placeholder">
              {relatedErr || "暂无推荐"}
            </p>
          )}
        </div>
      ) : null}

      <PageLoading show={loading && !seed} />
    </PageShell>
  );
}
