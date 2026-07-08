"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

type Tpl = { id: string; name: string; subject?: string };
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
  const [loading, setLoading] = useState(true);

  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  // 发送弹窗
  const [sendOpen, setSendOpen] = useState(false);
  const [sendCampaign, setSendCampaign] = useState<Campaign | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<{ taskId: string; totalCount: number } | null>(null);
  const [logs, setLogs] = useState<SendLog[]>([]);

  async function loadAll() {
    setLoading(true);
    try {
      const [cs, ts, cts] = await Promise.all([
        api<Campaign[]>("/api/campaigns"),
        api<Tpl[]>("/api/templates?type=EDM"),
        api<{ items: Contact[] }>("/api/contacts?limit=500"),
      ]);
      setCampaigns(cs ?? []);
      setTemplates(ts ?? []);
      setContacts((cts?.items ?? []).filter((c) => c.email));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  function openNew() {
    setName("");
    setTemplateId(templates[0]?.id ?? "");
    setErr("");
    setFormOpen(true);
  }

  async function createCampaign() {
    setErr("");
    if (!name.trim()) return setErr("请填写活动名称");
    setSaving(true);
    try {
      await api("/api/campaigns", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), channel: "EMAIL", templateId: templateId || undefined }),
      });
      setFormOpen(false);
      await loadAll();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  function openSend(c: Campaign) {
    setSendCampaign(c);
    setPicked([]);
    setSendResult(null);
    setLogs([]);
    setErr("");
    setSendOpen(true);
  }

  async function doSend() {
    if (!sendCampaign) return;
    if (picked.length === 0) return setErr("请至少选择一个收件人");
    setSending(true);
    setErr("");
    try {
      const res = await api<{ taskId: string; totalCount: number }>(
        `/api/campaigns/${sendCampaign.id}/send`,
        { method: "POST", body: JSON.stringify({ channel: "EMAIL", contactIds: picked }) },
      );
      setSendResult(res);
      // 稍等队列处理，再拉取发送记录
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

  function toggle(id: string) {
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 22 }}>营销活动（发送邮件）</h1>
        <button className="btn btn-primary" onClick={openNew}>＋ 新建活动</button>
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
                  <td style={{ padding: "10px 14px" }}>{c.name}</td>
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

      {/* 新建活动 */}
      {formOpen && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 16, marginBottom: 12 }}>新建活动</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>活动名称</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="如：618 大促 EDM" />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>绑定模板</label>
              <select className="input" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                <option value="">（不绑定，仅建活动）</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
          </div>
          {err && <div style={{ color: "red", fontSize: 13, marginTop: 8 }}>{err}</div>}
          <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
            <button className="btn btn-primary" onClick={createCampaign} disabled={saving}>{saving ? "创建中…" : "创建活动"}</button>
            <button className="btn" onClick={() => setFormOpen(false)}>取消</button>
          </div>
        </div>
      )}

      {/* 发送弹窗 */}
      {sendOpen && sendCampaign && (
        <div className="card" style={{ marginTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ fontSize: 16 }}>发送：{sendCampaign.name}</h2>
            <button className="btn" onClick={() => setSendOpen(false)}>关闭</button>
          </div>

          <p className="muted" style={{ fontSize: 13, marginTop: 4 }}>
            选择收件人（可多选 = 批量发送）。模板：{sendCampaign.template?.name || "未绑定"}。
          </p>

          <div style={{ marginTop: 10, maxHeight: 240, overflow: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
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

          {err && <div style={{ color: "red", fontSize: 13, marginTop: 8 }}>{err}</div>}

          <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
            <button className="btn btn-primary" onClick={doSend} disabled={sending || contacts.length === 0}>
              {sending ? "发送中…" : `发送（${picked.length} 人）`}
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
