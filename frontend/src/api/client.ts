export type Category = { value: string; title: string };

export type BrowseFilterDim = {
  title: string;
  options: Category[];
};

export type BrowseFilters = Record<string, BrowseFilterDim>;

export type Show = {
  id: string; // source:nativeId
  nativeId?: string;
  source?: string;
  title: string;
  total: number;
  finished: boolean;
  cover: string;
  label: string;
  tags?: string[];
  hot?: number;
};

export type SourceInfo = { name: string; title: string };

export type Episode = { n: number; title: string; url?: string };

export type ShowDetail = {
  id: string;
  nativeId?: string;
  source?: string;
  title: string;
  cover: string;
  tags: string[];
  finished: boolean;
  total: number;
  hot: number;
  score: number;
  description: string;
  author: string;
  channel: string;
  episodes: Episode[];
  related: Show[];
  label: string;
};

export type TaskItem = {
  ep: number;
  status: string;
  note: string;
  file?: string;
};

export type Task = {
  id: string;
  created: number;
  status: string;
  title: string;
  vid: string;
  folder?: string;
  cover?: boolean;
  score?: number;
  total?: number;
  have?: number[];
  plan?: number[];
  done?: number;
  fail?: number;
  coverNote?: string;
  coverOk?: boolean | null;
  error?: string;
  follow?: boolean;
  followCheckedAt?: number;
  items?: TaskItem[];
};

export type RuntimeSettings = {
  hg_api: string;
  http_proxy: string;
  cover_proxy: string;
  cover_token: string;
  huangdou_api?: string;
  yeguo_api?: string;
  sources_enabled?: string;
  out?: string;
  data?: string;
};

const TOKEN_KEY = "hg_api_token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || import.meta.env.VITE_API_TOKEN || "";
}

export function setToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type") && init?.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 25000);
  try {
    const res = await fetch(path, { ...init, headers, signal: ctrl.signal });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || body.error || JSON.stringify(body);
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    const ct = res.headers.get("Content-Type") || "";
    if (ct.includes("application/json")) return res.json();
    return undefined as T;
  } catch (e) {
    if ((e as Error).name === "AbortError") {
      throw new Error("请求超时：请到「设置」配置 HTTP 代理后重试");
    }
    throw e;
  } finally {
    window.clearTimeout(timer);
  }
}

