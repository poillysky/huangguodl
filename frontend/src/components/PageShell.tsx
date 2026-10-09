import { ReactNode, useRef } from "react";
import { usePullToRefresh } from "../hooks/usePullToRefresh";
import TopBar from "./TopBar";

type Props = {
  title: string;
  back?: boolean | string;
  right?: ReactNode;
  subtitle?: string;
  titleAlign?: "center" | "start";
  /** 顶栏内标题下方插槽（搜索等） */
  headerExtra?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Pull-down to reconnect / reload list */
  onRefresh?: () => void | Promise<void>;
};

/** TopBar stays fixed outside rubber-band; only .page-scroll bounces. */
export default function PageShell({
  title,
  back,
  right,
  subtitle,
  titleAlign,
  headerExtra,
  children,
  className = "",
  onRefresh,
}: Props) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const ptrRef = useRef<HTMLDivElement | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  usePullToRefresh(scrollerRef, {
    enabled: Boolean(onRefresh),
    onRefresh: onRefresh || (() => undefined),
    ptrRef,
    bodyRef,
  });

  return (
    <section className={`page${className ? ` ${className}` : ""}`}>
      <TopBar
        title={title}
        back={back}
        right={right}
        subtitle={subtitle}
        titleAlign={titleAlign}
        extra={headerExtra}
      />
      <div className="page-scroll" ref={scrollerRef}>
        {onRefresh ? (
          <div className="ptr" ref={ptrRef} aria-hidden>
            <span className="ptr-spin" />
            <span className="ptr-text">下拉刷新</span>
          </div>
        ) : null}
        <div className="ptr-body" ref={bodyRef}>
          {children}
        </div>
      </div>
    </section>
  );
}
