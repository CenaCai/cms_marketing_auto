"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api-client";

const TARGET_FIELDS = [
  { key: "name", label: "姓名" },
  { key: "email", label: "邮箱 *" },
  { key: "phone", label: "电话" },
  { key: "country", label: "国家" },
  { key: "city", label: "城市" },
  { key: "language", label: "语言" },
  { key: "source", label: "来源" },
] as const;

type Dedup = "email" | "phone" | "both";
const DEDUP_LABEL: Record<Dedup, string> = {
  email: "邮箱相同 → 视为同一联系人",
  phone: "手机号相同 → 视为同一联系人",
  both: "邮箱或手机号相同 → 视为同一联系人",
};

type Result = {
  success: number;
  failed: number;
  duplicate: number;
  errors: { row: number; reason: string }[];
};

export default function ImportContactsPage() {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [csvText, setCsvText] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [map, setMap] = useState<Record<string, string>>({});
  const [dedup, setDedup] = useState<Dedup>("email");
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [err, setErr] = useState("");

  function onCsvChange(text: string) {
    setCsvText(text);
    setResult(null);
    setErr("");
    const lines = text.trim().split(/\r?\n/);
    const firstLine = lines[0] || "";
    const cols = firstLine.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
    setColumns(cols);
    const auto: Record<string, string> = {};
    cols.forEach(function (c) {
      const lower = c.toLowerCase();
      TARGET_FIELDS.forEach(function (f) {
        if (lower === f.key || lower === f.label) auto[f.key] = c;
      });
    });
    setMap(auto);
    setStep(2);
  }

  async function doImport() {
    if (!csvText.trim()) return setErr("请粘贴 CSV 内容");
    if (columns.length === 0) return setErr("未识别到表头列");
    setImporting(true);
    setResult(null);
    try {
      const res = await api<Result>("/api/import", {
        method: "POST",
        body: JSON.stringify({ format: "csv", csvText: csvText, map: map, fileName: "contacts.csv", dedupRule: dedup }),
      });
      setResult(res);
      setStep(3);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setImporting(false);
    }
  }

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Link href="/contacts" className="btn">← 返回客户名单</Link>
      </div>
      <h1 style={{ fontSize: 22, marginBottom: 4 }}>导入联系人</h1>
      <p className="muted" style={{ fontSize: 13, marginBottom: 16 }}>
        支持 CSV 粘贴导入。流程：粘贴文件 → 字段映射 → 选择去重规则 → 预览导入结果。
      </p>

      {/* 步骤指示 */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {[
          { n: 1, t: "粘贴 CSV" },
          { n: 2, t: "字段映射" },
          { n: 3, t: "导入结果" },
        ].map(function (s) {
          return (
            <span key={s.n} style={{ fontSize: 13, padding: "4px 12px", borderRadius: 999, background: step >= s.n ? "var(--brand)" : "#f1f5f9", color: step >= s.n ? "#fff" : "#64748b" }}>
              {s.n}. {s.t}
            </span>
          );
        })}
      </div>

      {err && <div style={{ color: "red", fontSize: 13, marginBottom: 8 }}>{err}</div>}

      {step === 1 && (
        <div className="card" style={{ padding: 20 }}>
          <label className="muted" style={{ fontSize: 13 }}>粘贴 CSV（首行为表头）</label>
          <textarea
            className="input"
            rows={10}
            value={csvText}
            onChange={function (e) { onCsvChange(e.target.value); }}
            placeholder={"name,email,phone,city\n张三,zhang@x.com,13800000000,上海"}
            style={{ fontFamily: "ui-monospace, monospace", fontSize: 13, marginTop: 8 }}
          />
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            提示：也可通过 API / Webhook 写入联系人（见「集成」页）。Excel 导入等同按列映射处理。
          </p>
        </div>
      )}

      {step === 2 && (
        <div className="card" style={{ padding: 20 }}>
          <h2 style={{ fontSize: 16, marginBottom: 12 }}>字段映射</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
            {TARGET_FIELDS.map(function (f) {
              return (
                <div key={f.key}>
                  <label className="muted" style={{ fontSize: 13 }}>{f.label}</label>
                  <select className="input" value={map[f.key] ?? ""} onChange={function (e) { setMap(function (m) { var nm = Object.assign({}, m); nm[f.key] = e.target.value; return nm; }); }}>
                    <option value="">（不导入）</option>
                    {columns.map(function (c) {
                      return <option key={c} value={c}>{c}</option>;
                    })}
                  </select>
                </div>
              );
            })}
          </div>

          <h2 style={{ fontSize: 16, margin: "20px 0 12px" }}>去重规则</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {(Object.keys(DEDUP_LABEL) as Dedup[]).map(function (d) {
              return (
                <label key={d} style={{ fontSize: 14, display: "flex", gap: 8, alignItems: "center" }}>
                  <input type="radio" name="dedup" checked={dedup === d} onChange={function () { setDedup(d); }} />
                  {DEDUP_LABEL[d]}
                </label>
              );
            })}
            <p className="muted" style={{ fontSize: 12 }}>邮箱 + 手机号均为空 → 不导入。导入后系统发送前会自动过滤退订/黑名单/无有效联系方式用户。</p>
          </div>

          <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
            <button className="btn btn-primary" onClick={doImport} disabled={importing || columns.length === 0}>{importing ? "导入中…" : "开始导入"}</button>
            <button className="btn" onClick={function () { setStep(1); }}>上一步</button>
          </div>
        </div>
      )}

      {step === 3 && result && (
        <div className="card" style={{ padding: 20 }}>
          <h2 style={{ fontSize: 16, marginBottom: 12 }}>导入结果</h2>
          <div style={{ display: "flex", gap: 16 }}>
            <Stat label="成功" value={result.success} color="#16a34a" />
            <Stat label="重复" value={result.duplicate} color="#d97706" />
            <Stat label="失败" value={result.failed} color="#dc2626" />
          </div>
          {result.errors.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div className="muted" style={{ fontSize: 13, marginBottom: 6 }}>失败明细（前 10 条）：</div>
              <ul className="muted" style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
                {result.errors.slice(0, 10).map(function (e, i) {
                  return <li key={i}>第 {e.row} 行：{e.reason}</li>;
                })}
              </ul>
            </div>
          )}
          <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
            <Link href="/contacts" className="btn btn-primary">查看客户名单</Link>
            <button className="btn" onClick={function () { setCsvText(""); setColumns([]); setMap({}); setResult(null); setStep(1); }}>再导入一批</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ textAlign: "center", border: "1px solid var(--border)", borderRadius: 10, padding: "12px 20px" }}>
      <div style={{ fontSize: 24, fontWeight: 700, color }}>{value}</div>
      <div className="muted" style={{ fontSize: 13 }}>{label}</div>
    </div>
  );
}
