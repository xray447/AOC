import { useEffect, useState } from "react";

type Session = { username: string; role: "admin" | "pilot"; csrf: string };
type Profile = {
  min_fl: number;
  max_fl: number;
  route_provider_order: string[];
  coverage_ignore_below_nm: number;
  updated_at: string | null;
  updated_by: string | null;
};

const PROVIDERS = ["AIP", "GRAPH", "SIMBRIEF"];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export default function App() {
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [form, setForm] = useState<Profile | null>(null);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const loadProfile = async () => {
    const p = await api<Profile>("/api/network-profile");
    setProfile(p);
    setForm(p);
  };

  useEffect(() => {
    api<Session>("/api/session")
      .then(async (s) => {
        setSession(s);
        await loadProfile();
      })
      .catch(() => setSession(null));
  }, []);

  const login = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const s = await api<Session>("/api/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setSession(s);
      await loadProfile();
      setMsg({ kind: "ok", text: `已登录：${s.username}（${s.role}）` });
    } catch (err) {
      setMsg({ kind: "err", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    await api("/api/logout", { method: "POST" });
    setSession(null);
    setProfile(null);
    setForm(null);
  };

  const save = async () => {
    if (!form || !session) return;
    setBusy(true);
    setMsg(null);
    try {
      const p = await api<Profile>("/api/network-profile", {
        method: "PUT",
        headers: { "X-CSRF-Token": session.csrf },
        body: JSON.stringify({
          min_fl: form.min_fl,
          max_fl: form.max_fl,
          route_provider_order: form.route_provider_order,
          coverage_ignore_below_nm: form.coverage_ignore_below_nm,
        }),
      });
      setProfile(p);
      setForm(p);
      setMsg({ kind: "ok", text: "已保存" });
    } catch (err) {
      setMsg({ kind: "err", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!session) return;
    setBusy(true);
    try {
      const p = await api<Profile>("/api/network-profile/reset", {
        method: "POST",
        headers: { "X-CSRF-Token": session.csrf },
      });
      setProfile(p);
      setForm(p);
      setMsg({ kind: "ok", text: "已恢复默认" });
    } catch (err) {
      setMsg({ kind: "err", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  if (session === undefined) return <div className="shell">加载中…</div>;

  if (session === null) {
    return (
      <div className="shell">
        <form className="card login" onSubmit={login}>
          <h1>AOC 管理端</h1>
          <div className="sub">M0 登录 / CSRF / 表单读写探针</div>
          <label>用户名</label>
          <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} />
          <label>密码</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <div className="actions">
            <button disabled={busy}>登录</button>
            {msg && <span className={`msg ${msg.kind}`}>{msg.text}</span>}
          </div>
          <div className="meta">演示账号：admin / admin123 · pilot / pilot123</div>
        </form>
      </div>
    );
  }

  const readonly = session.role !== "admin";
  const toggleProvider = (name: string) => {
    if (!form) return;
    const has = form.route_provider_order.includes(name);
    const next = has
      ? form.route_provider_order.filter((p) => p !== name)
      : PROVIDERS.filter((p) => [...form.route_provider_order, name].includes(p));
    setForm({ ...form, route_provider_order: next });
  };

  return (
    <div className="shell">
      <div className="header">
        <h1>AOC 网络参数</h1>
        <span className="badge">{session.username} · {session.role}</span>
        <button className="ghost" onClick={logout}>退出</button>
      </div>
      <div className="sub">分组表单 → API → CSV/JSON 落盘；pilot 只读，写操作返回 403。</div>

      <div className="card">
        <h2>航路参数</h2>
        <div className="row">
          <div>
            <label>最低巡航高度（FL）</label>
            <input type="number" disabled={readonly} value={form?.min_fl ?? 0}
              onChange={(e) => form && setForm({ ...form, min_fl: Number(e.target.value) })} />
          </div>
          <div>
            <label>最高巡航高度（FL）</label>
            <input type="number" disabled={readonly} value={form?.max_fl ?? 0}
              onChange={(e) => form && setForm({ ...form, max_fl: Number(e.target.value) })} />
          </div>
          <div>
            <label>覆盖检查忽略航程（NM）</label>
            <input type="number" disabled={readonly} value={form?.coverage_ignore_below_nm ?? 0}
              onChange={(e) => form && setForm({ ...form, coverage_ignore_below_nm: Number(e.target.value) })} />
          </div>
        </div>
        <div className="hint">最低高度必须小于最高高度；覆盖检查对短航线直接跳过。</div>
      </div>

      <div className="card">
        <h2>数据源优先级</h2>
        <div className="checks">
          {PROVIDERS.map((p) => (
            <label key={p}>
              <input type="checkbox" disabled={readonly}
                checked={form?.route_provider_order.includes(p) ?? false}
                onChange={() => toggleProvider(p)} />
              {p}
            </label>
          ))}
        </div>
        <div className="hint">当前顺序：{form?.route_provider_order.join(" → ") || "无"}</div>
      </div>

      <div className="actions">
        <button disabled={busy || readonly} onClick={save}>保存</button>
        <button className="ghost" disabled={busy || readonly} onClick={reset}>恢复默认</button>
        {readonly && <span className="msg err">只读：需要管理员</span>}
        {msg && <span className={`msg ${msg.kind}`}>{msg.text}</span>}
      </div>
      <div className="meta">
        最近修改：{profile?.updated_at ?? "—"} {profile?.updated_by ? `by ${profile.updated_by}` : ""}
      </div>
    </div>
  );
}
