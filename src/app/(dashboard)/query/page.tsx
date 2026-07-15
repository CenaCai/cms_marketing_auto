"use client";

import { useState } from "react";
import { api } from "@/lib/api-client";

const DEFAULT_SQL = `-- 精准圈人：可写任意只读 SELECT，WHERE 中必须用 organizationId = CURRENT_ORG 限制本组织
-- 例：阿联酋 + 对 F1 活动有浏览行为 + 未购买 + 邮箱可触达 的用户
SELECT
    c.id,
    c.name,
    c.email,
    c.country,
    c.source,
    c.status
FROM Contact c
WHERE c.organizationId = CURRENT_ORG
  AND c.country = 'UAE'
  AND c.email IS NOT NULL
  AND c.status = 'active'
  AND c.id IN (
      SELECT contactId FROM Event
      WHERE organizationId = CURRENT_ORG
        AND eventType = 'BROWSE'
        AND eventName = 'F1_Event'
  )
  AND c.id NOT IN (
      SELECT contactId FROM Event
      WHERE organizationId = CURRENT_ORG
        AND eventType = 'PURCHASE'
  );`;

const DICTIONARY = [
  { table: "Contact", cols: "id, name, email, phone, country, city, language, source, status, lastActiveAt, organizationId" },
  { table: "Event", cols: "id, contactId, eventType(REGISTER/LOGIN/BROWSE/PURCHASE/REFUND/CUSTOM), eventName, source, properties, occurredAt, organizationId" },
  { table: "ContactTag", cols: "contactId, tagId" },
  { table: "Tag", cols: "id, name, color" },
  { table: "Segment", cols: "id, name, type(static/dynamic), rules" },
  { table: "Campaign", cols: "id, name, channel, status, segmentId, templateId" },
];

export default function SqlQueryPage() {
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    columns: string[];
    rows: Record<string, any>[];
    total: number;
    truncated?: boolean;
    note?: string;
  } | null>(null);
  const [segName, setSegName] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setError(null);
    setMsg(null);
    try {
      const data = await api<{
        columns: string[];
        rows: Record<string, any>[];
        total: number;
        truncated?: boolean;
        note?: string;
      }>("/api/query", { method: "POST", body: JSON.stringify({ sql }) });
      setResult(data);
    } catch (e: any) {
      setError(e.message || "查询失败");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  async function saveAsSegment() {
    if (!result) return;
    const ids = result.rows.map((r) => r.id).filter(Boolean);
    if (!ids.length) {
      setError("结果中没有 id 列，无法保存为分群（请在 SELECT 中包含 c.id）");
      return;
    }
    const name = segName.trim() || `SQL分群_${new Date().toISOString().slice(0, 10)}`;
    setSaving(true);
    setError(null);
    setMsg(null);
    try {
      const seg = await api<{ id: string }>("/api/segments", {
        method: "POST",
        body: JSON.stringify({ name, type: "static" }),
      });
      await api(`/api/segments/${seg.id}/members`, {
        method: "POST",
        body: JSON.stringify({ contactIds: ids }),
      });
      setMsg(`已保存为静态分群「${name}」（${ids.length} 人），可在「活动」页选择该分群批量发送。`);
    } catch (e: any) {
      setError(e.message || "保存分群失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">SQL 精准圈人</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          运营可写只读 SQL 圈定目标用户，结果可直接保存为分群并用于批量群发。查询在
          <code className="mx-1 rounded bg-gray-100 px-1 dark:bg-gray-800">organizationId = CURRENT_ORG</code>
          隔离范围内执行，仅允许 SELECT，所有查询留审计日志。
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          <textarea
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            spellCheck={false}
            className="h-72 w-full rounded-lg border border-gray-300 bg-white p-3 font-mono text-sm text-gray-800 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
            placeholder="SELECT ... FROM Contact WHERE organizationId = CURRENT_ORG ..."
          />
          <div className="flex items-center gap-3">
            <button
              onClick={run}
              disabled={loading}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? "运行中…" : "运行查询"}
            </button>
            <input
              value={segName}
              onChange={(e) => setSegName(e.target.value)}
              placeholder="分群名称（保存时用）"
              className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
            />
            <button
              onClick={saveAsSegment}
              disabled={saving || !result}
              className="rounded-lg border border-blue-600 px-4 py-2 text-sm font-medium text-blue-600 hover:bg-blue-50 disabled:opacity-50 dark:hover:bg-blue-950"
            >
              {saving ? "保存中…" : "保存为分群"}
            </button>
          </div>
          {error && (
            <div className="rounded-lg border-l-2 border-red-400 bg-red-50/40 px-3 py-2 text-sm text-red-700 dark:border-red-500 dark:bg-red-950/40 dark:text-red-300">
              {error}
            </div>
          )}
          {msg && (
            <div className="rounded-lg border-l-2 border-green-400 bg-green-50/40 px-3 py-2 text-sm text-green-700 dark:border-green-500 dark:bg-green-950/40 dark:text-green-300">
              {msg}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs dark:border-gray-700 dark:bg-gray-800">
          <div className="mb-2 font-semibold text-gray-700 dark:text-gray-200">可查询表字典</div>
          <ul className="space-y-2">
            {DICTIONARY.map((d) => (
              <li key={d.table}>
                <div className="font-mono text-blue-600 dark:text-blue-400">{d.table}</div>
                <div className="text-gray-500 dark:text-gray-400">{d.cols}</div>
              </li>
            ))}
          </ul>
          <div className="mt-3 text-gray-500 dark:text-gray-400">
            标签/兴趣建议用 <code>ContactTag</code> + <code>Tag</code> 关联查询；购买用{" "}
            <code>Event.eventType = 'PURCHASE'</code>。
          </div>
        </div>
      </div>

      {result && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm text-gray-500 dark:text-gray-400">
            <span>
              命中 <b className="text-gray-900 dark:text-gray-100">{result.total}</b> 人
              {result.truncated ? `（展示前 ${result.rows.length}）` : ""}
            </span>
            {result.note && <span className="text-amber-600">{result.note}</span>}
          </div>
          <div className="overflow-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300">
                <tr>
                  {result.columns.map((c) => (
                    <th key={c} className="whitespace-nowrap px-3 py-2 font-medium">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, i) => (
                  <tr key={i} className="border-t border-gray-100 dark:border-gray-800">
                    {result.columns.map((c) => (
                      <td key={c} className="whitespace-nowrap px-3 py-1.5 text-gray-800 dark:text-gray-200">
                        {String(row[c] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
                {result.rows.length === 0 && (
                  <tr>
                    <td colSpan={result.columns.length} className="px-3 py-4 text-center text-gray-400">
                      无匹配结果
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
