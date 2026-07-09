"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

type Ev = {
  id: string;
  contactId?: string | null;
  eventName: string;
  eventType: string;
  source?: string;
  properties?: string;
  occurredAt: string;
};
type Contact = { id: string; name?: string; email?: string };

const TYPE_COLOR: Record<string, string> = {
  REGISTER: "#0891b2",
  LOGIN: "#0891b2",
  BROWSE: "#7c3aed",
  PURCHASE: "#16a34a",
  REFUND: "#dc2626",
  CUSTOM: "#64748b",
};

export default function EventsPage() {
  const [events, setEvents] = useState<Ev[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  async function load() {
    setLoading(true);
    try {
      const [ev, ct] = await Promise.all([
        api<Ev[]>("/api/events?limit=500"),
        api<{ items: Contact[] }>("/api/contacts?limit=2000"),
      ]);
      setEvents(ev ?? []);
      setContacts(ct?.items ?? []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const nameMap = new Map(contacts.map((c) => [c.id, c.name || c.email || c.id]));
  const types = Array.from(new Set(events.map((e) => e.eventType)));
  const shown = filter ? events.filter((e) => e.eventType === filter) : events;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 22 }}>事件中心</h1>
        <span className="muted" style={{ fontSize: 13 }}>事件由 API / Webhook / SDK 写入，触发自动化工作流</span>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <button className="btn" style={{ background: filter === "" ? "var(--brand)" : "#fff", color: filter === "" ? "#fff" : "var(--text)" }} onClick={() => setFilter("")}>全部</button>
        {types.map((t) => (
          <button key={t} className="btn" style={{ background: filter === t ? "var(--brand)" : "#fff", color: filter === t ? "#fff" : "var(--text)" }} onClick={() => setFilter(t)}>{t}</button>
        ))}
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 24 }} className="muted">加载中…</div>
        ) : shown.length === 0 ? (
          <div style={{ padding: 24 }} className="muted">暂无事件。可通过 POST /api/events 写入，或在联系人详情查看时间线。</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                <th style={{ padding: "10px 14px" }}>类型</th>
                <th style={{ padding: "10px 14px" }}>事件名</th>
                <th style={{ padding: "10px 14px" }}>联系人</th>
                <th style={{ padding: "10px 14px" }}>来源</th>
                <th style={{ padding: "10px 14px" }}>时间</th>
              </tr>
            </thead>
            <tbody>
              {shown.slice(0, 300).map((e) => (
                <tr key={e.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "10px 14px" }}>
                    <span style={{ fontSize: 11, background: "#eef2ff", color: TYPE_COLOR[e.eventType] || "#1e3a8a", padding: "2px 8px", borderRadius: 6 }}>{e.eventType}</span>
                  </td>
                  <td style={{ padding: "10px 14px" }}>{e.eventName}</td>
                  <td style={{ padding: "10px 14px" }} className="muted">
                    {e.contactId ? (nameMap.get(e.contactId) || e.contactId) : "（无关联）"}
                  </td>
                  <td style={{ padding: "10px 14px" }} className="muted">{e.source || "—"}</td>
                  <td style={{ padding: "10px 14px" }} className="muted">{new Date(e.occurredAt).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
