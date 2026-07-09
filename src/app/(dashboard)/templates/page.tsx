"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

type Tpl = {
  id: string;
  name: string;
  type: string;
  subject?: string;
  body: string;
  variables: string;
  updatedAt: string;
};

export default function TemplatesPage() {
  const [type, setType] = useState<"EDM" | "SMS">("EDM");
  const [list, setList] = useState<Tpl[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Tpl | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [variables, setVariables] = useState("");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  // AI 助手（仅 EDM）
  const [aiTopic, setAiTopic] = useState("");
  const [aiTone, setAiTone] = useState("");
  const [aiOffer, setAiOffer] = useState("");
  const [aiCta, setAiCta] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiErr, setAiErr] = useState("");

  async function load() {
    setLoading(true);
    try {
      const data = await api<Tpl[]>(`/api/templates?type=${type}`);
      setList(data ?? []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [type]);

  function openNew() {
    setEditing(null);
    setName("");
    setSubject("");
    setBody("");
    setImageUrl("");
    setVariables("");
    setAiTopic("");
    setAiTone("");
    setAiOffer("");
    setAiCta("");
    setErr("");
    setAiErr("");
    setFormOpen(true);
  }

  function openEdit(t: Tpl) {
    setEditing(t);
    setName(t.name);
    setSubject(t.subject ?? "");
    setBody(t.body);
    try {
      const v = JSON.parse(t.variables || "[]");
      setVariables(Array.isArray(v) ? v.join(", ") : "");
    } catch {
      setVariables("");
    }
    setImageUrl("");
    setErr("");
    setFormOpen(true);
  }

  function insertImage() {
    const url = imageUrl.trim();
    if (!url) return;
    const tag = `\n<img src="${url}" alt="" style="max-width:100%;border-radius:8px;margin:12px 0" />\n`;
    setBody((b) => b + tag);
    setImageUrl("");
  }

  async function generateAI() {
    setAiErr("");
    if (!aiTopic.trim()) return setAiErr("请填写推广主题");
    setAiLoading(true);
    try {
      const base = { activityName: aiTopic.trim(), tone: aiTone.trim() || undefined, offer: aiOffer.trim() || undefined, cta: aiCta.trim() || undefined, language: "zh" };
      const [titleRes, bodyRes] = await Promise.all([
        api<{ variants: { content: string }[] }>("/api/ai/copy", { method: "POST", body: JSON.stringify({ ...base, channel: "EDM_TITLE" }) }),
        api<{ variants: { content: string }[] }>("/api/ai/copy", { method: "POST", body: JSON.stringify({ ...base, channel: "EDM_BODY" }) }),
      ]);
      const title = titleRes?.variants?.[0]?.content;
      const html = bodyRes?.variants?.[0]?.content;
      if (title) setSubject(title);
      if (html) setBody(html);
    } catch (e: any) {
      setAiErr(e.message || "生成失败");
    } finally {
      setAiLoading(false);
    }
  }

  async function save() {
    setErr("");
    if (!name.trim() || !body.trim()) return setErr("请填写模板名称与正文");
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        type,
        name: name.trim(),
        body,
        variables: variables.split(",").map((s) => s.trim()).filter(Boolean),
      };
      if (type === "EDM") payload.subject = subject.trim();
      if (editing) {
        await api(`/api/templates/${editing.id}`, { method: "PATCH", body: JSON.stringify(payload) });
      } else {
        await api("/api/templates", { method: "POST", body: JSON.stringify(payload) });
      }
      setFormOpen(false);
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <h1 style={{ fontSize: 22, margin: 0 }}>模板</h1>
          <div style={{ display: "flex", gap: 6, marginLeft: 12 }}>
            <button className="btn" style={{ background: type === "EDM" ? "var(--brand)" : "#fff", color: type === "EDM" ? "#fff" : "var(--text)" }} onClick={() => setType("EDM")}>📧 EDM</button>
            <button className="btn" style={{ background: type === "SMS" ? "var(--brand)" : "#fff", color: type === "SMS" ? "#fff" : "var(--text)" }} onClick={() => setType("SMS")}>💬 SMS</button>
          </div>
        </div>
        <button className="btn btn-primary" onClick={openNew}>＋ 新建{type === "EDM" ? "邮件" : "短信"}模板</button>
      </div>

      {!formOpen && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          {loading ? (
            <div style={{ padding: 24 }} className="muted">加载中…</div>
          ) : list.length === 0 ? (
            <div style={{ padding: 24 }} className="muted">还没有{type === "EDM" ? "邮件" : "短信"}模板，点击右上角新建。</div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead>
                <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                  <th style={{ padding: "10px 14px" }}>名称</th>
                  <th style={{ padding: "10px 14px" }}>{type === "EDM" ? "主题" : "正文预览"}</th>
                  <th style={{ padding: "10px 14px" }}>更新时间</th>
                  <th style={{ padding: "10px 14px" }}></th>
                </tr>
              </thead>
              <tbody>
                {list.map((t) => (
                  <tr key={t.id} style={{ borderTop: "1px solid var(--border)" }}>
                    <td style={{ padding: "10px 14px" }}>{t.name}</td>
                    <td style={{ padding: "10px 14px" }} className="muted">
                      {type === "EDM" ? (t.subject || "—") : (t.body.slice(0, 40) || "—")}
                    </td>
                    <td style={{ padding: "10px 14px" }} className="muted">{new Date(t.updatedAt).toLocaleString()}</td>
                    <td style={{ padding: "10px 14px", textAlign: "right" }}>
                      <button className="btn" onClick={() => openEdit(t)}>编辑</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {formOpen && (
        <div className="card">
          <h2 style={{ fontSize: 16, marginBottom: 12 }}>{editing ? "编辑模板" : `新建${type === "EDM" ? "邮件" : "短信"}模板`}（{type}）</h2>

          {type === "EDM" && (
            <div style={{ border: "1px solid #c7d2fe", background: "#eef2ff", borderRadius: 10, padding: 14, marginBottom: 16 }}>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>🤖 AI 助手：输入推广主题，自动生成标题 + 正文</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <div>
                  <label className="muted" style={{ fontSize: 13 }}>推广主题 *</label>
                  <input className="input" value={aiTopic} onChange={(e) => setAiTopic(e.target.value)} placeholder="如：618 年中大促" />
                </div>
                <div>
                  <label className="muted" style={{ fontSize: 13 }}>语气</label>
                  <input className="input" value={aiTone} onChange={(e) => setAiTone(e.target.value)} placeholder="如：亲切 / 专业 / 紧迫" />
                </div>
                <div>
                  <label className="muted" style={{ fontSize: 13 }}>优惠信息</label>
                  <input className="input" value={aiOffer} onChange={(e) => setAiOffer(e.target.value)} placeholder="如：全场 5 折" />
                </div>
                <div>
                  <label className="muted" style={{ fontSize: 13 }}>行动号召 (CTA)</label>
                  <input className="input" value={aiCta} onChange={(e) => setAiCta(e.target.value)} placeholder="如：立即抢购" />
                </div>
              </div>
              <div style={{ marginTop: 10 }}>
                <button className="btn btn-primary" type="button" onClick={generateAI} disabled={aiLoading}>{aiLoading ? "生成中…" : "✨ 一键生成标题与正文"}</button>
                <span className="muted" style={{ fontSize: 12, marginLeft: 10 }}>未配 API Key 时使用本地智能模板。</span>
              </div>
              {aiErr && <div style={{ color: "#dc2626", fontSize: 13, marginTop: 6 }}>{aiErr}</div>}
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>模板名称</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="如：618 大促通知" />
            </div>
            {type === "EDM" && (
              <div>
                <label className="muted" style={{ fontSize: 13 }}>邮件主题</label>
                <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="如：{{first_name}}，专属优惠来了" />
              </div>
            )}
          </div>

          <div style={{ marginTop: 12 }}>
            <label className="muted" style={{ fontSize: 13 }}>
              {type === "EDM" ? "正文（支持 HTML，可用 {{first_name}} 等变量）" : `短信正文（纯文本，可用 {{first_name}} 等变量，已 ${body.length} 字）`}
            </label>
            <textarea
              className="input"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={type === "EDM" ? 10 : 6}
              style={{ fontFamily: type === "EDM" ? "ui-monospace, monospace" : "inherit", fontSize: 13 }}
              placeholder={type === "EDM" ? "<h1>你好 {{first_name}}</h1><p>这是我们的新品…</p>" : "【品牌】{{first_name}}，专属优惠来了，回复 TD 退订"}
            />
          </div>

          {type === "EDM" && (
            <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center" }}>
              <input className="input" style={{ maxWidth: 380 }} value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} placeholder="图片 URL，如 https://…/banner.jpg" />
              <button className="btn" onClick={insertImage} type="button">＋ 插入图片</button>
            </div>
          )}

          <div style={{ marginTop: 12 }}>
            <label className="muted" style={{ fontSize: 13 }}>变量（逗号分隔，可选）</label>
            <input className="input" value={variables} onChange={(e) => setVariables(e.target.value)} placeholder="first_name, city" />
          </div>

          {type === "EDM" && (
            <div style={{ marginTop: 12 }}>
              <label className="muted" style={{ fontSize: 13 }}>实时预览</label>
              <iframe title="preview" srcDoc={body} style={{ width: "100%", height: 220, border: "1px solid var(--border)", borderRadius: 8, background: "#fff" }} />
            </div>
          )}

          {err && <div style={{ color: "red", fontSize: 13, marginTop: 8 }}>{err}</div>}

          <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
            <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? "保存中…" : "保存模板"}</button>
            <button className="btn" onClick={() => setFormOpen(false)}>取消</button>
          </div>
        </div>
      )}
    </div>
  );
}
