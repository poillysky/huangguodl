import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, Task, getToken } from "../api/client";
import PageLoading from "../components/PageLoading";
import PageShell from "../components/PageShell";

function formatTime(ts?: number) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function taskCounts(t: Task) {
  const items = t.items || [];
  const total =
    items.length ||
    t.total ||
    (t.plan?.length ?? 0) + (t.have?.length ?? 0);
  const done =
    t.done ??
    items.filter((i) => i.status === "ok" || i.status === "exist").length;
  const fail = t.fail ?? items.filter((i) => i.status === "fail").length;
  return { total, done, fail };
}

export default function TasksPage() {
  const nav = useNavigate();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [startingId, setStartingId] = useState<string | null>(null);
  const [redoingId, setRedoingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const firstLoad = useRef(true);

  function refresh() {
    const showOverlay = firstLoad.current;
    if (showOverlay) setLoading(true);
    return api
      .tasks()
      .then((r) => {
        // 同剧只留最新一条；空壳（0 集可下）不展示
        const seen = new Set<string>();
        const cleaned: Task[] = [];
        for (const t of r.tasks) {
          const { done } = taskCounts(t);
          const plan = t.plan?.length ?? 0;
          if (
            plan === 0 &&
            done === 0 &&
            t.status !== "running" &&
            !t.follow
          ) {
            continue;
          }
          const key = t.vid || t.title;
          if (key && seen.has(key)) continue;
          if (key) seen.add(key);
          cleaned.push(t);
        }
        setTasks(cleaned);
        setError("");
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => {
        if (showOverlay) {
          firstLoad.current = false;
          setLoading(false);
        }
      });
  }

  useEffect(() => {
    void refresh();
    const t = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    if (!activeId) return;
    esRef.current?.close();
    const token = getToken();
    const url = token
      ? `/api/tasks/${activeId}/events?access_token=${encodeURIComponent(token)}`
      : `/api/tasks/${activeId}/events`;
    const es = new EventSource(url);
    esRef.current = es;

    const onUpdate = () => void refresh();
    es.addEventListener("episode", onUpdate);
    es.addEventListener("cover", onUpdate);
    es.addEventListener("started", onUpdate);
    es.addEventListener("done", () => {
      void refresh();
      es.close();
    });
    es.addEventListener("error", () => {});
    es.addEventListener("snapshot", onUpdate);

    return () => es.close();
  }, [activeId]);

  useEffect(() => {
    const running = tasks.find((t) => t.status === "running");
    if (running && running.id !== activeId) setActiveId(running.id);
  }, [tasks, activeId]);

  async function onStart(tid: string, e: MouseEvent) {
    e.stopPropagation();
    if (startingId) return;
    setStartingId(tid);
    setError("");
    try {
      const res = await api.startTask(tid);
      if (!res.ok) {
        setError(res.error || "开始失败");
        return;
      }
      setActiveId(tid);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setStartingId(null);
    }
  }

  async function onDelete(tid: string, e: MouseEvent) {
    e.stopPropagation();
    if (deletingId) return;
    setDeletingId(tid);
    setError("");
    try {
      await api.deleteTask(tid);
      if (activeId === tid) setActiveId(null);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDeletingId(null);
    }
  }

  async function onRedownload(t: Task, e: MouseEvent) {
    e.stopPropagation();
    if (redoingId || !t.title) return;
    setRedoingId(t.id);
    setError("");
    setNotice("");
    try {
      const res = await api.download({
        title: t.title,
        id: t.vid || undefined,
        cover: true,
        start: true,
        force: true,
        follow: Boolean(t.follow),
      });
      if (!res.ok) {
        setError(res.error || "重新下载失败");
        return;
      }
      if (res.skipped) {
        setNotice(res.message || "没有可重下的集");
        return;
      }
      setNotice(res.message || "已覆盖重下并开始");
      if (res.taskId) setActiveId(res.taskId);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRedoingId(null);
    }
  }

  async function onToggleFollow(t: Task, e: MouseEvent) {
    e.stopPropagation();
    setError("");
    setNotice("");
    try {
      const res = await api.setTaskFollow(t.id, !t.follow);
      if (!res.ok) {
        setError(res.error || "追更设置失败");
        return;
      }
      setNotice(res.task?.follow ? "已开启追更（每日只下新增）" : "已关闭追更");
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const stats = useMemo(() => {
    let queued = 0;
    let running = 0;
    let done = 0;
    for (const t of tasks) {
      if (t.status === "queued") queued += 1;
      else if (t.status === "running") running += 1;
      else if (t.status === "done") done += 1;
    }
    return { queued, running, done };
  }, [tasks]);

  return (
    <PageShell title="下载" back="/me" onRefresh={() => refresh()}>
      {!loading && tasks.length > 0 ? (
        <div className="task-summary">
          <span>
            <em>{stats.queued}</em>排队
          </span>
          <span>
            <em>{stats.running}</em>进行中
          </span>
          <span>
            <em>{stats.done}</em>完成
          </span>
        </div>
      ) : null}

      {error ? <p className="err banner">{error}</p> : null}
      {notice && !error ? <p className="muted banner">{notice}</p> : null}

      {!loading && !tasks.length ? (
        <div className="fav-empty-state">
          <div className="fav-empty-glow" aria-hidden />
          <div className="fav-empty-icon" aria-hidden>
            <svg viewBox="0 0 24 24" width="36" height="36">
              <path
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 3.5v10.2M8.2 10.2 12 14l3.8-3.8M5 17.5h14"
              />
            </svg>
          </div>
          <h2 className="fav-empty-title">还没有下载任务</h2>
          <p className="fav-empty-desc">
            打开一部剧点「加入下载」，以完成记录为准跳过已下集；可开追更每日只补新集。
          </p>
          <button
            type="button"
            className="btn fav-empty-cta"
            onClick={() => nav("/huangguo")}
          >
            去黄果看看
          </button>
        </div>
      ) : null}

      <div className="task-list">
        {tasks.map((t) => {
          const { total, done, fail } = taskCounts(t);
          const pct =
            t.status === "queued"
              ? 0
              : total > 0
                ? Math.min(100, Math.round((done / total) * 100))
                : t.status === "done"
                  ? 100
                  : 0;
          const canStart = t.status === "queued" || t.status === "error";
          return (
            <article
              key={t.id}
              className={`task-row status-${t.status}`}
              role="button"
              tabIndex={0}
              onClick={() => nav(`/tasks/${encodeURIComponent(t.id)}`)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  nav(`/tasks/${encodeURIComponent(t.id)}`);
                }
              }}
            >
              <div className="task-row-top">
                <h3 className="task-row-name">{t.title}</h3>
                <span className={`task-row-pct ${t.status}`}>
                  {t.status === "queued"
                    ? "等待"
                    : t.status === "error"
                      ? "失败"
                      : `${pct}%`}
                </span>
              </div>
              <div className="task-row-bar">
                <div
                  className={`task-row-fill ${t.status}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <div className="task-row-foot">
                <span>
                  {done}/{total || "?"}
                  {fail > 0 ? ` · ${fail}失败` : ""}
                  {t.status === "running" ? " · 下载中" : ""}
                  {t.status === "done" ? " · 完成" : ""}
                  {t.follow ? " · 追更" : ""}
                  {t.status !== "running" ? (
                    <span className="task-row-time"> · {formatTime(t.created)}</span>
                  ) : null}
                </span>
                <span className="task-row-ops">
                  {canStart ? (
                    <button
                      type="button"
                      className="task-row-action"
                      disabled={startingId === t.id}
                      onClick={(e) => void onStart(t.id, e)}
                    >
                      {startingId === t.id
                        ? "…"
                        : t.status === "error"
                          ? "重试"
                          : "开始"}
                    </button>
                  ) : null}
                  {t.status !== "running" ? (
                    <button
                      type="button"
                      className={`task-row-action${t.follow ? " on" : ""}`}
                      onClick={(e) => void onToggleFollow(t, e)}
                    >
                      {t.follow ? "追更中" : "追更"}
                    </button>
                  ) : null}
                  {t.status === "done" ? (
                    <button
                      type="button"
                      className="task-row-action"
                      disabled={redoingId === t.id}
                      onClick={(e) => void onRedownload(t, e)}
                    >
                      {redoingId === t.id ? "…" : "重新下载"}
                    </button>
                  ) : null}
                  {t.status !== "running" ? (
                    <button
                      type="button"
                      className="task-row-action danger"
                      disabled={deletingId === t.id}
                      onClick={(e) => void onDelete(t.id, e)}
                    >
                      {deletingId === t.id ? "…" : "删除"}
                    </button>
                  ) : null}
                </span>
              </div>
            </article>
          );
        })}
      </div>
      <PageLoading show={loading} />
    </PageShell>
  );
}
