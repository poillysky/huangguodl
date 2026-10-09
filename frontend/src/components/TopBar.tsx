import { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

type Props = {
  title: string;
  /** true = history back; string = navigate to path */
  back?: boolean | string;
  right?: ReactNode;
  /** subtle subtitle / badge on the right of title row center */
  subtitle?: string;
  /** start = 标题靠左（浏览页）；默认居中 */
  titleAlign?: "center" | "start";
  /** 顶栏标题行下方插槽（如搜索） */
  extra?: ReactNode;
};

function IconChevronLeft() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M15 6 9 12l6 6"
      />
    </svg>
  );
}

function historyCanGoBack() {
  const idx = (window.history.state as { idx?: number } | null)?.idx;
  return typeof idx === "number" ? idx > 0 : window.history.length > 1;
}

export default function TopBar({
  title,
  back,
  right,
  subtitle,
  titleAlign = "center",
  extra,
}: Props) {
  const nav = useNavigate();
  const start = titleAlign === "start";

  function onBack() {
    // 有站内历史时优先 -1，保留列表筛选；否则落到指定路径
    if (typeof back === "string") {
      if (historyCanGoBack()) nav(-1);
      else nav(back);
      return;
    }
    if (back) {
      if (historyCanGoBack()) nav(-1);
      else nav("/huangguo");
    }
  }

  return (
    <header className={`topbar${extra ? " topbar-has-extra" : ""}`}>
      <div className={`topbar-row${start ? " topbar-row-start" : ""}`}>
        {start ? (
          <>
            <div className="topbar-start">
              {back ? (
                <button
                  type="button"
                  className="topbar-btn"
                  aria-label="返回"
                  onClick={onBack}
                >
                  <IconChevronLeft />
                </button>
              ) : null}
              <div className="topbar-title-block">
                <h1 className="topbar-title">{title}</h1>
                {subtitle ? <p className="topbar-sub">{subtitle}</p> : null}
              </div>
            </div>
            {extra ? <div className="topbar-inline">{extra}</div> : null}
            {right ? <div className="topbar-side right">{right}</div> : null}
          </>
        ) : (
          <>
            <div className="topbar-side left">
              {back ? (
                <button
                  type="button"
                  className="topbar-btn"
                  aria-label="返回"
                  onClick={onBack}
                >
                  <IconChevronLeft />
                </button>
              ) : (
                <span className="topbar-side-spacer" aria-hidden />
              )}
            </div>
            <div className="topbar-center">
              <h1 className="topbar-title">{title}</h1>
              {subtitle ? <p className="topbar-sub">{subtitle}</p> : null}
            </div>
            <div className="topbar-side right">
              {right ?? <span className="topbar-side-spacer" aria-hidden />}
            </div>
          </>
        )}
      </div>
      {!start && extra ? <div className="topbar-extra">{extra}</div> : null}
    </header>
  );
}
