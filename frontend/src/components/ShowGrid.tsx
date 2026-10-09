import { useNavigate } from "react-router-dom";
import { api, Show } from "../api/client";

function formatHot(n?: number) {
  const v = Number(n) || 0;
  if (v <= 0) return "";
  if (v >= 10000) {
    const wan = v / 10000;
    return `${wan >= 100 ? Math.round(wan) : wan.toFixed(wan >= 10 ? 0 : 1)}万`;
  }
  return String(v);
}

const SOURCE_META: Record<string, { label: string; tone: string }> = {
  huangguo: { label: "果", tone: "guo" },
  huangdou: { label: "豆", tone: "dou" },
  yeguo: { label: "野", tone: "ye" },
};

function sourceMeta(source?: string) {
  const key = (source || "huangguo").trim().toLowerCase() || "huangguo";
  return (
    SOURCE_META[key] || {
      label: key.slice(0, 2),
      tone: "other",
    }
  );
}

export default function ShowGrid({
  items,
  variant = "grid",
}: {
  items: Show[];
  variant?: "grid" | "rail";
}) {
  const nav = useNavigate();
  if (!items.length) {
    return <p className="empty">这一页没有剧。</p>;
  }
  return (
    <div className={variant === "rail" ? "poster-rail" : "poster-grid"}>
      {items.map((s) => {
        const hotText = formatHot(s.hot);
        const src = sourceMeta(s.source);
        return (
          <article
            key={s.id}
            className={variant === "rail" ? "tile rail-tile" : "tile"}
            onClick={() => nav(`/show/${encodeURIComponent(s.id)}`, { state: s })}
          >
            <div className="tile-art">
              <span className="ph" aria-hidden>
                {s.title.slice(0, 8)}
              </span>
              {s.cover ? (
                <img
                  src={api.coverUrl(s.cover)}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  fetchPriority="low"
                  onError={(e) => {
                    e.currentTarget.style.display = "none";
                  }}
                />
              ) : null}
              <div className="tile-badges">
                <span className="mark">18+</span>
                <span className={`src-badge src-${src.tone}`}>{src.label}</span>
              </div>
              {hotText ? (
                <span className="hot">{hotText}</span>
              ) : (
                <span className="ep">
                  {s.finished ? "全" : "更"}
                  {s.total || "?"}集
                </span>
              )}
              <div className="tile-veil">
                <h3>{s.title}</h3>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}
