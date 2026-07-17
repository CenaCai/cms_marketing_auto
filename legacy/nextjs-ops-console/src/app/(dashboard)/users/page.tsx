"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
import { MODULES, ACTIONS } from "@/lib/permissions";

type U = {
  id: string;
  name: string;
  email: string;
  username?: string;
  memberships?: { role: string; status: string }[];
  userPermissions?: { module: string; action: string; allowed: boolean }[];
};

type PermMap = Record<string, Record<string, boolean>>;

function emptyPerms(): PermMap {
  const m: PermMap = {};
  MODULES.forEach((mod) => {
    m[mod.key] = {};
    ACTIONS.forEach((a) => (m[mod.key][a.key] = false));
  });
  return m;
}

export default function UsersPage() {
  const [users, setUsers] = useState<U[]>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [err, setErr] = useState("");

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<U | null>(null);
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("MARKETING_OPERATOR");
  const [status, setStatus] = useState("active");
  const [perms, setPerms] = useState<PermMap>(emptyPerms());
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    setForbidden(false);
    try {
      const data = await api<U[]>("/api/users");
      setUsers(data ?? []);
    } catch (e: any) {
      if (e.message?.includes("403") || e.message?.includes("权限")) setForbidden(true);
      else setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function openNew() {
    setEditing(null);
    setName("");
    setUsername("");
    setEmail("");
    setPassword("");
    setRole("MARKETING_OPERATOR");
    setStatus("active");
    setPerms(emptyPerms());
    setErr("");
    setFormOpen(true);
  }
  function openEdit(u: U) {
    setEditing(u);
    setName(u.name);
    setUsername(u.username ?? "");
    setEmail(u.email);
    setPassword("");
    setRole(u.memberships?.[0]?.role ?? "MARKETING_OPERATOR");
    setStatus(u.memberships?.[0]?.status ?? "active");
    const p = emptyPerms();
    (u.userPermissions ?? []).forEach((row) => {
      if (p[row.module]) p[row.module][row.action] = row.allowed;
    });
    setPerms(p);
    setErr("");
    setFormOpen(true);
  }
  function togglePerm(mod: string, act: string) {
    setPerms((prev) => ({
      ...prev,
      [mod]: { ...prev[mod], [act]: !prev[mod]?.[act] },
    }));
  }
  function quickFill(rolePreset: "all" | "none" | "ops") {
    const p = emptyPerms();
    MODULES.forEach((mod) => {
      ACTIONS.forEach((a) => {
        if (rolePreset === "all") p[mod.key][a.key] = true;
        else if (rolePreset === "ops") {
          // 运营：可对多数模块增改，但对账号管理只给查看
          if (mod.key === "users" && a.key !== "view") p[mod.key][a.key] = false;
          else if (a.key !== "delete") p[mod.key][a.key] = true;
          else p[mod.key][a.key] = mod.key === "users" ? false : true;
        }
      });
    });
    setPerms(p);
  }
  async function save() {
    setErr("");
    if (!name.trim() || !email.trim() || (!editing && !password.trim())) {
      return setErr("姓名 / 邮箱 / 密码(新建时) 必填");
    }
    setSaving(true);
    try {
      if (editing) {
        await api(`/api/users/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify({ role, status, permissions: perms }),
        });
      } else {
        await api("/api/users", {
          method: "POST",
          body: JSON.stringify({ name, username, email, password, role, permissions: perms }),
        });
      }
      setFormOpen(false);
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }
  async function delUser(u: U) {
    if (!confirm(`确认删除账号「${u.name}」？`)) return;
    await api(`/api/users/${u.id}`, { method: "DELETE" });
    await load();
  }

  if (forbidden) {
    return (
      <div>
        <h1 style={{ fontSize: 22 }}>账号管理</h1>
        <div className="card muted" style={{ marginTop: 16 }}>无权限访问。仅管理员（SUPER_ADMIN）可开通与管理运营账号。</div>
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 22 }}>账号管理</h1>
        <button className="btn btn-primary" onClick={openNew}>＋ 开通运营账号</button>
      </div>

      {err && <div style={{ color: "red", fontSize: 13, marginBottom: 8 }}>{err}</div>}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 24 }} className="muted">加载中…</div>
        ) : users.length === 0 ? (
          <div style={{ padding: 24 }} className="muted">还没有其他账号。</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                <th style={{ padding: "10px 14px" }}>姓名</th>
                <th style={{ padding: "10px 14px" }}>邮箱</th>
                <th style={{ padding: "10px 14px" }}>角色</th>
                <th style={{ padding: "10px 14px" }}>状态</th>
                <th style={{ padding: "10px 14px" }}></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "10px 14px" }}>{u.name}{u.username ? ` (${u.username})` : ""}</td>
                  <td style={{ padding: "10px 14px" }}>{u.email}</td>
                  <td style={{ padding: "10px 14px" }}><span style={{ fontSize: 12, color: u.memberships?.[0]?.role === "SUPER_ADMIN" ? "#7c3aed" : "#0891b2" }}>{u.memberships?.[0]?.role}</span></td>
                  <td style={{ padding: "10px 14px" }}><span style={{ fontSize: 12, color: u.memberships?.[0]?.status === "active" ? "#16a34a" : "#dc2626" }}>{u.memberships?.[0]?.status}</span></td>
                  <td style={{ padding: "10px 14px", textAlign: "right" }}>
                    <button className="btn" onClick={() => openEdit(u)}>编辑</button>
                    {u.memberships?.[0]?.role !== "SUPER_ADMIN" && (
                      <button className="btn" style={{ marginLeft: 6 }} onClick={() => delUser(u)}>删除</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {formOpen && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 16, marginBottom: 12 }}>{editing ? "编辑账号" : "开通运营账号"}</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>姓名 *</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>邮箱 *</label>
              <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>登录账号名</label>
              <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="可选" />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>{editing ? "重置密码（留空不修改）" : "密码 *"}</label>
              <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>角色</label>
              <select className="input" value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="MARKETING_OPERATOR">运营 (OPERATOR)</option>
                <option value="ORG_ADMIN">组织管理员 (ORG_ADMIN)</option>
                <option value="VIEWER">只读 (VIEWER)</option>
              </select>
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>状态</label>
              <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="active">active</option>
                <option value="disabled">disabled</option>
              </select>
            </div>
          </div>

          <div style={{ marginTop: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <h3 style={{ fontSize: 15 }}>功能权限（按目录勾选增删改查）</h3>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn" onClick={() => quickFill("ops")}>运营模板</button>
                <button className="btn" onClick={() => quickFill("all")}>全选</button>
                <button className="btn" onClick={() => quickFill("none")}>清空</button>
              </div>
            </div>
            <div style={{ overflowX: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ background: "#f8fafc", textAlign: "center" }}>
                    <th style={{ padding: "8px 10px", textAlign: "left" }}>目录</th>
                    {ACTIONS.map((a) => (
                      <th key={a.key} style={{ padding: "8px 10px" }}>{a.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {MODULES.map((mod) => (
                    <tr key={mod.key} style={{ borderTop: "1px solid var(--border)" }}>
                      <td style={{ padding: "8px 10px" }}>{mod.label}</td>
                      {ACTIONS.map((a) => (
                        <td key={a.key} style={{ textAlign: "center", padding: "8px 10px" }}>
                          <input
                            type="checkbox"
                            checked={!!perms[mod.key]?.[a.key]}
                            onChange={() => togglePerm(mod.key, a.key)}
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {err && <div style={{ color: "red", fontSize: 13, marginTop: 8 }}>{err}</div>}
          <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
            <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? "保存中…" : "保存账号"}</button>
            <button className="btn" onClick={() => setFormOpen(false)}>取消</button>
          </div>
        </div>
      )}
    </div>
  );
}
