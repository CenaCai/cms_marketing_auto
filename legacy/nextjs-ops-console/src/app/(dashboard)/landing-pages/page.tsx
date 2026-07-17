"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api-client";

type LP = { id: string; name: string; updatedAt: string; body: string };

export default function LandingPagesPage() {
  const router = useRouter();
  const [list, setList] = useState<LP[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const data = await api<LP[]>("/api/templates?type=LANDING");
      setList(data ?? []);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  async function create() {
    if (!name.trim()) return setErr("请填写落地页名称");
    setSaving(true);
    try {
      const lp = await api<{ id: string }>("/api/templates", {
        method: "POST",
        body: JSON.stringify({ type: "LANDING", name: name.trim(), body: JSON.stringify({ status: "draft", blocks: [] }) }),
      });
      router.push(`/landing-pages/${lp.id}`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 22 }}>落地页 / H5</h1>
      </div>

      <div className="card" style={{ padding: 16, marginBottom: 16, display: "flex", gap: 8, alignItems: "center" }}>
        <input className="input" style={{ maxWidth: 280 }} value={name} onChange={(e) => setName(e.target.value)} placeholder="新落地页名称，如：F1 Madrid 2026 报名" />
        <button className="btn btn-primary" onClick={create} disabled={saving}>{saving ? "创建中…" : "＋ 新建落地页"}</button>
        {err && <span style={{ color: "red", fontSize: 13 }}>{err}</span>}
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 24 }} className="muted">加载中…</div>
        ) : list.length === 0 ? (
          <div style={{ padding: 24 }} className="muted">还没有落地页。输入名称新建一个，进入基础 H5 编辑器。</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                <th style={{ padding: "10px 14px" }}>名称</th>
                <th style={{ padding: "10px 14px" }}>更新时间</th>
                <th style={{ padding: "10px 14px" }}></th>
              </tr>
            </thead>
            <tbody>
              {list.map((l) => (
                <tr key={l.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "10px 14px" }}>{l.name}</td>
                  <td style={{ padding: "10px 14px" }} className="muted">{new Date(l.updatedAt).toLocaleString()}</td>
                  <td style={{ padding: "10px 14px", textAlign: "right" }}>
                    <Link href={`/landing-pages/${l.id}`} className="btn">编辑</Link>
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
