import { FormEvent, useEffect, useState } from "react";
import { api, RuntimeSettings } from "../api/client";
import PageLoading from "../components/PageLoading";
import PageShell from "../components/PageShell";
import { isIos, isStandalone } from "../pwa";

export default function SettingsPage() {
  const [form, setForm] = useState<RuntimeSettings>({
    hg_api: "",
    http_proxy: "",
    cover_proxy: "",
    cover_token: "",
  });
  const [out, setOut] = useState("");
  const [data, setData] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [standalone, setStandalone] = useState(false);
  const [ios, setIos] = useState(false);

  function loadSettings() {
    setLoading(true);
    setError("");
    return api
      .settings()
      .then((s) => {
        setForm({
          hg_api: s.hg_api,
          http_proxy: s.http_proxy,
          cover_proxy: s.cover_proxy,
          cover_token: s.cover_token,
        });
        setOut(s.out || "");
        setData(s.data || "");
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    setStandalone(isStandalone());
    setIos(isIos());
    void loadSettings();
  }, []);

  function setField<K extends keyof RuntimeSettings>(key: K, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMsg("");
    setError("");
    try {
      const s = await api.saveSettings(form);
      setForm({
        hg_api: s.hg_api,
        http_proxy: s.http_proxy,
        cover_proxy: s.cover_proxy,
        cover_token: s.cover_token,
      });
      setMsg("已保存，后续请求会走新配置");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function onTest() {
    setTesting(true);
    setMsg("");
    setError("");
    try {
      // save first so test uses form values
      await api.saveSettings(form);
      const r = await api.testSettings();
      setMsg(
        `连通正常 · 代理 ${r.proxy || "直连"} · 拿到 ${r.count} 条（示例：${(r.sample || []).join("、") || "无"}）`,
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setTesting(false);
    }
  }

  return (
    <PageShell title="配置" back="/me" onRefresh={() => loadSettings()}>
      <div className="panel">
        <h2>添加到主屏幕</h2>
        {standalone ? (
          <p className="ok">已在独立全屏模式运行（无 Safari 地址栏）。</p>
        ) : ios ? (
          <ol className="install-steps">
            <li>点 Safari 底栏中间的「分享」按钮</li>
            <li>
              下滑列表，点 <strong>添加到主屏幕</strong>
            </li>
            <li>确认名称后添加；从主屏幕图标打开即为全屏 App</li>
          </ol>
        ) : (
          <p className="muted">
            用 iPhone Safari 打开本页 → 分享 → <strong>添加到主屏幕</strong>
            ，再从图标启动即可全屏独立窗口。
          </p>
        )}
      </div>

      <div className="panel">
        <h2>连接</h2>
        <p className="muted">
          上游打不开时，填本机代理（Clash / V2Ray 常见端口{" "}
          <code>http://127.0.0.1:7890</code>）。保存后写到{" "}
          <code>data/settings.json</code>（与下载目录分离，重启不丢）。
        </p>
        {out && <p className="muted">下载目录：{out}</p>}
        {data && <p className="muted">配置目录：{data}</p>}

        <form className="settings-form" onSubmit={onSave}>
          <label>
            <span>HTTP 代理</span>
            <input
              value={form.http_proxy}
              onChange={(e) => setField("http_proxy", e.target.value)}
              placeholder="http://127.0.0.1:7890（留空=直连）"
              disabled={loading}
            />
          </label>
          <label>
            <span>上游 API</span>
            <input
              value={form.hg_api}
              onChange={(e) => setField("hg_api", e.target.value)}
              placeholder="https://huangguoai.com"
              disabled={loading}
            />
          </label>
          <label>
            <span>封面解密代理</span>
            <input
              value={form.cover_proxy}
              onChange={(e) => setField("cover_proxy", e.target.value)}
              placeholder="https://ai.wulii.de5.net"
              disabled={loading}
            />
          </label>
          <label>
            <span>封面 Token</span>
            <input
              value={form.cover_token}
              onChange={(e) => setField("cover_token", e.target.value)}
              placeholder="封面解密 token"
              type="password"
              autoComplete="off"
              disabled={loading}
            />
          </label>

          <div className="actions">
            <button className="btn" type="submit" disabled={saving || loading}>
              {saving ? "保存中…" : "保存"}
            </button>
            <button
              className="btn ghost"
              type="button"
              disabled={testing || loading}
              onClick={onTest}
            >
              {testing ? "测试中…" : "保存并测试连通"}
            </button>
          </div>
        </form>

        {msg && <p className="ok">{msg}</p>}
        {error && <p className="err">{error}</p>}
      </div>
      <PageLoading show={loading} />
    </PageShell>
  );
}
