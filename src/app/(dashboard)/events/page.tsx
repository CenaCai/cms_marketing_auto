"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
import { EVENT_TYPES, eventMeta, resolveEventType } from "@/lib/event-types";

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
  // 用标准 eventType 去重，保证筛选按钮与展示名一致
  const types = Array.from(new Set(events.map((e) => resolveEventType(e.eventType, e.eventName))));
  const shown = filter ? events.filter((e) => resolveEventType(e.eventType, e.eventName) === filter) : events;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, flexWrap: "wrap", gap: 8 }}>
        <h1 style={{ fontSize: 22, margin: 0 }}>事件中心</h1>
        <span className="muted" style={{ fontSize: 13 }}>事件由 API / Webhook / SDK 写入，触发自动化工作流</span>
      </div>

      {/* 默认事件图例 */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        {EVENT_TYPES.filter((e) => e.type !== "CUSTOM").map((t) => (
          <span key={t.type} title={t.type} style={{ fontSize: 12, color: t.color, border: `1px solid ${t.color}`, padding: "2px 8px", borderRadius: 999 }}>
            {t.icon} {t.label}
          </span>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <button className="btn" style={{ background: filter === "" ? "var(--brand)" : "#fff", color: filter === "" ? "#fff" : "var(--text)" }} onClick={() => setFilter("")}>全部</button>
        {types.map((t) => {
          const meta = eventMeta(t);
          return (
            <button key={t} className="btn" style={{ background: filter === t ? meta.color : "#fff", color: filter === t ? "#fff" : "var(--text)", borderColor: meta.color }} onClick={() => setFilter(t)}>
              {meta.icon} {meta.label}
            </button>
          );
        })}
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
                <th style={{ padding: "10px 14px" }}>事件名 (event_name)</th>
                <th style={{ padding: "10px 14px" }}>类型 (event_type)</th>
                <th style={{ padding: "10px 14px" }}>联系人 (contact)</th>
                <th style={{ padding: "10px 14px" }}>来源 (source)</th>
                <th style={{ padding: "10px 14px", maxWidth: 260 }}>属性 (properties)</th>
                <th style={{ padding: "10px 14px" }}>发生时间 (occurred_at)</th>
              </tr>
            </thead>
            <tbody>
              {shown.slice(0, 300).map((e) => {
                const meta = eventMeta(resolveEventType(e.eventType, e.eventName));
                return (
                  <tr key={e.id} style={{ borderTop: "1px solid var(--border)" }}>
                    <td style={{ padding: "10px 14px" }}>{e.eventName}</td>
                    <td style={{ padding: "10px 14px" }}>
                      <span style={{ fontSize: 11, background: "#eef2ff", color: meta.color, padding: "2px 8px", borderRadius: 6 }}>{meta.icon} {meta.label}</span>
                    </td>
                    <td style={{ padding: "10px 14px" }} className="muted">
                      {e.contactId ? (nameMap.get(e.contactId) || e.contactId) : "（无关联）"}
                    </td>
                    <td style={{ padding: "10px 14px" }} className="muted">{e.source || "—"}</td>
                    <td style={{ padding: "10px 14px", maxWidth: 260 }} className="muted">
                      {e.properties ? (
                        <span title={e.properties} style={{ fontFamily: "monospace", fontSize: 12, display: "block", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                          {e.properties}
                        </span>
                      ) : "—"}
                    </td>
                    <td style={{ padding: "10px 14px" }} className="muted">{new Date(e.occurredAt).toLocaleString()}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
