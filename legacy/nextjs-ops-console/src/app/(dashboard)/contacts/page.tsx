"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api-client";

type Contact = {
  id: string;
  name?: string;
  email?: string;
  phone?: string;
  country?: string;
  city?: string;
  status: string;
  createdAt: string;
};

const TARGET_FIELDS = [
  { key: "name", label: "姓名" },
  { key: "email", label: "邮箱 *" },
  { key: "phone", label: "电话" },
  { key: "country", label: "国家" },
  { key: "city", label: "城市" },
  { key: "language", label: "语言" },
  { key: "source", label: "来源" },
] as const;

export default function ContactsPage() {
  const [list, setList] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [formOpen, setFormOpen] = useState(false);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [country, setCountry] = useState("");
  const [city, setCity] = useState("");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  // CSV 导入
  const [importOpen, setImportOpen] = useState(false);
  const [csvText, setCsvText] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [map, setMap] = useState<Record<string, string>>({});
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{ success: number; failed: number; duplicate: number; errors: { row: number; reason: string }[] } | null>(null);

  // ---- ContactOut 导入潜客 ----
  const [coOpen, setCoOpen] = useState(false);
  const [coJobTitle, setCoJobTitle] = useState("");
  const [coCompany, setCoCompany] = useState("");
  const [coLocation, setCoLocation] = useState("");
  const [coLimit, setCoLimit] = useState(25);
  const [coImporting, setCoImporting] = useState(false);
  const [coResult, setCoResult] = useState<ContactOutResult | null>(null);
  const [coErr, setCoErr] = useState("");

  async function load(q = "") {
    setLoading(true);
    try {
      const data = await api<{ items: Contact[]; total: number }>(
        `/api/contacts?limit=200${q ? `&search=${encodeURIComponent(q)}` : ""}`,
      );
      setList(data?.items ?? []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function openNew() {
    setName("");
    setEmail("");
    setPhone("");
    setCountry("");
    setCity("");
    setErr("");
    setFormOpen(true);
  }

  async function save() {
    setErr("");
    if (!email.trim() && !phone.trim()) {
      setErr("至少填写邮箱或电话");
      return;
    }
    setSaving(true);
    try {
      await api("/api/contacts", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim() || undefined,
          email: email.trim() || undefined,
          phone: phone.trim() || undefined,
          country: country.trim() || undefined,
          city: city.trim() || undefined,
        }),
      });
      setFormOpen(false);
      await load(search);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  // ---- CSV 导入 ----
  function onCsvChange(text: string) {
    setCsvText(text);
    setImportResult(null);
    const firstLine = text.trim().split(/\r?\n/)[0] || "";
    const cols = firstLine.split(",").map((s) => s.trim()).filter(Boolean);
    setColumns(cols);
    // 自动按列名匹配
    const auto: Record<string, string> = {};
    cols.forEach((c) => {
      const lower = c.toLowerCase();
      TARGET_FIELDS.forEach((f) => {
        if (lower === f.key || lower === f.label) auto[f.key] = c;
      });
    });
    setMap(auto);
  }
  async function doImport() {
    if (!csvText.trim()) return setErr("请粘贴 CSV 内容");
    setImporting(true);
    setImportResult(null);
    try {
      const res = await api<{ success: number; failed: number; duplicate: number; errors: { row: number; reason: string }[] }>(
        "/api/import",
        {
          method: "POST",
          body: JSON.stringify({ format: "csv", csvText, map, fileName: "contacts.csv" }),
        },
      );
      setImportResult(res);
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setImporting(false);
    }
  }

  async function doContactOutImport() {
    if (coImporting) return;
    setCoErr("");
    setCoResult(null);
    setCoImporting(true);
    try {
      const res = await api<ContactOutResult>("/api/integrations/contactout/import", {
        method: "POST",
        body: JSON.stringify({
          job_title: splitList(coJobTitle),
          company: splitList(coCompany),
          location: splitList(coLocation),
          limit: coLimit,
        }),
      });
      setCoResult(res);
      await load(search);
    } catch (e: any) {
      setCoErr(e.message);
    } finally {
      setCoImporting(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 22 }}>客户名单（邮箱地址）</h1>
        <div style={{ display: "flex", gap: 8 }}>
          <input className="input" style={{ maxWidth: 240 }} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索姓名/邮箱/电话" onKeyDown={(e) => e.key === "Enter" && load(search)} />
          <button className="btn" onClick={() => load(search)}>搜索</button>
          <button className="btn" onClick={() => { setCsvText(""); setColumns([]); setMap({}); setImportResult(null); setImportOpen(true); }}>CSV 批量导入</button>
          <button className="btn" onClick={() => { setCoOpen(true); setCoResult(null); setCoErr(""); }}>ContactOut 导入潜客</button>
          <button className="btn btn-primary" onClick={openNew}>＋ 新增客户</button>
        </div>
      </div>

      {err && <div style={{ color: "red", fontSize: 13, marginBottom: 8 }}>{err}</div>}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 24 }} className="muted">加载中…</div>
        ) : list.length === 0 ? (
          <div style={{ padding: 24 }} className="muted">还没有客户，点击“新增客户”或“CSV 批量导入”。</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                <th style={{ padding: "10px 14px" }}>姓名</th>
                <th style={{ padding: "10px 14px" }}>邮箱</th>
                <th style={{ padding: "10px 14px" }}>电话</th>
                <th style={{ padding: "10px 14px" }}>地区</th>
                <th style={{ padding: "10px 14px" }}>状态</th>
              </tr>
            </thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "10px 14px" }}>
                    <Link href={`/contacts/${c.id}`} style={{ color: "var(--brand)", textDecoration: "none" }}>{c.name || "—"}</Link>
                  </td>
                  <td style={{ padding: "10px 14px" }}>{c.email || "—"}</td>
                  <td style={{ padding: "10px 14px" }}>{c.phone || "—"}</td>
                  <td style={{ padding: "10px 14px" }} className="muted">{[c.city, c.country].filter(Boolean).join(" / ") || "—"}</td>
                  <td style={{ padding: "10px 14px" }}>
                    <span style={{ fontSize: 12, color: c.status === "active" ? "#16a34a" : "#dc2626" }}>{c.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {formOpen && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 16, marginBottom: 12 }}>新增客户</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>姓名</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>邮箱 *</label>
              <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="customer@example.com" />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>电话</label>
              <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>城市</label>
              <input className="input" value={city} onChange={(e) => setCity(e.target.value)} />
            </div>
          </div>
          {err && <div style={{ color: "red", fontSize: 13, marginTop: 8 }}>{err}</div>}
          <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
            <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? "保存中…" : "保存客户"}</button>
            <button className="btn" onClick={() => setFormOpen(false)}>取消</button>
          </div>
        </div>
      )}

      {/* CSV 导入 */}
      {importOpen && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 16, marginBottom: 8 }}>CSV 批量导入客户</h2>
          <p className="muted" style={{ fontSize: 13, marginBottom: 8 }}>粘贴 CSV（首行为表头），下方将 CSV 列映射到系统字段。示例：<br />name,email,phone,city<br />张三,zhang@x.com,13800000000,上海</p>
          <textarea className="input" rows={6} value={csvText} onChange={(e) => onCsvChange(e.target.value)} placeholder="粘贴 CSV 文本" style={{ fontFamily: "ui-monospace, monospace", fontSize: 13 }} />

          {columns.length > 0 && (
            <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
              {TARGET_FIELDS.map((f) => (
                <div key={f.key}>
                  <label className="muted" style={{ fontSize: 13 }}>{f.label}</label>
                  <select className="input" value={map[f.key] ?? ""} onChange={(e) => setMap((m) => ({ ...m, [f.key]: e.target.value }))}>
                    <option value="">（不导入）</option>
                    {columns.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          )}

          {err && <div style={{ color: "red", fontSize: 13, marginTop: 8 }}>{err}</div>}

          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button className="btn btn-primary" onClick={doImport} disabled={importing || columns.length === 0}>{importing ? "导入中…" : "开始导入"}</button>
            <button className="btn" onClick={() => setImportOpen(false)}>关闭</button>
          </div>

          {importResult && (
            <div style={{ marginTop: 12, fontSize: 13 }}>
              <div style={{ color: "#16a34a" }}>导入完成：成功 {importResult.success} / 重复 {importResult.duplicate} / 失败 {importResult.failed}</div>
              {importResult.errors.length > 0 && (
                <ul className="muted" style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                  {importResult.errors.slice(0, 10).map((e, i) => (
                    <li key={i}>第 {e.row} 行：{e.reason}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {/* ContactOut 导入潜客 */}
      {coOpen && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 16, marginBottom: 8 }}>从 ContactOut 导入潜客（B2B 数据源）</h2>
          <p className="muted" style={{ fontSize: 13, marginBottom: 12 }}>
            按条件从 ContactOut 拉取潜客，写入「数据资产层」并自动打「潜客」标签（按邮箱去重）。多个值用逗号分隔，如 <code>CEO,VP Sales</code>。
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>职位 job_title（逗号分隔）</label>
              <input className="input" value={coJobTitle} onChange={(e) => setCoJobTitle(e.target.value)} placeholder="CEO,VP Sales" />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>公司 company（逗号分隔）</label>
              <input className="input" value={coCompany} onChange={(e) => setCoCompany(e.target.value)} placeholder="Acme,Global Corp" />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>地区 location（逗号分隔）</label>
              <input className="input" value={coLocation} onChange={(e) => setCoLocation(e.target.value)} placeholder="Singapore,London" />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>拉取数量 limit</label>
              <input className="input" type="number" min={1} value={coLimit} onChange={(e) => setCoLimit(Number(e.target.value) || 25)} />
            </div>
          </div>

          {coErr && <div style={{ color: "red", fontSize: 13, marginTop: 8 }}>{coErr}</div>}

          <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
            <button className="btn btn-primary" onClick={doContactOutImport} disabled={coImporting}>{coImporting ? "导入中…" : "开始导入"}</button>
            <button className="btn" onClick={() => setCoOpen(false)}>关闭</button>
          </div>

          {coResult && (
            <div style={{ marginTop: 14 }}>
              {!coResult.compliance.enabled && (
                <div style={{ background: "#fef3c7", color: "#92400e", fontSize: 13, padding: "8px 12px", borderRadius: 8, marginBottom: 10 }}>
                  ⚠️ ContactOut 未启用或未配置 API key，当前返回样例预览，<b>不会写入数据库</b>。请在 .env 设置 CONTACTOUT_ENABLED=true 与 CONTACTOUT_API_KEY。
                </div>
              )}
              <div style={{ display: "flex", gap: 16 }}>
                <Stat label="导入" value={coResult.imported} color="#16a34a" />
                <Stat label="匹配总数" value={coResult.totalAvailable} color="#2563eb" />
                <Stat label="跳过(无邮箱)" value={coResult.skippedNoEmail} color="#d97706" />
                <Stat label="打标" value={coResult.tagApplied} color="#7c3aed" />
              </div>
              <p className="muted" style={{ fontSize: 13, marginTop: 10 }}>{coResult.note}</p>
              {coResult.skipped.length > 0 && (
                <ul className="muted" style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 13 }}>
                  {coResult.skipped.slice(0, 10).map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              )}
              <p className="muted" style={{ fontSize: 12, marginTop: 10, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                🔒 合规：导入仅写入数据资产层。正式触达前需确认合法基础（legitimate interest 或 consent）并保留退订渠道。
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

type ContactOutResult = {
  requested: number;
  imported: number;
  skippedNoEmail: number;
  tagApplied: number;
  totalAvailable: number;
  skipped: string[];
  note: string;
  compliance: { enabled: boolean; needsReview: boolean; warning: string };
};

function splitList(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ textAlign: "center", border: "1px solid var(--border)", borderRadius: 10, padding: "12px 20px" }}>
      <div style={{ fontSize: 24, fontWeight: 700, color }}>{value}</div>
      <div className="muted" style={{ fontSize: 13 }}>{label}</div>
    </div>
  );
}
