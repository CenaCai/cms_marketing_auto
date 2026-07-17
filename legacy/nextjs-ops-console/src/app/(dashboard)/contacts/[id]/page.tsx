"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api-client";
import { eventMeta, resolveEventType } from "@/lib/event-types";

type Tag = { id: string; name: string; color?: string };
type Segment = { id: string; name: string };
type Channel = { channel: string; identifier: string; verified: boolean; consentStatus: string };
type Ev = {
  id: string;
  eventName: string;
  eventType: string;
  source?: string;
  properties?: string;
  occurredAt: string;
};
type CustomValue = { field?: { fieldLabel?: string }; value?: string | null };

type Contact = {
  id: string;
  name?: string;
  email?: string;
  phone?: string;
  country?: string;
  city?: string;
  language?: string;
  source?: string;
  status: string;
  createdAt: string;
  lastActiveAt?: string;
  contactTags: { tag: Tag }[];
  contactSegments: { segment: Segment }[];
  channels: Channel[];
  events: Ev[];
  customValues: CustomValue[];
};

const STATUS_COLOR: Record<string, string> = {
  active: "#16a34a",
  unsubscribed: "#d97706",
  bounced: "#dc2626",
  blacklisted: "#dc2626",
};

export default function ContactDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [c, setC] = useState<Contact | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<"profile" | "timeline">("profile");

  useEffect(() => {
    if (!id) return;
    (async () => {
      setLoading(true);
      try {
        const data = await api<Contact>(`/api/contacts/${id}`);
        setC(data);
      } catch (e: any) {
        setErr(e.message || "加载失败");
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  if (loading) return <div className="muted" style={{ padding: 24 }}>加载中…</div>;
  if (err) return <div style={{ color: "red", padding: 24 }}>{err}</div>;
  if (!c) return <div className="muted" style={{ padding: 24 }}>联系人不存在</div>;

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Link href="/contacts" className="btn">← 返回客户名单</Link>
      </div>

      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h1 style={{ fontSize: 22, margin: 0 }}>{c.name || "（未命名）"}</h1>
            <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
              {c.email || "无邮箱"} · {c.phone || "无电话"}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 13, color: STATUS_COLOR[c.status] || "#64748b", border: `1px solid ${STATUS_COLOR[c.status] || "#64748b"}`, padding: "3px 10px", borderRadius: 999 }}>
              {c.status}
            </span>
            <Link href={`/contacts/import`} className="btn">编辑资料</Link>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          {c.contactTags.map((t) => (
            <span key={t.tag.id} style={{ fontSize: 12, background: t.tag.color || "#eef2ff", color: "#1e3a8a", padding: "3px 10px", borderRadius: 999 }}>
              {t.tag.name}
            </span>
          ))}
          {c.contactTags.length === 0 && <span className="muted" style={{ fontSize: 13 }}>暂无标签</span>}
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          {c.contactSegments.map((s) => (
            <span key={s.segment.id} style={{ fontSize: 12, background: "#ecfdf5", color: "#065f46", padding: "3px 10px", borderRadius: 999 }}>
              #{s.segment.name}
            </span>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button className="btn" style={{ background: tab === "profile" ? "var(--brand)" : "#fff", color: tab === "profile" ? "#fff" : "var(--text)" }} onClick={() => setTab("profile")}>资料</button>
        <button className="btn" style={{ background: tab === "timeline" ? "var(--brand)" : "#fff", color: tab === "timeline" ? "#fff" : "var(--text)" }} onClick={() => setTab("timeline")}>行为时间线（{c.events.length}）</button>
      </div>

      {tab === "profile" ? (
        <div className="card" style={{ padding: 20 }}>
          <h2 style={{ fontSize: 16, marginBottom: 12 }}>基础字段</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="姓名" value={c.name} />
            <Field label="邮箱" value={c.email} />
            <Field label="电话" value={c.phone} />
            <Field label="国家" value={c.country} />
            <Field label="城市" value={c.city} />
            <Field label="语言" value={c.language} />
            <Field label="来源" value={c.source} />
            <Field label="最近活跃" value={c.lastActiveAt ? new Date(c.lastActiveAt).toLocaleString() : "—"} />
            <Field label="创建时间" value={new Date(c.createdAt).toLocaleString()} />
          </div>

          <h2 style={{ fontSize: 16, margin: "20px 0 12px" }}>触达渠道</h2>
          {c.channels.length === 0 ? (
            <div className="muted" style={{ fontSize: 13 }}>暂无多渠道标识</div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead>
                <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                  <th style={{ padding: "8px 12px" }}>渠道</th>
                  <th style={{ padding: "8px 12px" }}>标识</th>
                  <th style={{ padding: "8px 12px" }}>授权</th>
                </tr>
              </thead>
              <tbody>
                {c.channels.map((ch, i) => (
                  <tr key={i} style={{ borderTop: "1px solid var(--border)" }}>
                    <td style={{ padding: "8px 12px" }}>{ch.channel}</td>
                    <td style={{ padding: "8px 12px" }}>{ch.identifier}</td>
                    <td style={{ padding: "8px 12px" }} className="muted">{ch.consentStatus}{ch.verified ? " · 已验证" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {c.customValues.length > 0 && (
            <>
              <h2 style={{ fontSize: 16, margin: "20px 0 12px" }}>自定义字段</h2>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                {c.customValues.map((cv, i) => (
                  <Field key={i} label={cv.field?.fieldLabel || "字段"} value={cv.value || "—"} />
                ))}
              </div>
            </>
          )}
        </div>
      ) : (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          {c.events.length === 0 ? (
            <div style={{ padding: 24 }} className="muted">暂无行为事件。可通过 API / Webhook 写入事件，或在工作流中触发。</div>
          ) : (
            <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
              {c.events.map((e) => {
                const meta = eventMeta(resolveEventType(e.eventType, e.eventName));
                return (
                <li key={e.id} style={{ display: "flex", gap: 12, padding: "12px 16px", borderBottom: "1px solid var(--border)", borderLeft: `3px solid ${meta.color}` }}>
                  <div style={{ minWidth: 110 }}>
                    <span style={{ fontSize: 12, color: meta.color }}>{meta.icon} {meta.label}</span>
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14 }}>{e.eventName}</div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {e.source ? `来源 ${e.source} · ` : ""}
                      {new Date(e.occurredAt).toLocaleString()}
                      {e.properties ? (
                        <span title={e.properties} style={{ fontFamily: "monospace", display: "block", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 360 }}>
                          {e.properties}
                        </span>
                      ) : null}
                    </div>
                  </div>
                </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <label className="muted" style={{ fontSize: 13 }}>{label}</label>
      <div style={{ fontSize: 14, marginTop: 2 }}>{value || "—"}</div>
    </div>
  );
}
