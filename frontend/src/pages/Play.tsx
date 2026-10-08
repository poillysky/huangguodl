import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api, Show } from "../api/client";
import ArtHlsPlayer from "../components/ArtHlsPlayer";
import PageLoading from "../components/PageLoading";

const AUTO_KEY = "hg-dl-auto-next";

export default function PlayPage() {
  const { id = "", ep: epParam = "1" } = useParams();
  const ep = Math.max(1, Number(epParam) || 1);
  const loc = useLocation();
  const nav = useNavigate();
  const seed =
    (loc.state as { title?: string; cover?: string; total?: number } | null) ||
    null;

  const leavingRef = useRef(false);

  const [url, setUrl] = useState("");
  const [title, setTitle] = useState(seed?.title || "");
  const [cover, setCover] = useState(seed?.cover || "");
  const [total, setTotal] = useState(seed?.total || 0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retryTick, setRetryTick] = useState(0);
  /** 加载时铺封面；视频出画后撤掉 */
  const [coverBg, setCoverBg] = useState(true);
  const [autoNext, setAutoNext] = useState(() => {
    try {
      const v = localStorage.getItem(AUTO_KEY);
      return v === null ? true : v === "1";
    } catch {
      return true;
    }
  });
  const autoNextRef = useRef(autoNext);
  autoNextRef.current = autoNext;

  const metaRef = useRef({ id, title, cover, total, seed });
  metaRef.current = { id, title, cover, total, seed };
  const epRef = useRef(ep);
  epRef.current = ep;
  const totalRef = useRef(total);
  totalRef.current = total;

  function leaveToDetail() {
    if (leavingRef.current) return;
    leavingRef.current = true;
    const m = metaRef.current;
    const state: Show = {
      id: m.id,
      title: m.title || m.seed?.title || m.id,
      cover: m.cover || m.seed?.cover || "",
      total: m.total || m.seed?.total || 0,
      finished: false,
      label: "",
    };
    nav(`/show/${encodeURIComponent(m.id)}`, {
      state,
      replace: true,
    });
  }

  function goEp(n: number) {
    if (n < 1) return;
    const tot = totalRef.current;
    if (tot > 0 && n > tot) return;
    if (n === epRef.current) return;
    const m = metaRef.current;
    nav(`/play/${encodeURIComponent(m.id)}/${n}`, {
      state: {
        title: m.title || m.seed?.title || "",
        cover: m.cover || m.seed?.cover || "",
        total: m.total || m.seed?.total || 0,
      },
      replace: true,
    });
  }

  function retryStream() {
    setError("");
    setUrl("");
    setCoverBg(true);
    setRetryTick((n) => n + 1);
  }

  const coverSrc = cover ? api.coverUrl(cover) : undefined;
  const showCoverBg = coverBg && Boolean(coverSrc);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setUrl("");
    setCoverBg(true);

    const load = async () => {
      try {
        if (!title || !cover || !total) {
          const show = await api.show(id);
          if (cancelled) return;
          setTitle(show.title);
          setCover(show.cover);
          setTotal(show.total || show.episodes.length);
        }
        const play = await api.play(id, ep);
        if (cancelled) return;
        setUrl(play.url);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- title/cover/total 仅首屏补全，重试靠 retryTick
  }, [id, ep, retryTick]);

  // 播放页全屏铺到刘海：仅加载态铺封面；出画后清掉避免挡画面
  useEffect(() => {
    const root = document.documentElement;
    const shell = document.querySelector(".app-shell") as HTMLElement | null;
    root.classList.add("playing");
    const applyCover = (src?: string) => {
      const value = src ? `url(${JSON.stringify(src)})` : "";
      root.style.setProperty("--play-cover", value || "none");
      if (shell) {
        if (value) {
          shell.style.backgroundImage = value;
          shell.classList.add("has-cover");
        } else {
          shell.style.backgroundImage = "";
          shell.classList.remove("has-cover");
        }
      }
    };
    applyCover(showCoverBg ? coverSrc : undefined);
    return () => {
      root.classList.remove("playing");
      root.style.removeProperty("--play-cover");
      if (shell) {
        shell.style.backgroundImage = "";
        shell.classList.remove("has-cover");
      }
    };
  }, [coverSrc, showCoverBg]);

  return (
    <section className="page play-page">
      <div className="play-shell" role="region" aria-label="视频播放器">
        <div
          className={`play-stage${showCoverBg ? " has-cover" : ""}`}
          style={
            showCoverBg && coverSrc
              ? { backgroundImage: `url(${JSON.stringify(coverSrc)})` }
              : undefined
          }
        >
          {url ? (
            <ArtHlsPlayer
              key={`${id}-${ep}-${retryTick}`}
              url={url}
              poster={showCoverBg ? coverSrc : undefined}
              biz={{
                title,
                ep,
                total,
                autoNext,
                onBack: leaveToDetail,
                onToggleAutoNext: () => {
                  setAutoNext((v) => {
                    const next = !v;
                    try {
                      localStorage.setItem(AUTO_KEY, next ? "1" : "0");
                    } catch {
                      /* ignore */
                    }
                    return next;
                  });
                },
                onSelectEp: goEp,
              }}
              onEnded={() => {
                const cur = epRef.current;
                const tot = totalRef.current;
                const nextOk = tot > 0 ? cur < tot : true;
                if (autoNextRef.current && nextOk) goEp(cur + 1);
                else if (!nextOk) leaveToDetail();
              }}
              onError={(msg) => setError(msg)}
              onVideoReady={() => setCoverBg(false)}
            />
          ) : (
            <div className="play-stage-empty">
              {loading ? "" : error || "暂无播放地址"}
              {!loading && error ? (
                <button
                  type="button"
                  className="btn play-retry"
                  onClick={retryStream}
                >
                  重新取流
                </button>
              ) : null}
            </div>
          )}
          {error && url ? (
            <div className="play-err-bar">
              <p className="err banner play-err">{error}</p>
              <button
                type="button"
                className="btn play-retry"
                onClick={retryStream}
              >
                重新取流
              </button>
            </div>
          ) : null}
          <PageLoading show={loading && !url} />
        </div>
      </div>
    </section>
  );
}