export const api = {
  health: () => request<{ ok: boolean }>("/api/health"),
  config: (source?: string) => {
    const qs = source
      ? `?source=${encodeURIComponent(source)}`
      : "";
    return request<{
      ok: boolean;
      categories: Category[];
      tags?: Category[];
      filters?: BrowseFilters;
      sources?: SourceInfo[];
      source?: string | null;
      out: string;
      api: string;
      httpProxy: string;
      authRequired: boolean;
    }>(`/api/config${qs}`);
  },
  settings: () =>
    request<{ ok: boolean } & RuntimeSettings>("/api/settings"),
  saveSettings: (body: Partial<RuntimeSettings>) =>
    request<{ ok: boolean } & RuntimeSettings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  testSettings: () =>
    request<{
      ok: boolean;
      count: number;
      sample: string[];
      proxy: string;
      api: string;
    }>("/api/settings/test", { method: "POST", body: "{}" }),
  catalog: (
    category: string,
    page = 1,
    pageSize = 20,
    sort?: "hot" | "new",
    source?: string,
    tab?: string,
  ) => {
    const qs = new URLSearchParams({
      category,
      page: String(page),
      pageSize: String(pageSize),
    });
    if (sort) qs.set("sort", sort);
    if (source) qs.set("source", source);
    if (tab) qs.set("tab", tab);
    return request<{
      items: Show[];
      category: string;
      page: number;
      sort?: string | null;
      source?: string | null;
      tab?: string | null;
    }>(`/api/catalog?${qs}`);
  },
  navTabs: (category: string, source = "huangdou") => {
    const qs = new URLSearchParams({
      category,
      source,
    });
    return request<{
      ok: boolean;
      source: string;
      category: string;
      tabs: Category[];
    }>(`/api/nav-tabs?${qs}`);
  },
  search: (q: string, page = 1, source?: string) => {
    const qs = new URLSearchParams({
      q,
      page: String(page),
    });
    if (source) qs.set("source", source);
    return request<{
      items: Show[];
      keyword: string;
      page: number;
      source?: string | null;
    }>(`/api/search?${qs}`);
  },
  episodes: (id: string) =>
    request<{ id: string; title: string; episodes: Episode[] }>(
      `/api/episodes?id=${encodeURIComponent(id)}`,
    ),
  show: (id: string) =>
    request<ShowDetail>(`/api/show?id=${encodeURIComponent(id)}`),
  showRelated: async (id: string, tags?: string[]) => {
    const qs = new URLSearchParams({ id });
    if (tags?.length) qs.set("tags", tags.filter(Boolean).join(","));
    try {
      return await request<{ ok?: boolean; id: string; items: Show[] }>(
        `/api/related?${qs}`,
      );
    } catch (err) {
      // 旧后端没有 /api/related 时，用热门兜底，避免详情页显示 Not Found
      const msg = (err as Error).message || "";
      if (!/not found|404/i.test(msg)) throw err;
      const hot = await request<{ items: Show[] }>(
        `/api/catalog?category=hot&page=1&pageSize=20`,
      );
      return {
        ok: true,
        id,
        items: (hot.items || []).filter((s) => s.id !== id).slice(0, 8),
      };
    }
  },
  play: (id: string, ep: number) =>
    request<{ id: string; ep: number; url: string; rawUrl?: string }>(
      `/api/play?id=${encodeURIComponent(id)}&ep=${ep}`,
    ),
  /** 浏览器取证播放用的本机 HLS 代理（一般由 /api/play 直接返回） */
  hlsUrl: (upstream: string) => {
    const qs = new URLSearchParams({ url: upstream });
    const token = getToken();
    if (token) qs.set("access_token", token);
    return `/api/hls?${qs}`;
  },
  download: (body: {
    title?: string;
    id?: string;
    episodes?: number[];
    cover?: boolean;
    start?: boolean;
    force?: boolean;
    follow?: boolean;
  }) =>
    request<{
      ok: boolean;
      taskId?: string | null;
      task?: Task | null;
      error?: string;
      candidates?: Show[];
      skipped?: boolean;
      reused?: boolean;
      merged?: boolean;
      message?: string;
    }>("/api/download", { method: "POST", body: JSON.stringify(body) }),
  tasks: () => request<{ ok: boolean; tasks: Task[] }>("/api/tasks"),
  task: (id: string) => request<{ ok: boolean; task: Task }>(`/api/tasks/${id}`),
  startTask: (id: string) =>
    request<{ ok: boolean; task?: Task; error?: string }>(
      `/api/tasks/${encodeURIComponent(id)}/start`,
      { method: "POST" },
    ),
  setTaskFollow: (id: string, follow: boolean) =>
    request<{ ok: boolean; task?: Task; error?: string }>(
      `/api/tasks/${encodeURIComponent(id)}/follow`,
      { method: "POST", body: JSON.stringify({ follow }) },
    ),
  checkFollow: () =>
    request<{
      ok: boolean;
      checked: number;
      enqueued: number;
      started: number;
      errors: string[];
    }>("/api/tasks/follow/check", { method: "POST", body: "{}" }),
  deleteTask: (id: string) =>
    request<{ ok: boolean; id?: string }>(
      `/api/tasks/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    ),
  coverUrl: (raw: string) => `/api/cover?url=${encodeURIComponent(raw)}`,
  favorites: () =>
    request<{ items: Show[]; count: number }>("/api/favorites"),
  favoriteStatus: (id: string) =>
    request<{ id: string; favorited: boolean }>(
      `/api/favorites/${encodeURIComponent(id)}`,
    ),
  addFavorite: (show: Pick<Show, "id" | "title" | "cover" | "total" | "finished" | "label"> & {
    tags?: string[];
    hot?: number;
  }) =>
    request<{ ok: boolean; item: Show; favorited: boolean }>(
      "/api/favorites",
      { method: "POST", body: JSON.stringify(show) },
    ),
  removeFavorite: (id: string) =>
    request<{ ok: boolean; id: string; favorited: boolean }>(
      `/api/favorites/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    ),
};
