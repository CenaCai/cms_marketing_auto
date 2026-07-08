"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

type Contact = {
  id: string;
  name?: string;
  email?: string;
  phone?: string;
  country?: string;
  city?: string;
  status: string;
  createdAt: string;
};

export default function ContactsPage() {
  const [list, setList] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [formOpen, setFormOpen] = useState(false);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [country, setCountry] = useState("");
  const [city, setCity] = useState("");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  async function load(q = "") {
    setLoading(true);
    try {
      const data = await api<{ items: Contact[]; total: number }>(
        `/api/contacts?limit=200${q ? `&search=${encodeURIComponent(q)}` : ""}`,
      );
      setList(data?.items ?? []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function openNew() {
    setName("");
    setEmail("");
    setPhone("");
    setCountry("");
    setCity("");
    setErr("");
    setFormOpen(true);
  }

  async function save() {
    setErr("");
    if (!email.trim() && !phone.trim()) {
      setErr("至少填写邮箱或电话");
      return;
    }
    setSaving(true);
    try {
      await api("/api/contacts", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim() || undefined,
          email: email.trim() || undefined,
          phone: phone.trim() || undefined,
          country: country.trim() || undefined,
          city: city.trim() || undefined,
        }),
      });
      setFormOpen(false);
      await load(search);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 22 }}>客户名单（邮箱地址）</h1>
        <div style={{ display: "flex", gap: 8 }}>
          <input className="input" style={{ maxWidth: 240 }} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索姓名/邮箱/电话" onKeyDown={(e) => e.key === "Enter" && load(search)} />
          <button className="btn" onClick={() => load(search)}>搜索</button>
          <button className="btn btn-primary" onClick={openNew}>＋ 新增客户</button>
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 24 }} className="muted">加载中…</div>
        ) : list.length === 0 ? (
          <div style={{ padding: 24 }} className="muted">还没有客户，点击“新增客户”录入邮箱。</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                <th style={{ padding: "10px 14px" }}>姓名</th>
                <th style={{ padding: "10px 14px" }}>邮箱</th>
                <th style={{ padding: "10px 14px" }}>电话</th>
                <th style={{ padding: "10px 14px" }}>地区</th>
                <th style={{ padding: "10px 14px" }}>状态</th>
              </tr>
            </thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "10px 14px" }}>{c.name || "—"}</td>
                  <td style={{ padding: "10px 14px" }}>{c.email || "—"}</td>
                  <td style={{ padding: "10px 14px" }}>{c.phone || "—"}</td>
                  <td style={{ padding: "10px 14px" }} className="muted">{[c.city, c.country].filter(Boolean).join(" / ") || "—"}</td>
                  <td style={{ padding: "10px 14px" }}>
                    <span style={{ fontSize: 12, color: c.status === "active" ? "#16a34a" : "#dc2626" }}>{c.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {formOpen && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 16, marginBottom: 12 }}>新增客户</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>姓名</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>邮箱 *</label>
              <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="customer@example.com" />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>电话</label>
              <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>城市</label>
              <input className="input" value={city} onChange={(e) => setCity(e.target.value)} />
            </div>
          </div>
          {err && <div style={{ color: "red", fontSize: 13, marginTop: 8 }}>{err}</div>}
          <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
            <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? "保存中…" : "保存客户"}</button>
            <button className="btn" onClick={() => setFormOpen(false)}>取消</button>
          </div>
        </div>
      )}
    </div>
  );
}
