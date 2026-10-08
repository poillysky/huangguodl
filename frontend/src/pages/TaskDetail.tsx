import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, Task, getToken } from "../api/client";
import PageLoading from "../components/PageLoading";
import PageShell from "../components/PageShell";

const STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  running: "下载中",
  done: "已完成",
  error: "失败",
  pending: "待下",
  ok: "完成",
  fail: "失败",
  skip: "跳过",
  exist: "已有",
};

function statusLabel(s: string) {
  return STATUS_LABEL[s] || s;
}

function formatTime(ts?: number) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function TaskDetailPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const refresh = useCallback(() => {
    if (!id) return Promise.resolve();
    return api
      .task(id)
      .then((r) => {
        setTask(r.task);
        setError("");
      })
      .catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(() => {
    setLoading(true);
    void refresh().finally(() => setLoading(false));
  }, [refresh]);

  useEffect(() => {
    if (!id || task?.status !== "running") {
      esRef.current?.close();
      esRef.current = null;
      return;
    }
    esRef.current?.close();
    const token = getToken();
    const url = token
      ? `/api/tasks/${id}/events?access_token=${encodeURIComponent(token)}`
      : `/api/tasks/${id}/events`;
    const es = new EventSource(url);
    esRef.current = es;
    const onUpdate = () => void refresh();
    es.addEventListener("episode", onUpdate);
    es.addEventListener("cover", onUpdate);
    es.addEventListener("started", onUpdate);
    es.addEventListener("snapshot", onUpdate);
    es.addEventListener("done", () => {
      void refresh();
      es.close();
    });
    return () => es.close();
  }, [id, task?.status, refresh]);

  const items = useMemo(() => {
    const list = [...(task?.items || [])];
    list.sort((a, b) => a.ep - b.ep);
    return list;
  }, [task?.items]);

  const plan = task?.plan?.length ?? 0;
  const total = items.length || task?.total || plan;
  const done = task?.done ?? items.filter((i) => i.status === "ok" || i.status === "exist").length;
  const fail = task?.fail ?? items.filter((i) => i.status === "fail").length;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const canStart = task?.status === "queued" || task?.status === "error";

  async function onStart() {
    if (!task || starting) return;
    setStarting(true);
    setError("");
    try {
      const res = await api.startTask(task.id);
      if (!res.ok) {
        setError(res.error || "开始失败");
        return;
      }
      if (res.task) setTask(res.task);
      else await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  async function onRedownload() {
    if (!task || starting) return;
    setStarting(true);
    setError("");
    try {
      const res = await api.download({
        title: task.title,
        id: task.vid || undefined,
        cover: true,
        start: true,
        force: true,
        follow: Boolean(task.follow),
      });
      if (!res.ok) {
        setError(res.error || "重新下载失败");
        return;
      }
      if (res.skipped) {
        setError(res.message || "没有可重下的集");
        return;
      }
      if (res.taskId && res.taskId !== task.id) {
        nav(`/tasks/${encodeURIComponent(res.taskId)}`, { replace: true });
        return;
      }
      if (res.task) setTask(res.task);
      else await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  async function onToggleFollow() {
    if (!task || starting) return;
    setStarting(true);
    setError("");
    try {
      const res = await api.setTaskFollow(task.id, !task.follow);
      if (!res.ok) {
        setError(res.error || "追更设置失败");
        return;
      }
      if (res.task) setTask(res.task);
      else await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  async function onCheckFollow() {
    if (starting) return;
    setStarting(true);
    setError("");
    setNotice("");
    try {
      const res = await api.checkFollow();
      await refresh();
      if (res.errors?.length) {
        setError(res.errors.join("；"));
        return;
      }
      setNotice(
        [
          `检查 ${res.checked} 部`,
          res.enqueued ? `新增 ${res.enqueued} 集` : "无新增",
          res.started ? `已开始 ${res.started}` : "",
        ]
          .filter(Boolean)
          .join(" · "),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  return (
    <PageShell
      title={task?.title || "任务详情"}
      back="/tasks"
      subtitle={task ? statusLabel(task.status) : undefined}
      onRefresh={() => refresh()}
      right={
        task?.vid ? (
          <button
            type="button"
            className="topbar-btn ghost-text"
            onClick={() =>
              nav(`/show/${encodeURIComponent(task.vid)}`, {
                state: { id: task.vid, title: task.title },
              })
            }
          >
            剧页
          </button>
        ) : null
      }
    >
      {error ? <p className="err banner">{error}</p> : null}
      {notice && !error ? <p className="muted banner">{notice}</p> : null}

      {task ? (
        <div className="task-detail">
          <div className="task-detail-hero">
            <div className="task-detail-stats">
              <div>
                <em>{done}</em>
                <span>完成</span>
              </div>
              <div>
                <em>{fail}</em>
                <span>失败</span>
              </div>
              <div>
                <em>{total}</em>
                <span>合计</span>
              </div>
            </div>
            <div className="task-progress">
              <div className="task-progress-track">
                <div
                  className={`task-progress-bar ${task.status}`}
                  style={{ width: `${task.status === "queued" ? 0 : pct}%` }}
                />
              </div>
              <div className="task-progress-label">
                <span>{pct}%</span>
                <span>{formatTime(task.created)}</span>
              </div>
            </div>
          </div>

          <dl className="task-detail-meta">
            {task.folder ? (
              <>
                <dt>目录</dt>
                <dd>
                  downloads/{task.folder}/Season 01/
                </dd>
              </>
            ) : null}
            {task.coverNote ? (
              <>
                <dt>封面</dt>
                <dd>{task.coverNote}</dd>
              </>
            ) : null}
            {task.error ? (
              <>
                <dt>错误</dt>
                <dd className="err">{task.error}</dd>
              </>
            ) : null}
          </dl>

          <div className="task-detail-actions">
            {canStart ? (
              <button
                type="button"
                className="btn task-detail-start"
                disabled={starting}
                onClick={() => void onStart()}
              >
                {starting
                  ? "启动中…"
                  : task.status === "error"
                    ? "重试下载"
                    : "开始下载"}
              </button>
            ) : null}

            {task.status !== "running" ? (
              <button
                type="button"
                className={`btn ghost task-detail-start${task.follow ? " on" : ""}`}
                disabled={starting}
                onClick={() => void onToggleFollow()}
              >
                {task.follow ? "追更中 · 点按关闭" : "开启追更"}
              </button>
            ) : null}

            {task.follow && task.status !== "running" ? (
              <button
                type="button"
                className="btn ghost task-detail-start"
                disabled={starting}
                onClick={() => void onCheckFollow()}
              >
                {starting ? "检查中…" : "立刻检查新集"}
              </button>
            ) : null}

            {task.status === "done" ? (
              <button
                type="button"
                className="btn task-detail-start"
                disabled={starting}
                onClick={() => void onRedownload()}
              >
                {starting ? "准备中…" : "重新下载（覆盖）"}
              </button>
            ) : null}
          </div>

          {task.follow ? (
            <p className="muted task-follow-hint">
              追更已开：约每天自动检查，只下完成记录里没有的新集
              {task.followCheckedAt
                ? ` · 上次 ${formatTime(task.followCheckedAt)}`
                : ""}
            </p>
          ) : null}

          {task.status === "running" ? (
            <p className="task-live">正在下载，列表实时更新</p>
          ) : null}

          <div className="block-head">
            <h2>分集</h2>
            <span className="muted">{items.length} 集</span>
          </div>
          <ul className="task-ep-list">
            {items.map((it) => (
              <li key={it.ep} className={`task-ep-row ${it.status}`}>
                <span className="task-ep-n">第{it.ep}集</span>
                <span className="task-ep-st">{statusLabel(it.status)}</span>
                <span className="task-ep-note" title={it.file || it.note}>
                  {it.note || it.file || "—"}
                </span>
              </li>
            ))}
            {!items.length ? (
              <li className="muted task-ep-empty">没有分集记录</li>
            ) : null}
          </ul>
        </div>
      ) : null}

      <PageLoading show={loading} />
    </PageShell>
  );
}
