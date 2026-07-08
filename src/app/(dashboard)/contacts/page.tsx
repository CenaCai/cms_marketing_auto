"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

export default function ContactsPage() {
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [form, setForm] = useState({ name: "", email: "", phone: "", country: "", city: "" });

  async function load() {
    const res = await api("/api/contacts?limit=100");
    setItems(res.items);
    setTotal(res.total);
  }

  useEffect(() => {
    load().catch(() => {});
  }, []);

  async function add() {
    if (!form.email && !form.phone) return alert("邮箱或手机号至少填一个");
    await api("/api/contacts", { method: "POST", body: JSON.stringify(form) });
    setForm({ name: "", email: "", phone: "", country: "", city: "" });
    load();
  }

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: 4 }}>Contacts</h1>
      <div className="muted" style={{ fontSize: 13, marginBottom: 16 }}>共 {total} 条</div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input className="input" style={{ flex: 1, minWidth: 120 }} placeholder="姓名" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input className="input" style={{ flex: 1, minWidth: 120 }} placeholder="邮箱" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input className="input" style={{ flex: 1, minWidth: 120 }} placeholder="手机" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          <input className="input" style={{ width: 100 }} placeholder="国家" value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })} />
          <input className="input" style={{ width: 100 }} placeholder="城市" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
          <button className="btn btn-primary" onClick={add}>新增</button>
        </div>
      </div>

      <div className="card">
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid var(--border)" }}>
              <th style={{ padding: 8 }}>姓名</th>
              <th style={{ padding: 8 }}>邮箱</th>
              <th style={{ padding: 8 }}>手机</th>
              <th style={{ padding: 8 }}>国家/城市</th>
              <th style={{ padding: 8 }}>状态</th>
            </tr>
          </thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.id} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: 8 }}>{c.name ?? "—"}</td>
                <td style={{ padding: 8 }}>{c.email ?? "—"}</td>
                <td style={{ padding: 8 }}>{c.phone ?? "—"}</td>
                <td style={{ padding: 8 }}>{c.country ?? "—"} / {c.city ?? "—"}</td>
                <td style={{ padding: 8 }}>{c.status}</td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={5} style={{ padding: 16 }} className="muted">暂无联系人</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
