"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api-client";

type Block =
  | { type: "heading"; text: string }
  | { type: "text"; text: string }
  | { type: "image"; url: string }
  | { type: "button"; text: string; href: string };
type Doc = { status: "draft" | "published"; blocks: Block[] };

const BLOCK_TYPES = [
  { key: "heading", label: "标题" },
  { key: "text", label: "文本" },
  { key: "image", label: "图片" },
  { key: "button", label: "按钮" },
];

function renderBlock(b: Block): string {
  switch (b.type) {
    case "heading":
      return `<h2 style="font-size:20px;margin:16px 0 8px;color:#111">${esc(b.text)}</h2>`;
    case "text":
      return `<p style="font-size:14px;line-height:1.7;color:#374151;margin:8px 0">${esc(b.text)}</p>`;
    case "image":
      return b.url ? `<img src="${esc(b.url)}" style="width:100%;border-radius:10px;margin:10px 0" />` : "";
    case "button":
      return `<a href="${esc(b.href)}" style="display:inline-block;margin:12px 0;padding:12px 24px;background:#4f46e5;color:#fff;border-radius:10px;text-decoration:none;font-size:15px">${esc(b.text)}</a>`;
    default:
      return "";
  }
}
function esc(s: string): string {
  return (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string));
}
function toHtml(doc: Doc): string {
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:system-ui,sans-serif;padding:16px;margin:0}</style></head><body>${doc.blocks.map(renderBlock).join("")}</body></html>`;
}

export default function LandingEditorPage() {
  const { id } = useParams<{ id: string }>();
  const [name, setName] = useState("");
  const [doc, setDoc] = useState<Doc>({ status: "draft", blocks: [] });
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!id) return;
    (async () => {
      try {
        const list = await api<{ id: string; name: string; body: string }[]>("/api/templates?type=LANDING");
        const lp = list?.find((t) => t.id === id);
        if (!lp) throw new Error("落地页不存在");
        setName(lp.name);
        try {
          setDoc(JSON.parse(lp.body) as Doc);
        } catch {
          setDoc({ status: "draft", blocks: [] });
        }
      } catch (e: any) {
        setErr(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  function addBlock(type: string) {
    const base: Block =
      type === "heading" ? { type: "heading", text: "标题文字" } :
      type === "text" ? { type: "text", text: "这里是正文内容。" } :
      type === "image" ? { type: "image", url: "" } :
      { type: "button", text: "立即报名", href: "#" };
    setDoc((d) => ({ ...d, blocks: [...d.blocks, base] }));
  }
  function updateBlock(i: number, patch: Partial<Block>) {
    setDoc((d) => ({ ...d, blocks: d.blocks.map((b, idx) => (idx === i ? ({ ...b, ...patch } as Block) : b)) }));
  }
  function removeBlock(i: number) {
    setDoc((d) => ({ ...d, blocks: d.blocks.filter((_, idx) => idx !== i) }));
  }
  function move(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= doc.blocks.length) return;
    const blocks = [...doc.blocks];
    [blocks[i], blocks[j]] = [blocks[j], blocks[i]];
    setDoc((d) => ({ ...d, blocks }));
  }

  async function save() {
    setErr("");
    setSaved(false);
    setSaving(true);
    try {
      await api(`/api/templates/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ name, body: JSON.stringify(doc) }),
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

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Link href="/landing-pages" className="btn">← 返回落地页</Link>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <input className="input" style={{ maxWidth: 320, fontSize: 18 }} value={name} onChange={(e) => setName(e.target.value)} />
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select className="input" style={{ maxWidth: 140 }} value={doc.status} onChange={(e) => setDoc((d) => ({ ...d, status: e.target.value as Doc["status"] }))}>
            <option value="draft">草稿</option>
            <option value="published">已发布</option>
          </select>
          <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? "保存中…" : "保存"}</button>
        </div>
      </div>
      {err && <div style={{ color: "red", fontSize: 13, marginBottom: 8 }}>{err}</div>}
      {saved && <div style={{ color: "#16a34a", fontSize: 13, marginBottom: 8 }}>已保存（状态：{doc.status === "published" ? "已发布" : "草稿"}）</div>}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>
        {/* 编辑区 */}
        <div className="card" style={{ padding: 16 }}>
          <h2 style={{ fontSize: 15, margin: "0 0 10px" }}>编辑区块</h2>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
            {BLOCK_TYPES.map((t) => (
              <button key={t.key} className="btn" onClick={() => addBlock(t.key)}>＋ {t.label}</button>
            ))}
          </div>

          {doc.blocks.length === 0 && <div className="muted" style={{ fontSize: 13 }}>点击上方按钮添加区块。</div>}

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {doc.blocks.map((b, i) => (
              <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <span style={{ fontSize: 12, color: "#4f46e5", fontWeight: 600 }}>{BLOCK_TYPES.find((t) => t.key === b.type)?.label} #{i + 1}</span>
                  <div style={{ display: "flex", gap: 4 }}>
                    <button className="btn" onClick={() => move(i, -1)}>↑</button>
                    <button className="btn" onClick={() => move(i, 1)}>↓</button>
                    <button className="btn" onClick={() => removeBlock(i)}>✕</button>
                  </div>
                </div>
                {b.type === "image" ? (
                  <input className="input" value={b.url} onChange={(e) => updateBlock(i, { url: e.target.value })} placeholder="图片 URL" />
                ) : b.type === "button" ? (
                  <div style={{ display: "flex", gap: 6 }}>
                    <input className="input" value={b.text} onChange={(e) => updateBlock(i, { text: e.target.value })} placeholder="按钮文字" />
                    <input className="input" value={b.href} onChange={(e) => updateBlock(i, { href: e.target.value })} placeholder="链接" />
                  </div>
                ) : (
                  <textarea className="input" rows={b.type === "heading" ? 1 : 3} value={b.text} onChange={(e) => updateBlock(i, { text: e.target.value })} />
                )}
              </div>
            ))}
          </div>
        </div>

        {/* 预览区 */}
        <div className="card" style={{ padding: 16 }}>
          <h2 style={{ fontSize: 15, margin: "0 0 10px" }}>手机预览（H5）</h2>
          <div style={{ border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden", maxWidth: 420, margin: "0 auto" }}>
            <iframe title="preview" srcDoc={toHtml(doc)} style={{ width: "100%", height: 520, border: "none", background: "#fff" }} />
          </div>
          <p className="muted" style={{ fontSize: 12, textAlign: "center", marginTop: 8 }}>预览为移动端样式。保存后可嵌入活动邮件或分享链接。</p>
        </div>
      </div>
    </div>
  );
}
