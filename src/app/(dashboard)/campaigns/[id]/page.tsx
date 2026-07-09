"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api-client";

type Tpl = { id: string; name: string; subject?: string };
type Tag = { id: string; name: string };
type Contact = { id: string; name?: string; email?: string; phone?: string };
type Campaign = {
  id: string;
  name: string;
  objective?: string;
  channel: string;
  status: string;
  segmentId?: string | null;
  templateId?: string | null;
  template?: Tpl | null;
  scheduledAt?: string;
  createdAt: string;
  activity?: string | null;
  country?: string | null;
  language?: string | null;
  channels?: string | null;
  edmTemplateId?: string | null;
  smsTemplateId?: string | null;
  landingPageId?: string | null;
  landingUrl?: string | null;
  audienceType?: string | null;
  tagIds?: string | null;
  sqlQuery?: string | null;
};

const CHANNEL_LABEL: Record<string, string> = { EMAIL: "📧 邮件 EDM", SMS: "💬 短信 SMS" };
const STATUS_COLOR: Record<string, string> = { draft: "#64748b", scheduled: "#d97706", sending: "#2563eb", sent: "#16a34a", paused: "#64748b", failed: "#dc2626", completed: "#16a34a" };

export default function CampaignDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [c, setC] = useState<Campaign | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const [contacts, setContacts] = useState<Contact[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [tplMap, setTplMap] = useState<Record<string, string>>({});
  const [sendOpen, setSendOpen] = useState(false);
  const [sendMode, setSendMode] = useState<"contacts" | "tags">("contacts");
  const [picked, setPicked] = useState<string[]>([]);
  const [pickedTags, setPickedTags] = useState<string[]>([]);
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<{ taskId: string; totalCount: number } | null>(null);
  const [logs, setLogs] = useState<{ id: string; status: string; errorMessage?: string; sentAt?: string }[]>([]);

  async function load() {
    setLoading(true);
    try {
      const [camp, ct, tg, edm, sms, lp] = await Promise.all([
        api<Campaign>(`/api/campaigns/${id}`),
        api<{ items: Contact[] }>("/api/contacts?limit=500"),
        api<Tag[]>("/api/tags"),
        api<Tpl[]>("/api/templates?type=EDM"),
        api<Tpl[]>("/api/templates?type=SMS"),
        api<Tpl[]>("/api/templates?type=LANDING"),
      ]);
      setC(camp);
      setContacts((ct?.items ?? []).filter((x) => (camp.channel === "SMS" ? x.phone : x.email)));
      setTags(tg ?? []);
      const map: Record<string, string> = {};
      [...(edm ?? []), ...(sms ?? []), ...(lp ?? [])].forEach((t) => { map[t.id] = t.name; });
      setTplMap(map);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { if (id) load(); }, [id]);

  function toggle(idv: string) { setPicked((p) => (p.includes(idv) ? p.filter((x) => x !== idv) : [...p, idv])); }
  function toggleTag(idv: string) { setPickedTags((p) => (p.includes(idv) ? p.filter((x) => x !== idv) : [...p, idv])); }
  function selectAll() { setPicked(contacts.map((x) => x.id)); }

  async function doSend() {
    if (!c) return;
    const body: Record<string, unknown> = { channel: c.channel };
    if (sendMode === "contacts") {
      if (picked.length === 0) return setErr("请至少选择一个收件人");
      body.contactIds = picked;
    } else {
      if (pickedTags.length === 0) return setErr("请至少选择一个标签");
      body.tagIds = pickedTags;
    }
    setSending(true);
    setErr("");
    try {
      const res = await api<{ taskId: string; totalCount: number }>(`/api/campaigns/${c.id}/send`, { method: "POST", body: JSON.stringify(body) });
      setSendResult(res);
      setC({ ...c, status: "sending" });
      setTimeout(() => refreshLogs(res.taskId), 1200);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSending(false);
    }
  }
  async function refreshLogs(taskId: string) {
    try {
      const data = await api<{ logs: { id: string; status: string; errorMessage?: string; sentAt?: string }[] }>(`/api/send/tasks/${taskId}`);
      setLogs(data?.logs ?? []);
    } catch { /* ignore */ }
  }

  if (loading) return <div className="muted" style={{ padding: 24 }}>加载中…</div>;
  if (err && !c) return <div style={{ color: "red", padding: 24 }}>{err}</div>;
  if (!c) return <div className="muted" style={{ padding: 24 }}>活动不存在</div>;

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Link href="/campaigns" className="btn">← 返回活动列表</Link>
      </div>

      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h1 style={{ fontSize: 22, margin: 0 }}>{c.name}</h1>
            <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>{c.objective || "无活动目标"}</div>
          </div>
          <span style={{ fontSize: 13, color: STATUS_COLOR[c.status] || "#64748b", border: `1px solid ${STATUS_COLOR[c.status] || "#64748b"}`, padding: "3px 10px", borderRadius: 999 }}>{c.status}</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginTop: 16 }}>
          <Field label="渠道" value={CHANNEL_LABEL[c.channel] || c.channel} />
          <Field label="绑定模板" value={c.template?.name || "未绑定"} />
          <Field label="排期" value={c.scheduledAt ? new Date(c.scheduledAt).toLocaleString() : "草稿（随时发送）"} />
          <Field label="创建时间" value={new Date(c.createdAt).toLocaleString()} />
        </div>
        <div style={{ marginTop: 16 }}>
          <button className="btn btn-primary" onClick={() => { setSendOpen((v) => !v); setSendResult(null); setLogs([]); setErr(""); }}>✉ 发送</button>
        </div>
      </div>

      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 12 }}>配置概览</h2>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
          <Field label="活动 / IP" value={c.activity || "—"} />
          <Field label="目标国家" value={c.country || "—"} />
          <Field label="目标语言" value={c.language || "—"} />
          <Field label="渠道" value={(c.channels ? JSON.parse(c.channels) : [c.channel]).map((x: string) => (x === "EMAIL" ? "EDM" : "SMS")).join(" + ") || "—"} />
          <Field label="EDM 模板" value={c.edmTemplateId ? (tplMap[c.edmTemplateId] ?? "—") : "—"} />
          <Field label="SMS 模板" value={c.smsTemplateId ? (tplMap[c.smsTemplateId] ?? "—") : "—"} />
          <Field label="落地页" value={c.landingPageId ? (tplMap[c.landingPageId] ?? "—") : (c.landingUrl || "—")} />
          <Field label="跳转链接" value={c.landingUrl || "—"} />
          <Field label="圈人方式" value={c.audienceType === "segment" ? "分群" : c.audienceType === "tags" ? "标签组合" : c.audienceType === "sql" ? "SQL 圈人" : "—"} />
        </div>
      </div>

      {sendOpen && (
        <div className="card" style={{ padding: 20 }}>
          <h2 style={{ fontSize: 16, marginBottom: 8 }}>发送：{c.name}</h2>
          <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>模板：{c.template?.name || "未绑定"}。可「按收件人」多选 / 一键全选，或「按标签」批量发送。</p>

          <div style={{ display: "flex", gap: 8, margin: "10px 0" }}>
            <button className="btn" style={{ background: sendMode === "contacts" ? "var(--brand)" : "#fff", color: sendMode === "contacts" ? "#fff" : "var(--text)" }} onClick={() => setSendMode("contacts")}>按收件人</button>
            <button className="btn" style={{ background: sendMode === "tags" ? "var(--brand)" : "#fff", color: sendMode === "tags" ? "#fff" : "var(--text)" }} onClick={() => setSendMode("tags")}>按标签</button>
          </div>

          {sendMode === "contacts" ? (
            <>
              <div style={{ marginBottom: 8, display: "flex", alignItems: "center", gap: 12 }}>
                <label style={{ fontSize: 13 }}><input type="checkbox" checked={picked.length === contacts.length && contacts.length > 0} onChange={selectAll} /> 一键全选（{contacts.length} 人）</label>
                <span className="muted" style={{ fontSize: 13 }}>已选 {picked.length} 人</span>
              </div>
              <div style={{ maxHeight: 240, overflow: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
                {contacts.length === 0 ? (
                  <div style={{ padding: 16 }} className="muted">暂无带联系方式的客户，请先到「客户名单」添加。</div>
                ) : contacts.map((x) => (
                  <label key={x.id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 12px", borderBottom: "1px solid var(--border)", fontSize: 14 }}>
                    <input type="checkbox" checked={picked.includes(x.id)} onChange={() => toggle(x.id)} />
                    <span>{x.name || "—"}</span>
                    <span className="muted">{c.channel === "SMS" ? x.phone : x.email}</span>
                  </label>
                ))}
              </div>
            </>
          ) : (
            <>
              <p className="muted" style={{ fontSize: 13, marginBottom: 8 }}>勾选标签，将向「拥有任一所选标签」的客户批量发送（并集）：</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {tags.length === 0 ? <span className="muted">暂无标签</span> : tags.map((t) => (
                  <label key={t.id} style={{ fontSize: 14, border: "1px solid var(--border)", padding: "6px 10px", borderRadius: 8, background: pickedTags.includes(t.id) ? "#eef2ff" : "#fff" }}>
                    <input type="checkbox" checked={pickedTags.includes(t.id)} onChange={() => toggleTag(t.id)} /> {t.name}
                  </label>
                ))}
              </div>
              <div style={{ marginTop: 8, fontSize: 13 }} className="muted">已选 {pickedTags.length} 个标签</div>
            </>
          )}

          {err && <div style={{ color: "red", fontSize: 13, marginTop: 8 }}>{err}</div>}

          <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
            <button className="btn btn-primary" onClick={doSend} disabled={sending}>
              {sending ? "发送中…" : sendMode === "contacts" ? `发送（${picked.length} 人）` : `按标签发送（${pickedTags.length} 个）`}
            </button>
            {sendResult && <span className="muted" style={{ fontSize: 13 }}>已入队 {sendResult.totalCount} 封，任务 {sendResult.taskId.slice(0, 8)}…</span>}
          </div>

          {logs.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <h3 style={{ fontSize: 14, marginBottom: 8 }}>发送记录</h3>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <tbody>
                  {logs.map((l) => (
                    <tr key={l.id} style={{ borderTop: "1px solid var(--border)" }}>
                      <td style={{ padding: "6px 10px" }}><span style={{ color: l.status === "success" ? "#16a34a" : l.status === "failed" ? "#dc2626" : "#64748b" }}>{l.status}</span></td>
                      <td style={{ padding: "6px 10px" }} className="muted">{l.errorMessage || (l.sentAt ? new Date(l.sentAt).toLocaleString() : "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="btn" style={{ marginTop: 8 }} onClick={() => sendResult && refreshLogs(sendResult.taskId)}>刷新记录</button>
            </div>
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
