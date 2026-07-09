"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api-client";

type Wf = {
  id: string;
  name: string;
  description?: string;
  enabled: boolean;
  definition: string; // JSON 字符串
};

export default function WorkflowsPage() {
  const [list, setList] = useState<Wf[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const data = await api<Wf[]>("/api/workflows");
      setList(data ?? []);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  async function create() {
    if (!name.trim()) return setErr("请填写工作流名称");
    setSaving(true);
    try {
      const wf = await api<{ id: string }>("/api/workflows", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          definition: { trigger: { type: "event" }, actions: [] },
          enabled: false,
        }),
      });
      setName("");
      await load();
      // 直接进构造器
      window.location.href = `/workflows/${wf.id}`;
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function toggle(id: string, enabled: boolean) {
    await api(`/api/workflows/${id}`, { method: "PATCH", body: JSON.stringify({ enabled: !enabled }) });
    await load();
  }
  async function del(id: string) {
    if (!confirm("确认删除该工作流？")) return;
    await api(`/api/workflows/${id}`, { method: "DELETE" });
    await load();
  }

  function triggerLabel(def?: string): string {
    if (!def) return "—";
    try {
      const d = JSON.parse(def);
      const t = d.trigger?.type || "未配置";
      return t;
    } catch {
      return "—";
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 22 }}>自动化工作流</h1>
      </div>

      <div className="card" style={{ padding: 16, marginBottom: 16, display: "flex", gap: 8, alignItems: "center" }}>
        <input className="input" style={{ maxWidth: 280 }} value={name} onChange={(e) => setName(e.target.value)} placeholder="新工作流名称，如：F1 浏览未购自动打标" />
        <button className="btn btn-primary" onClick={create} disabled={saving}>{saving ? "创建中…" : "＋ 新建工作流"}</button>
        {err && <span style={{ color: "red", fontSize: 13 }}>{err}</span>}
      </div>

      <p className="muted" style={{ fontSize: 13, marginTop: -8, marginBottom: 12 }}>
        触发器（事件 / 标签被添加 / 进入分群 / Webhook）→ 动作序列（发送邮件·短信、加/移除标签、进/出分群、等待、调用 Webhook）。每个动作可附加条件（有标签 / 在分群内 / 事件次数≥ / 已购买），不满足则跳过。点击「编辑」进入可视化构造器。
      </p>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 24 }} className="muted">加载中…</div>
        ) : list.length === 0 ? (
          <div style={{ padding: 24 }} className="muted">还没有工作流。输入名称新建一个。</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                <th style={{ padding: "10px 14px" }}>名称</th>
                <th style={{ padding: "10px 14px" }}>触发器</th>
                <th style={{ padding: "10px 14px" }}>状态</th>
                <th style={{ padding: "10px 14px" }}></th>
              </tr>
            </thead>
            <tbody>
              {list.map((w) => (
                <tr key={w.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "10px 14px" }}>{w.name}</td>
                  <td style={{ padding: "10px 14px" }} className="muted">{triggerLabel(w.definition)}</td>
                  <td style={{ padding: "10px 14px" }}>
                    <span style={{ fontSize: 12, color: w.enabled ? "#16a34a" : "#64748b" }}>{w.enabled ? "启用中" : "已停用"}</span>
                  </td>
                  <td style={{ padding: "10px 14px", textAlign: "right", display: "flex", gap: 6, justifyContent: "flex-end" }}>
                    <button className="btn" onClick={() => toggle(w.id, w.enabled)}>{w.enabled ? "停用" : "启用"}</button>
                    <Link href={`/workflows/${w.id}`} className="btn">编辑</Link>
                    <button className="btn" onClick={() => del(w.id)}>删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
