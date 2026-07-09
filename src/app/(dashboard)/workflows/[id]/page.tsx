"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api-client";

type Tag = { id: string; name: string };
type Seg = { id: string; name: string };

type Def = {
  trigger: any;
  actions: any[];
};

const ACTION_TYPES = [
  { key: "send_email", label: "发送邮件" },
  { key: "send_sms", label: "发送短信" },
  { key: "add_tag", label: "加标签" },
  { key: "remove_tag", label: "移除标签" },
  { key: "join_segment", label: "加入分群" },
  { key: "leave_segment", label: "移出分群" },
  { key: "call_webhook", label: "调用 Webhook" },
  { key: "wait", label: "等待（延迟）" },
];
const TRIGGER_TYPES = [
  { key: "event", label: "事件（event）" },
  { key: "custom_event", label: "自定义事件" },
  { key: "tag_added", label: "标签被添加" },
  { key: "segment_joined", label: "进入分群" },
  { key: "webhook", label: "Webhook" },
];

export default function WorkflowBuilderPage() {
  const { id } = useParams<{ id: string }>();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [def, setDef] = useState<Def>({ trigger: { type: "event" }, actions: [] });
  const [tags, setTags] = useState<Tag[]>([]);
  const [segments, setSegments] = useState<Seg[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!id) return;
    (async () => {
      try {
        const [wf, tg, sg] = await Promise.all([
          api<{ name: string; description?: string; enabled: boolean; definition: string }>(`/api/workflows/${id}`),
          api<Tag[]>("/api/tags"),
          api<Seg[]>("/api/segments"),
        ]);
        setName(wf.name);
        setDescription(wf.description || "");
        setEnabled(wf.enabled);
        try {
          setDef(JSON.parse(wf.definition) as Def);
        } catch {
          setDef({ trigger: { type: "event" }, actions: [] });
        }
        setTags(tg ?? []);
        setSegments(sg ?? []);
      } catch (e: any) {
        setErr(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  function setTrigger(patch: any) {
    setDef((d) => ({ ...d, trigger: { ...d.trigger, ...patch } }));
  }
  function updateAction(i: number, patch: any) {
    setDef((d) => ({ ...d, actions: d.actions.map((a, idx) => (idx === i ? { ...a, ...patch } : a)) }));
  }
  function setActionConfig(i: number, config: any) {
    setDef((d) => ({ ...d, actions: d.actions.map((a, idx) => (idx === i ? { ...a, config } : a)) }));
  }
  function addAction() {
    setDef((d) => ({ ...d, actions: [...d.actions, { type: "add_tag", config: {} }] }));
  }
  function removeAction(i: number) {
    setDef((d) => ({ ...d, actions: d.actions.filter((_, idx) => idx !== i) }));
  }

  async function save() {
    setErr("");
    setSaved(false);
    setSaving(true);
    try {
      await api(`/api/workflows/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ name, description, enabled, definition: def }),
      });
      setSaved(true);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="muted" style={{ padding: 24 }}>加载中…</div>;
  if (err && !name) return <div style={{ color: "red", padding: 24 }}>{err}</div>;

  const tt = def.trigger?.type || "event";

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Link href="/workflows" className="btn">← 返回工作流</Link>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h1 style={{ fontSize: 22, margin: 0 }}>工作流构造器</h1>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <label style={{ fontSize: 14, display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> 启用
          </label>
          <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? "保存中…" : "保存"}</button>
        </div>
      </div>
      {err && <div style={{ color: "red", fontSize: 13, marginBottom: 8 }}>{err}</div>}
      {saved && <div style={{ color: "#16a34a", fontSize: 13, marginBottom: 8 }}>已保存</div>}

      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div>
            <label className="muted" style={{ fontSize: 13 }}>名称</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="muted" style={{ fontSize: 13 }}>说明</label>
            <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
        </div>
      </div>

      {/* 触发器 */}
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        <h2 style={{ fontSize: 15, margin: "0 0 10px" }}>① 触发器（何时启动）</h2>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <select className="input" style={{ maxWidth: 200 }} value={tt} onChange={(e) => setTrigger({ type: e.target.value })}>
            {TRIGGER_TYPES.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select>
          {(tt === "event" || tt === "custom_event") && (
            <input className="input" style={{ maxWidth: 240 }} value={def.trigger?.eventName || ""} onChange={(e) => setTrigger({ eventName: e.target.value })} placeholder="事件名，如 F1_Event" />
          )}
          {tt === "event" && (
            <input className="input" style={{ maxWidth: 200 }} value={def.trigger?.eventType || ""} onChange={(e) => setTrigger({ eventType: e.target.value })} placeholder="事件类型（可选）" />
          )}
          {tt === "tag_added" && (
            <select className="input" style={{ maxWidth: 200 }} value={def.trigger?.tagId || ""} onChange={(e) => setTrigger({ tagId: e.target.value })}>
              <option value="">选择标签</option>
              {tags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          )}
          {tt === "segment_joined" && (
            <select className="input" style={{ maxWidth: 200 }} value={def.trigger?.segmentId || ""} onChange={(e) => setTrigger({ segmentId: e.target.value })}>
              <option value="">选择分群</option>
              {segments.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}
        </div>
      </div>

      {/* 动作序列 */}
      <div className="card" style={{ padding: 16 }}>
        <h2 style={{ fontSize: 15, margin: "0 0 10px" }}>② 动作序列（按顺序执行）</h2>
        {def.actions.length === 0 && <div className="muted" style={{ fontSize: 13 }}>暂无动作，点击下方「＋ 添加动作」。</div>}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {def.actions.map((a, i) => (
            <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 12 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                <span style={{ fontSize: 12, color: "#7c3aed", fontWeight: 600 }}>步骤 {i + 1}</span>
                <select className="input" style={{ maxWidth: 180 }} value={a.type} onChange={(e) => updateAction(i, { type: e.target.value })}>
                  {ACTION_TYPES.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                </select>
                <button className="btn" onClick={() => removeAction(i)}>✕ 删除</button>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {(a.type === "send_email" || a.type === "send_sms") && (
                  <>
                    {a.type === "send_email" && (
                      <input className="input" style={{ maxWidth: 280 }} value={a.config?.subject || ""} onChange={(e) => setActionConfig(i, { ...a.config, subject: e.target.value })} placeholder="邮件主题" />
                    )}
                    <textarea className="input" rows={2} style={{ flex: 1, minWidth: 240, fontSize: 13 }} value={a.config?.body || ""} onChange={(e) => setActionConfig(i, { ...a.config, body: e.target.value })} placeholder="正文（可用 {{first_name}} 变量）" />
                  </>
                )}
                {(a.type === "add_tag" || a.type === "remove_tag") && (
                  <select className="input" style={{ maxWidth: 200 }} value={a.config?.tagId || ""} onChange={(e) => setActionConfig(i, { ...a.config, tagId: e.target.value })}>
                    <option value="">选择标签</option>
                    {tags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                )}
                {(a.type === "join_segment" || a.type === "leave_segment") && (
                  <select className="input" style={{ maxWidth: 200 }} value={a.config?.segmentId || ""} onChange={(e) => setActionConfig(i, { ...a.config, segmentId: e.target.value })}>
                    <option value="">选择分群</option>
                    {segments.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                )}
                {a.type === "call_webhook" && (
                  <input className="input" style={{ flex: 1, minWidth: 240 }} value={a.config?.url || ""} onChange={(e) => setActionConfig(i, { ...a.config, url: e.target.value })} placeholder="https://..." />
                )}
                {a.type === "wait" && (
                  <input className="input" style={{ maxWidth: 160 }} type="number" value={a.config?.minutes || 60} onChange={(e) => setActionConfig(i, { ...a.config, minutes: Number(e.target.value) })} placeholder="延迟分钟" />
                )}
              </div>
            </div>
          ))}
        </div>
        <button className="btn" style={{ marginTop: 10 }} onClick={addAction}>＋ 添加动作</button>
      </div>
    </div>
  );
}
