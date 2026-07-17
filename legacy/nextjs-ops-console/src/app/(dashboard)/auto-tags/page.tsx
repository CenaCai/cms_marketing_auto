"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

type Rule = {
  id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  trigger: "EVENT" | "INACTIVITY";
  eventType: string | null;
  matchMode: string;
  threshold: number;
  windowDays: number | null;
  propMatch: string | null;
  tagTemplate: string;
  inactiveDays: number | null;
  matched: number;
};

function summarize(r: Rule): string {
  if (r.trigger === "INACTIVITY") return `超过 ${r.inactiveDays ?? 30} 天未活跃`;
  let s = `事件类型 = ${r.eventType}`;
  if (r.propMatch) {
    try {
      const pm = JSON.parse(r.propMatch);
      s += ` 且 ${pm.field} 含 "${pm.contains}"`;
    } catch {}
  }
  if (r.matchMode === "count") s += ` · 累计 ≥ ${r.threshold} 次`;
  if (r.windowDays) s += `（${r.windowDays} 天内）`;
  return s;
}

export default function AutoTagsPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(true);
  const [sweepMsg, setSweepMsg] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    trigger: "EVENT" as "EVENT" | "INACTIVITY",
    eventType: "BROWSE",
    matchMode: "always" as "always" | "count",
    threshold: 2,
    windowDays: 30,
    propField: "",
    propContains: "",
    tagTemplate: "",
    inactiveDays: 30,
    enabled: true,
  });

  async function load() {
    setLoading(true);
    try {
      const data = await api<Rule[]>("/api/auto-tags");
      setRules(data ?? []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function toggle(rule: Rule) {
    await api(`/api/auto-tags/${rule.id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled: !rule.enabled }),
    });
    load();
  }

  async function remove(rule: Rule) {
    if (!confirm(`确定删除规则「${rule.name}」？`)) return;
    await api(`/api/auto-tags/${rule.id}`, { method: "DELETE" });
    load();
  }

  async function runSweep() {
    setSweepMsg("扫描中…");
    try {
      const res = await api<{ tagged: number }>("/api/auto-tags/sweep", { method: "POST" });
      setSweepMsg(`扫描完成，本次新增打标 ${res.tagged} 人`);
      load();
    } catch (e: any) {
      setSweepMsg("失败：" + e.message);
    }
  }

  async function submit() {
    const payload: any = {
      name: form.name,
      description: form.description,
      trigger: form.trigger,
      tagTemplate: form.tagTemplate,
      enabled: form.enabled,
    };
    if (form.trigger === "EVENT") {
      payload.eventType = form.eventType;
      payload.matchMode = form.matchMode;
      if (form.matchMode === "count") {
        payload.threshold = Number(form.threshold);
        payload.windowDays = Number(form.windowDays) || null;
      } else {
        payload.windowDays = null;
      }
      payload.propMatch =
        form.propField && form.propContains
          ? { field: form.propField, contains: form.propContains }
          : null;
    } else {
      payload.inactiveDays = Number(form.inactiveDays);
    }
    await api("/api/auto-tags", { method: "POST", body: JSON.stringify(payload) });
    setShowForm(false);
    setForm({ ...form, name: "", description: "", tagTemplate: "", propField: "", propContains: "" });
    load();
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, flexWrap: "wrap", gap: 8 }}>
        <h1 style={{ fontSize: 22, margin: 0 }}>自动打标签规则</h1>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" onClick={runSweep}>⏱ 运行不活跃扫描</button>
          <button className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>{showForm ? "收起" : "＋ 新建规则"}</button>
        </div>
      </div>
      <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
        基于规则引擎（非 AI）：事件触发（即时 / 计数）+ 不活跃定时扫描，命中即自动给联系人打标。
      </p>
      {sweepMsg && <div className="card" style={{ padding: 10, marginBottom: 12, fontSize: 13 }}>{sweepMsg}</div>}

      {showForm && (
        <div className="card" style={{ padding: 16, marginBottom: 16 }}>
          <h3 style={{ margin: "0 0 12px" }}>新建规则</h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="规则名称"><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="例如：高意向 F1" /></Field>
            <Field label="标签模板（支持 {var}）"><input className="input" value={form.tagTemplate} onChange={(e) => setForm({ ...form, tagTemplate: e.target.value })} placeholder="例如：high_intent_f1 / purchased_{product}" /></Field>
            <Field label="触发方式">
              <select className="input" value={form.trigger} onChange={(e) => setForm({ ...form, trigger: e.target.value as any })}>
                <option value="EVENT">事件触发</option>
                <option value="INACTIVITY">不活跃扫描</option>
              </select>
            </Field>
            {form.trigger === "EVENT" ? (
              <>
                <Field label="事件类型"><input className="input" value={form.eventType} onChange={(e) => setForm({ ...form, eventType: e.target.value })} placeholder="BROWSE / CLICK_LINK / PURCHASE" /></Field>
                <Field label="匹配模式">
                  <select className="input" value={form.matchMode} onChange={(e) => setForm({ ...form, matchMode: e.target.value as any })}>
                    <option value="always">每次事件</option>
                    <option value="count">累计次数</option>
                  </select>
                </Field>
                {form.matchMode === "count" && (
                  <>
                    <Field label="阈值次数"><input className="input" type="number" value={form.threshold} onChange={(e) => setForm({ ...form, threshold: Number(e.target.value) })} /></Field>
                    <Field label="统计窗口(天, 0=不限)"><input className="input" type="number" value={form.windowDays} onChange={(e) => setForm({ ...form, windowDays: Number(e.target.value) })} /></Field>
                  </>
                )}
                <Field label="属性字段(可选)"><input className="input" value={form.propField} onChange={(e) => setForm({ ...form, propField: e.target.value })} placeholder="例如 page" /></Field>
                <Field label="属性包含(可选)"><input className="input" value={form.propContains} onChange={(e) => setForm({ ...form, propContains: e.target.value })} placeholder="例如 f1" /></Field>
              </>
            ) : (
              <Field label="未活跃天数"><input className="input" type="number" value={form.inactiveDays} onChange={(e) => setForm({ ...form, inactiveDays: Number(e.target.value) })} /></Field>
            )}
          </div>
          <div style={{ marginTop: 12 }}>
            <button className="btn btn-primary" onClick={submit}>创建规则</button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="muted" style={{ padding: 24 }}>加载中…</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {rules.map((r) => (
            <div key={r.id} className="card" style={{ padding: 16, borderLeft: `4px solid ${r.enabled ? "#16a34a" : "#cbd5e1"}` }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <strong style={{ fontSize: 15 }}>{r.name}</strong>
                    <span style={{ fontSize: 11, background: r.trigger === "INACTIVITY" ? "#fef3c7" : "#e0f2fe", color: r.trigger === "INACTIVITY" ? "#b45309" : "#0369a1", padding: "2px 8px", borderRadius: 6 }}>
                      {r.trigger === "INACTIVITY" ? "不活跃扫描" : "事件触发"}
                    </span>
                    <span style={{ fontSize: 11, background: "#f1f5f9", color: "#475569", padding: "2px 8px", borderRadius: 6 }}>标签 → {r.tagTemplate}</span>
                  </div>
                  <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>{r.description}</div>
                  <div style={{ fontSize: 13, marginTop: 6 }}>条件：{summarize(r)}</div>
                  <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>已打标人数：{r.matched}</div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <button className="btn" style={{ background: r.enabled ? "#16a34a" : "#fff", color: r.enabled ? "#fff" : "var(--text)" }} onClick={() => toggle(r)}>{r.enabled ? "已启用" : "已停用"}</button>
                  <button className="btn" style={{ color: "#dc2626" }} onClick={() => remove(r)}>删除</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="muted" style={{ fontSize: 13 }}>{label}</label>
      <div style={{ marginTop: 4 }}>{children}</div>
    </div>
  );
}
