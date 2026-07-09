"use client";

import { useEffect, useState } from "react";
import { api, getToken } from "@/lib/api-client";

type Seg = { id: string; name: string; type: string; description?: string; _count?: { contactSegments: number } };
type Contact = { id: string; name?: string; email?: string };

export default function SegmentsPage() {
  const [segments, setSegments] = useState<Seg[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  // 分组表单
  const [formOpen, setFormOpen] = useState(false);
  const [segName, setSegName] = useState("");
  const [segType, setSegType] = useState("static");
  const [segDesc, setSegDesc] = useState("");
  const [saving, setSaving] = useState(false);

  // 详情（成员 + 导出）
  const [detail, setDetail] = useState<Seg | null>(null);
  const [members, setMembers] = useState<Contact[]>([]);
  const [membersLoading, setMembersLoading] = useState(false);
  // 添加联系人
  const [addOpen, setAddOpen] = useState(false);
  const [addPicked, setAddPicked] = useState<string[]>([]);

  async function load() {
    setLoading(true);
    try {
      const [sg, ct] = await Promise.all([
        api<Seg[]>("/api/segments"),
        api<{ items: Contact[] }>("/api/contacts?limit=1000"),
      ]);
      setSegments(sg ?? []);
      setContacts(ct?.items ?? []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function openNew() {
    setSegName("");
    setSegType("static");
    setSegDesc("");
    setErr("");
    setFormOpen(true);
  }
  async function saveSeg() {
    setErr("");
    if (!segName.trim()) return setErr("请填写分组名称");
    setSaving(true);
    try {
      await api("/api/segments", {
        method: "POST",
        body: JSON.stringify({ name: segName.trim(), type: segType, description: segDesc.trim() || undefined }),
      });
      setFormOpen(false);
      await load();
    } catch (e: any) {
      // 名称重复等
      setErr(e.message?.includes("name") ? "分组名称已存在，请换一个" : e.message || "创建失败");
    } finally {
      setSaving(false);
    }
  }
  async function delSeg(s: Seg) {
    if (!confirm(`确认删除分组「${s.name}」？`)) return;
    await api(`/api/segments/${s.id}`, { method: "DELETE" });
    await load();
  }

  async function openDetail(s: Seg) {
    setDetail(s);
    setAddPicked([]);
    setMembersLoading(true);
    setMembers([]);
    try {
      const m = await api<Contact[]>(`/api/segments/${s.id}/members`);
      setMembers(m ?? []);
    } finally {
      setMembersLoading(false);
    }
  }
  function toggleAdd(id: string) {
    setAddPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  }
  async function addMembers() {
    if (!detail || addPicked.length === 0) return;
    await api(`/api/segments/${detail.id}/members`, { method: "POST", body: JSON.stringify({ contactIds: addPicked }) });
    setAddOpen(false);
    setAddPicked([]);
    await openDetail(detail);
    await load();
  }
  async function removeMember(id: string) {
    if (!detail) return;
    await api(`/api/segments/${detail.id}/members`, { method: "DELETE", body: JSON.stringify({ contactIds: [id] }) });
    await openDetail(detail);
    await load();
  }
  async function exportSeg() {
    if (!detail) return;
    const token = getToken() || "";
    const resp = await fetch(`/api/segments/${detail.id}/export`, { headers: { Authorization: `Bearer ${token}` } });
    if (!resp.ok) return alert("导出失败");
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `segment-${detail.name}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 22 }}>分群 / 分组</h1>
        <button className="btn btn-primary" onClick={openNew}>＋ 新建分组</button>
      </div>

      {err && <div style={{ color: "red", fontSize: 13, marginBottom: 8 }}>{err}</div>}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 24 }} className="muted">加载中…</div>
        ) : segments.length === 0 ? (
          <div style={{ padding: 24 }} className="muted">还没有分组。新建一个分组（名称不可重复），再把客户勾选进去。</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                <th style={{ padding: "10px 14px" }}>分组名称</th>
                <th style={{ padding: "10px 14px" }}>类型</th>
                <th style={{ padding: "10px 14px" }}>成员数</th>
                <th style={{ padding: "10px 14px" }}>说明</th>
                <th style={{ padding: "10px 14px" }}></th>
              </tr>
            </thead>
            <tbody>
              {segments.map((s) => (
                <tr key={s.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "10px 14px" }}>{s.name}</td>
                  <td style={{ padding: "10px 14px" }}>
                    <span style={{ fontSize: 12, color: s.type === "dynamic" ? "#7c3aed" : "#0891b2" }}>{s.type === "dynamic" ? "动态(规则)" : "静态(手动)"}</span>
                  </td>
                  <td style={{ padding: "10px 14px" }}>{s._count?.contactSegments ?? 0}</td>
                  <td style={{ padding: "10px 14px" }} className="muted">{s.description || "—"}</td>
                  <td style={{ padding: "10px 14px", textAlign: "right" }}>
                    <button className="btn" onClick={() => openDetail(s)}>成员</button>
                    <button className="btn" style={{ marginLeft: 6 }} onClick={() => delSeg(s)}>删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 新建分组 */}
      {formOpen && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 16, marginBottom: 12 }}>新建分组</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>分组名称 *（不可重复）</label>
              <input className="input" value={segName} onChange={(e) => setSegName(e.target.value)} placeholder="如：VIP 客户" />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>类型</label>
              <select className="input" value={segType} onChange={(e) => setSegType(e.target.value)}>
                <option value="static">静态（手动勾选客户）</option>
                <option value="dynamic">动态（按规则自动）</option>
              </select>
            </div>
          </div>
          <div style={{ marginTop: 12 }}>
            <label className="muted" style={{ fontSize: 13 }}>说明</label>
            <input className="input" value={segDesc} onChange={(e) => setSegDesc(e.target.value)} placeholder="可选" />
          </div>
          {err && <div style={{ color: "red", fontSize: 13, marginTop: 8 }}>{err}</div>}
          <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
            <button className="btn btn-primary" onClick={saveSeg} disabled={saving}>{saving ? "保存中…" : "保存分组"}</button>
            <button className="btn" onClick={() => setFormOpen(false)}>取消</button>
          </div>
        </div>
      )}

      {/* 分组详情：成员 + 导出 */}
      {detail && (
        <div className="card" style={{ marginTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ fontSize: 16 }}>分组：{detail.name}</h2>
            <div style={{ display: "flex", gap: 8 }}>
              {detail.type === "static" && (
                <button className="btn" onClick={() => { setAddPicked([]); setAddOpen(true); }}>＋ 添加客户</button>
              )}
              <button className="btn" onClick={exportSeg}>⬇ 导出 CSV</button>
              <button className="btn" onClick={() => setDetail(null)}>关闭</button>
            </div>
          </div>
          {detail.type === "dynamic" && (
            <p className="muted" style={{ fontSize: 13, marginTop: 4 }}>动态分组由规则自动计算，成员为只读；如需手动管理请使用静态分组。</p>
          )}
          {membersLoading ? (
            <div className="muted" style={{ fontSize: 13, marginTop: 10 }}>加载成员…</div>
          ) : (
            <div style={{ marginTop: 10, maxHeight: 280, overflow: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
              {members.length === 0 ? (
                <div style={{ padding: 16 }} className="muted">该分组暂无成员{detail.type === "static" ? "，点击「添加客户」。" : "（可能无匹配规则）。"}</div>
              ) : (
                members.map((m) => (
                  <div key={m.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 12px", borderBottom: "1px solid var(--border)", fontSize: 14 }}>
                    <span>{m.name || "—"} <span className="muted">{m.email}</span></span>
                    {detail.type === "static" && (
                      <button className="btn" onClick={() => removeMember(m.id)}>移除</button>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      )}

      {/* 添加客户到分组 */}
      {addOpen && detail && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 16, marginBottom: 8 }}>添加到「{detail.name}」</h2>
          <p className="muted" style={{ fontSize: 13, marginBottom: 8 }}>勾选客户（已选 {addPicked.length}），同一客户可加入多个分组。</p>
          <div style={{ maxHeight: 280, overflow: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
            {contacts.map((c) => (
              <label key={c.id} style={{ display: "flex", gap: 8, alignItems: "center", padding: "6px 10px", borderBottom: "1px solid var(--border)", fontSize: 13 }}>
                <input type="checkbox" checked={addPicked.includes(c.id)} onChange={() => toggleAdd(c.id)} />
                <span>{c.name || "—"}</span>
                <span className="muted">{c.email}</span>
              </label>
            ))}
          </div>
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button className="btn btn-primary" onClick={addMembers} disabled={addPicked.length === 0}>添加选中</button>
            <button className="btn" onClick={() => setAddOpen(false)}>取消</button>
          </div>
        </div>
      )}
    </div>
  );
}
