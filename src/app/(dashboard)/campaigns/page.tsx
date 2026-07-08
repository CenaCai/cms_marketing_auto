"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

export default function CampaignsPage() {
  const [items, setItems] = useState<any[]>([]);
  const [form, setForm] = useState({ name: "", channel: "EMAIL", segmentId: "", templateId: "" });

  async function load() {
    const res = await api("/api/campaigns");
    setItems(res);
  }
  useEffect(() => { load().catch(() => {}); }, []);

  async function create() {
    if (!form.name) return alert("请填写名称");
    await api("/api/campaigns", { method: "POST", body: JSON.stringify(form) });
    setForm({ name: "", channel: "EMAIL", segmentId: "", templateId: "" });
    load();
  }

  async function send(id: string) {
    const channel = prompt("发送渠道 (EMAIL/SMS)", "EMAIL");
    if (!channel) return;
    await api(`/api/campaigns/${id}/send`, {
      method: "POST",
      body: JSON.stringify({ channel }),
    });
    alert("已创建批量发送任务（开发模式走 mock provider）");
  }

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: 16 }}>Campaigns</h1>
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input className="input" style={{ flex: 2, minWidth: 160 }} placeholder="Campaign 名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select className="input" style={{ width: 120 }} value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })}>
            <option value="EMAIL">EMAIL</option>
            <option value="SMS">SMS</option>
          </select>
          <input className="input" style={{ flex: 1, minWidth: 120 }} placeholder="Segment ID" value={form.segmentId} onChange={(e) => setForm({ ...form, segmentId: e.target.value })} />
          <button className="btn btn-primary" onClick={create}>创建</button>
        </div>
      </div>
      <div className="card">
        {items.map((c) => (
          <div key={c.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
            <div>
              <div style={{ fontWeight: 600 }}>{c.name}</div>
              <div className="muted" style={{ fontSize: 13 }}>{c.channel} · {c.status}</div>
            </div>
            <button className="btn" onClick={() => send(c.id)}>发送</button>
          </div>
        ))}
        {items.length === 0 && <div className="muted" style={{ padding: 16 }}>暂无 Campaign</div>}
      </div>
    </div>
  );
}
