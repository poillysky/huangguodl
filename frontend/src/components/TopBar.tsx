import { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

type Props = {
  title: string;
  /** true = history back; string = navigate to path */
  back?: boolean | string;
  right?: ReactNode;
  /** subtle subtitle / badge on the right of title row center */
  subtitle?: string;
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

export default function TopBar({ title, back, right, subtitle }: Props) {
  const nav = useNavigate();

  function onBack() {
    if (typeof back === "string") {
      nav(back);
      return;
    }
    if (window.history.length > 1) nav(-1);
    else nav("/");
  }

  return (
    <header className="topbar">
      <div className="topbar-row">
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
      </div>
    </header>
  );
}
