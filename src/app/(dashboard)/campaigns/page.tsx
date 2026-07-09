"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api-client";

type Tpl = { id: string; name: string; subject?: string };
type Tag = { id: string; name: string };
type Contact = { id: string; name?: string; email?: string };
type Campaign = {
  id: string;
  name: string;
  channel: string;
  status: string;
  template?: Tpl | null;
  _count?: { sendTasks: number };
  createdAt: string;
};
type SendLog = {
  id: string;
  contactId?: string;
  channel: string;
  status: string;
  errorMessage?: string;
  sentAt?: string;
};

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [templates, setTemplates] = useState<Tpl[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(true);

  const [err, setErr] = useState("");

  // 发送弹窗
  const [sendOpen, setSendOpen] = useState(false);
  const [sendCampaign, setSendCampaign] = useState<Campaign | null>(null);
  const [sendMode, setSendMode] = useState<"contacts" | "tags">("contacts");
  const [picked, setPicked] = useState<string[]>([]); // 按收件人
  const [pickedTags, setPickedTags] = useState<string[]>([]); // 按标签
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<{ taskId: string; totalCount: number } | null>(null);
  const [logs, setLogs] = useState<SendLog[]>([]);

  async function loadAll() {
    setLoading(true);
    try {
      const [cs, ts, cts, tg] = await Promise.all([
        api<Campaign[]>("/api/campaigns"),
        api<Tpl[]>("/api/templates?type=EDM"),
        api<{ items: Contact[] }>("/api/contacts?limit=500"),
        api<Tag[]>("/api/tags"),
      ]);
      setCampaigns(cs ?? []);
      setTemplates(ts ?? []);
      setContacts((cts?.items ?? []).filter((c) => c.email));
      setTags(tg ?? []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  function openSend(c: Campaign) {
    setSendCampaign(c);
    setSendMode("contacts");
    setPicked([]);
    setPickedTags([]);
    setSendResult(null);
    setLogs([]);
    setErr("");
    setSendOpen(true);
  }

  function toggle(id: string) {
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  }
  function toggleTag(id: string) {
    setPickedTags((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  }
  function selectAllContacts() {
    setPicked(contacts.map((c) => c.id));
  }

  async function doSend() {
    if (!sendCampaign) return;
    const body: Record<string, unknown> = { channel: "EMAIL" };
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
      const res = await api<{ taskId: string; totalCount: number }>(
        `/api/campaigns/${sendCampaign.id}/send`,
        { method: "POST", body: JSON.stringify(body) },
      );
      setSendResult(res);
      setTimeout(() => refreshLogs(res.taskId), 1200);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSending(false);
    }
  }

  async function refreshLogs(taskId: string) {
    try {
      const data = await api<{ logs: SendLog[] }>(`/api/send/tasks/${taskId}`);
      setLogs(data?.logs ?? []);
    } catch {
      /* ignore */
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 22 }}>营销活动（发送邮件）</h1>
        <Link href="/campaigns/new" className="btn btn-primary">＋ 向导新建</Link>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 24 }} className="muted">加载中…</div>
        ) : campaigns.length === 0 ? (
          <div style={{ padding: 24 }} className="muted">还没有活动。新建一个活动并绑定模板后即可发送。</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                <th style={{ padding: "10px 14px" }}>活动</th>
                <th style={{ padding: "10px 14px" }}>渠道</th>
                <th style={{ padding: "10px 14px" }}>模板</th>
                <th style={{ padding: "10px 14px" }}>状态</th>
                <th style={{ padding: "10px 14px" }}></th>
              </tr>
            </thead>
            <tbody>
                {campaigns.map((c) => (
                  <tr key={c.id} style={{ borderTop: "1px solid var(--border)" }}>
                    <td style={{ padding: "10px 14px" }}><Link href={`/campaigns/${c.id}`} style={{ color: "var(--brand)", textDecoration: "none" }}>{c.name}</Link></td>
                  <td style={{ padding: "10px 14px" }}>{c.channel}</td>
                  <td style={{ padding: "10px 14px" }} className="muted">{c.template?.name || "未绑定"}</td>
                  <td style={{ padding: "10px 14px" }}>
                    <span style={{ fontSize: 12, color: c.status === "sending" ? "#2563eb" : c.status === "sent" ? "#16a34a" : "#64748b" }}>{c.status}</span>
                  </td>
                  <td style={{ padding: "10px 14px", textAlign: "right" }}>
                    <button className="btn btn-primary" onClick={() => openSend(c)}>发送</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 发送弹窗 */}
      {sendOpen && sendCampaign && (
        <div className="card" style={{ marginTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ fontSize: 16 }}>发送：{sendCampaign.name}</h2>
            <button className="btn" onClick={() => setSendOpen(false)}>关闭</button>
          </div>
          <p className="muted" style={{ fontSize: 13, marginTop: 4 }}>
            模板：{sendCampaign.template?.name || "未绑定"}。可「按收件人」多选 / 一键全选，或「按标签」批量发送。
          </p>

          <div style={{ display: "flex", gap: 8, margin: "10px 0" }}>
            <button className="btn" style={{ background: sendMode === "contacts" ? "var(--brand)" : "#fff", color: sendMode === "contacts" ? "#fff" : "var(--text)" }} onClick={() => setSendMode("contacts")}>按收件人</button>
            <button className="btn" style={{ background: sendMode === "tags" ? "var(--brand)" : "#fff", color: sendMode === "tags" ? "#fff" : "var(--text)" }} onClick={() => setSendMode("tags")}>按标签</button>
          </div>

          {sendMode === "contacts" ? (
            <>
              <div style={{ marginBottom: 8, display: "flex", alignItems: "center", gap: 12 }}>
                <label style={{ fontSize: 13 }}>
                  <input type="checkbox" checked={picked.length === contacts.length && contacts.length > 0} onChange={selectAllContacts} /> 一键全选（{contacts.length} 人）
                </label>
                <span className="muted" style={{ fontSize: 13 }}>已选 {picked.length} 人</span>
              </div>
              <div style={{ maxHeight: 240, overflow: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
                {contacts.length === 0 ? (
                  <div style={{ padding: 16 }} className="muted">暂无带邮箱的客户，请先到“客户名单”添加。</div>
                ) : (
                  contacts.map((c) => (
                    <label key={c.id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 12px", borderBottom: "1px solid var(--border)", fontSize: 14 }}>
                      <input type="checkbox" checked={picked.includes(c.id)} onChange={() => toggle(c.id)} />
                      <span>{c.name || "—"}</span>
                      <span className="muted">{c.email}</span>
                    </label>
                  ))
                )}
              </div>
            </>
          ) : (
            <>
              <p className="muted" style={{ fontSize: 13, marginBottom: 8 }}>勾选标签，将向「拥有任一所选标签」的客户批量发送（并集）：</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {tags.length === 0 ? (
                  <span className="muted">暂无标签，请先到「标签」页创建。</span>
                ) : (
                  tags.map((t) => (
                    <label key={t.id} style={{ fontSize: 14, border: "1px solid var(--border)", padding: "6px 10px", borderRadius: 8, background: pickedTags.includes(t.id) ? "#eef2ff" : "#fff" }}>
                      <input type="checkbox" checked={pickedTags.includes(t.id)} onChange={() => toggleTag(t.id)} /> {t.name}
                    </label>
                  ))
                )}
              </div>
              <div style={{ marginTop: 8, fontSize: 13 }} className="muted">已选 {pickedTags.length} 个标签</div>
            </>
          )}

          {err && <div style={{ color: "red", fontSize: 13, marginTop: 8 }}>{err}</div>}

          <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
            <button className="btn btn-primary" onClick={doSend} disabled={sending}>
              {sending ? "发送中…" : sendMode === "contacts" ? `发送（${picked.length} 人）` : `按标签发送（${pickedTags.length} 个）`}
            </button>
            {sendResult && (
              <span className="muted" style={{ fontSize: 13 }}>已入队 {sendResult.totalCount} 封，任务 {sendResult.taskId.slice(0, 8)}…</span>
            )}
          </div>

          {logs.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <h3 style={{ fontSize: 14, marginBottom: 8 }}>发送记录</h3>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                    <th style={{ padding: "6px 10px" }}>状态</th>
                    <th style={{ padding: "6px 10px" }}>说明</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((l) => (
                    <tr key={l.id} style={{ borderTop: "1px solid var(--border)" }}>
                      <td style={{ padding: "6px 10px" }}>
                        <span style={{ color: l.status === "success" ? "#16a34a" : l.status === "failed" ? "#dc2626" : "#64748b" }}>{l.status}</span>
                      </td>
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
