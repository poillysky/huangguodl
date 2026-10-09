import { useNavigate } from "react-router-dom";
import PageShell from "../components/PageShell";

const LINKS = [
  {
    to: "/favorites",
    title: "收藏",
    desc: "已收藏的剧集",
  },
  {
    to: "/tasks",
    title: "下载",
    desc: "下载任务与追更",
  },
  {
    to: "/settings",
    title: "配置",
    desc: "代理、上游 API、片源开关",
  },
] as const;

export default function MePage() {
  const nav = useNavigate();

  return (
    <PageShell title="我的">
      <div className="me-menu" role="list">
        {LINKS.map((item) => (
          <button
            key={item.to}
            type="button"
            className="me-menu-item"
            role="listitem"
            onClick={() => nav(item.to)}
          >
            <span className="me-menu-text">
              <span className="me-menu-title">{item.title}</span>
              <span className="me-menu-desc">{item.desc}</span>
            </span>
            <span className="me-menu-chevron" aria-hidden>
              ›
            </span>
          </button>
        ))}
      </div>
    </PageShell>
  );
}
