"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

type Tag = { id: string; name: string; color?: string; description?: string; _count?: { contactTags: number } };
type Contact = { id: string; name?: string; email?: string };

export default function TagsPage() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  // 标签表单
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Tag | null>(null);
  const [tName, setTName] = useState("");
  const [tColor, setTColor] = useState("#2563eb");
  const [tDesc, setTDesc] = useState("");
  const [saving, setSaving] = useState(false);

  // CSV 导入
  const [importOpen, setImportOpen] = useState(false);
  const [csvText, setCsvText] = useState("");
  const [preview, setPreview] = useState<{ name: string; color?: string; description?: string }[]>([]);
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState("");

  // 批量打标签
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkContacts, setBulkContacts] = useState<string[]>([]);
  const [bulkTags, setBulkTags] = useState<string[]>([]);
  const [bulkSaving, setBulkSaving] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [tg, ct] = await Promise.all([
        api<Tag[]>("/api/tags"),
        api<{ items: Contact[] }>("/api/contacts?limit=1000"),
      ]);
      setTags(tg ?? []);
      setContacts(ct?.items ?? []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  // ---- 标签增删改 ----
  function openNew() {
    setEditing(null);
    setTName("");
    setTColor("#2563eb");
    setTDesc("");
    setErr("");
    setFormOpen(true);
  }
  function openEdit(t: Tag) {
    setEditing(t);
    setTName(t.name);
    setTColor(t.color || "#2563eb");
    setTDesc(t.description || "");
    setErr("");
    setFormOpen(true);
  }
  async function saveTag() {
    setErr("");
    if (!tName.trim()) return setErr("请填写标签名称");
    setSaving(true);
    try {
      const payload = { name: tName.trim(), color: tColor, description: tDesc.trim() || undefined };
      if (editing) await api(`/api/tags/${editing.id}`, { method: "PATCH", body: JSON.stringify(payload) });
      else await api("/api/tags", { method: "POST", body: JSON.stringify(payload) });
      setFormOpen(false);
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }
  async function delTag(t: Tag) {
    if (!confirm(`确认删除标签「${t.name}」？`)) return;
    await api(`/api/tags/${t.id}`, { method: "DELETE" });
    await load();
  }

  // ---- CSV 导入 ----
  function parseCsv() {
    const lines = csvText.trim().split(/\r?\n/).filter(Boolean);
    if (lines.length < 2) return setErr("CSV 至少需要表头 + 一行数据");
    const header = lines[0].split(",").map((s) => s.trim());
    const rows = lines.slice(1).map((line) => {
      const cells = line.split(",");
      const obj: { name: string; color?: string; description?: string } = { name: "" };
      header.forEach((h, i) => {
        const v = (cells[i] ?? "").trim();
        if (h === "name") obj.name = v;
        else if (h === "color") obj.color = v;
        else if (h === "description") obj.description = v;
      });
      return obj;
    });
    setPreview(rows.filter((r) => r.name));
  }
  async function doImport() {
    if (preview.length === 0) return setErr("请先解析 CSV");
    setImporting(true);
    setImportMsg("");
    let okCount = 0;
    for (const r of preview) {
      try {
        await api("/api/tags", { method: "POST", body: JSON.stringify(r) });
        okCount++;
      } catch {
        /* 跳过重复/失败 */
      }
    }
    setImporting(false);
    setImportMsg(`导入完成：成功 ${okCount} / 共 ${preview.length}`);
    setCsvText("");
    setPreview([]);
    await load();
  }

  // ---- 批量打标签 ----
  function toggleC(id: string) {
    setBulkContacts((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  }
  function toggleT(id: string) {
    setBulkTags((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  }
  async function applyBulk() {
    if (bulkContacts.length === 0 || bulkTags.length === 0) return setErr("请选择联系人与标签");
    setBulkSaving(true);
    try {
      await api("/api/tags/bulk", { method: "POST", body: JSON.stringify({ contactIds: bulkContacts, tagIds: bulkTags }) });
      setBulkOpen(false);
      setBulkContacts([]);
      setBulkTags([]);
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBulkSaving(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 22 }}>标签</h1>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" onClick={() => { setCsvText(""); setPreview([]); setImportMsg(""); setImportOpen(true); }}>CSV 批量导入</button>
          <button className="btn" onClick={() => { setBulkContacts([]); setBulkTags([]); setBulkOpen(true); }}>批量打标签</button>
          <button className="btn btn-primary" onClick={openNew}>＋ 新建标签</button>
        </div>
      </div>

      {err && <div style={{ color: "red", fontSize: 13, marginBottom: 8 }}>{err}</div>}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 24 }} className="muted">加载中…</div>
        ) : tags.length === 0 ? (
          <div style={{ padding: 24 }} className="muted">还没有标签。新建标签或用 CSV 批量导入。</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                <th style={{ padding: "10px 14px" }}>标签</th>
                <th style={{ padding: "10px 14px" }}>说明</th>
                <th style={{ padding: "10px 14px" }}>关联客户数</th>
                <th style={{ padding: "10px 14px" }}></th>
              </tr>
            </thead>
            <tbody>
              {tags.map((t) => (
                <tr key={t.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "10px 14px" }}>
                    <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: "50%", background: t.color || "#94a3b8", marginRight: 8 }} />
                    {t.name}
                  </td>
                  <td style={{ padding: "10px 14px" }} className="muted">{t.description || "—"}</td>
                  <td style={{ padding: "10px 14px" }}>{t._count?.contactTags ?? 0}</td>
                  <td style={{ padding: "10px 14px", textAlign: "right" }}>
                    <button className="btn" onClick={() => openEdit(t)}>编辑</button>
                    <button className="btn" style={{ marginLeft: 6 }} onClick={() => delTag(t)}>删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 标签表单 */}
      {formOpen && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 16, marginBottom: 12 }}>{editing ? "编辑标签" : "新建标签"}</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>标签名称 *</label>
              <input className="input" value={tName} onChange={(e) => setTName(e.target.value)} placeholder="如：高意向" />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>颜色</label>
              <input type="color" value={tColor} onChange={(e) => setTColor(e.target.value)} style={{ width: 48, height: 34, border: "none", background: "none" }} />
            </div>
          </div>
          <div style={{ marginTop: 12 }}>
            <label className="muted" style={{ fontSize: 13 }}>说明</label>
            <input className="input" value={tDesc} onChange={(e) => setTDesc(e.target.value)} placeholder="可选" />
          </div>
          {err && <div style={{ color: "red", fontSize: 13, marginTop: 8 }}>{err}</div>}
          <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
            <button className="btn btn-primary" onClick={saveTag} disabled={saving}>{saving ? "保存中…" : "保存"}</button>
            <button className="btn" onClick={() => setFormOpen(false)}>取消</button>
          </div>
        </div>
      )}

      {/* CSV 导入 */}
      {importOpen && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 16, marginBottom: 8 }}>CSV 批量导入标签</h2>
          <p className="muted" style={{ fontSize: 13, marginBottom: 8 }}>格式：首行表头 name,color,description。例：<br />name,color,description<br />高意向,#f59e0b,近期活跃<br />流失风险,#ef4444,30天未活跃</p>
          <textarea className="input" rows={6} value={csvText} onChange={(e) => setCsvText(e.target.value)} placeholder="粘贴 CSV 文本" style={{ fontFamily: "ui-monospace, monospace", fontSize: 13 }} />
          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            <button className="btn" onClick={parseCsv}>解析预览</button>
            <button className="btn btn-primary" onClick={doImport} disabled={importing || preview.length === 0}>{importing ? "导入中…" : `导入（${preview.length}）`}</button>
            <button className="btn" onClick={() => setImportOpen(false)}>关闭</button>
          </div>
          {preview.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div className="muted" style={{ fontSize: 13, marginBottom: 4 }}>预览 {preview.length} 行：</div>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
                {preview.slice(0, 8).map((r, i) => (
                  <li key={i}>{r.name} {r.color ? `(${r.color})` : ""} {r.description ? `— ${r.description}` : ""}</li>
                ))}
                {preview.length > 8 && <li className="muted">…共 {preview.length} 行</li>}
              </ul>
            </div>
          )}
          {importMsg && <div style={{ color: "#16a34a", fontSize: 13, marginTop: 8 }}>{importMsg}</div>}
        </div>
      )}

      {/* 批量打标签 */}
      {bulkOpen && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 16, marginBottom: 8 }}>批量打标签</h2>
          <p className="muted" style={{ fontSize: 13, marginBottom: 8 }}>左侧勾选客户，右侧勾选标签，点击「应用」即把所选标签打到所选客户上。</p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div>
              <div className="muted" style={{ fontSize: 13, marginBottom: 6 }}>客户（已选 {bulkContacts.length}）</div>
              <div style={{ maxHeight: 260, overflow: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
                {contacts.map((c) => (
                  <label key={c.id} style={{ display: "flex", gap: 8, alignItems: "center", padding: "6px 10px", borderBottom: "1px solid var(--border)", fontSize: 13 }}>
                    <input type="checkbox" checked={bulkContacts.includes(c.id)} onChange={() => toggleC(c.id)} />
                    <span>{c.name || "—"}</span>
                    <span className="muted">{c.email}</span>
                  </label>
                ))}
              </div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 13, marginBottom: 6 }}>标签（已选 {bulkTags.length}）</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {tags.map((t) => (
                  <label key={t.id} style={{ fontSize: 13, border: "1px solid var(--border)", padding: "6px 10px", borderRadius: 8, background: bulkTags.includes(t.id) ? "#eef2ff" : "#fff" }}>
                    <input type="checkbox" checked={bulkTags.includes(t.id)} onChange={() => toggleT(t.id)} /> {t.name}
                  </label>
                ))}
              </div>
            </div>
          </div>
          {err && <div style={{ color: "red", fontSize: 13, marginTop: 8 }}>{err}</div>}
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button className="btn btn-primary" onClick={applyBulk} disabled={bulkSaving}>{bulkSaving ? "应用中…" : "应用"}</button>
            <button className="btn" onClick={() => setBulkOpen(false)}>关闭</button>
          </div>
        </div>
      )}
    </div>
  );
}
