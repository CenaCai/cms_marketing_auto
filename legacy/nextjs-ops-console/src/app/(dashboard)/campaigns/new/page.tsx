"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api-client";

type Seg = { id: string; name: string; type: string };
type Tpl = { id: string; name: string; type: string };
type Tag = { id: string; name: string };
type Estimate = {
  total: number;
  reachable: number;
  unsubscribed: number;
  blacklisted: number;
  freqLimited: number;
  finalCount: number;
};

const CHANNELS = [
  { key: "EMAIL", label: "📧 邮件 EDM" },
  { key: "SMS", label: "💬 短信 SMS" },
];
const STEPS = [
  "基本信息",
  "目标人群",
  "选择渠道",
  "选择模板",
  "落地页 / 跳转",
  "发送前检查",
  "发送 / 定时",
];

export default function NewCampaignPage() {
  const router = useRouter();
  const [loadingRef, setLoadingRef] = useState(true);
  const [segments, setSegments] = useState<Seg[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [edmTpls, setEdmTpls] = useState<Tpl[]>([]);
  const [smsTpls, setSmsTpls] = useState<Tpl[]>([]);
  const [landingPages, setLandingPages] = useState<Tpl[]>([]);

  const [step, setStep] = useState(1);
  const [err, setErr] = useState("");

  // Step 1
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [activity, setActivity] = useState("");
  const [country, setCountry] = useState("");
  const [language, setLanguage] = useState("");

  // Step 2
  const [audienceType, setAudienceType] = useState<"segment" | "tags" | "sql">("segment");
  const [segmentId, setSegmentId] = useState("");
  const [tagIds, setTagIds] = useState<string[]>([]);
  const [sqlQuery, setSqlQuery] = useState("");
  const [sqlCount, setSqlCount] = useState<number | null>(null);
  const [sqlTesting, setSqlTesting] = useState(false);
  const [sqlTestErr, setSqlTestErr] = useState("");

  // Step 3
  const [channels, setChannels] = useState<string[]>(["EMAIL"]);

  // Step 4
  const [edmTemplateId, setEdmTemplateId] = useState("");
  const [smsTemplateId, setSmsTemplateId] = useState("");

  // Step 5
  const [landingPageId, setLandingPageId] = useState("");
  const [landingUrl, setLandingUrl] = useState("");

  // Step 6
  const [estimates, setEstimates] = useState<Record<string, Estimate>>({});
  const [estimating, setEstimating] = useState(false);

  // Step 7
  const [sendMode, setSendMode] = useState<"now" | "scheduled" | "draft">("now");
  const [scheduledAt, setScheduledAt] = useState("");
  const [saving, setSaving] = useState(false);
  const [createdId, setCreatedId] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [sg, tg, edm, sms, lp] = await Promise.all([
          api<Seg[]>("/api/segments"),
          api<Tag[]>("/api/tags"),
          api<Tpl[]>("/api/templates?type=EDM"),
          api<Tpl[]>("/api/templates?type=SMS"),
          api<Tpl[]>("/api/templates?type=LANDING"),
        ]);
        setSegments(sg ?? []);
        setTags(tg ?? []);
        setEdmTpls(edm ?? []);
        setSmsTpls(sms ?? []);
        setLandingPages(lp ?? []);
      } finally {
        setLoadingRef(false);
      }
    })();
  }, []);

  function toggleChannel(key: string) {
    setChannels((cs) => (cs.includes(key) ? cs.filter((c) => c !== key) : [...cs, key]));
  }
  function toggleTag(idv: string) {
    setTagIds((ts) => (ts.includes(idv) ? ts.filter((x) => x !== idv) : [...ts, idv]));
  }

  async function testSql() {
    if (!sqlQuery.trim()) return setSqlTestErr("请填写 SQL");
    setSqlTesting(true);
    setSqlTestErr("");
    try {
      const res = await api<{ total: number }>("/api/query", { method: "POST", body: JSON.stringify({ sql: sqlQuery }) });
      setSqlCount(res?.total ?? 0);
    } catch (e: any) {
      setSqlTestErr(e.message);
    } finally {
      setSqlTesting(false);
    }
  }

  async function runEstimates() {
    setEstimating(true);
    setErr("");
    try {
      const out: Record<string, Estimate> = {};
      for (const ch of channels) {
        const res = await api<Estimate>("/api/campaigns/estimate", {
          method: "POST",
          body: JSON.stringify({
            channel: ch,
            audienceType,
            segmentId: audienceType === "segment" ? segmentId : undefined,
            tagIds: audienceType === "tags" ? JSON.stringify(tagIds) : undefined,
            sqlQuery: audienceType === "sql" ? sqlQuery : undefined,
          }),
        });
        out[ch] = res;
      }
      setEstimates(out);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setEstimating(false);
    }
  }

  function validate(): string {
    if (!name.trim()) return "请填写活动名称";
    if (channels.length === 0) return "请至少选择一个渠道";
    if (channels.includes("EMAIL") && !edmTemplateId) return "已选 EDM 渠道，请选择 EDM 模板";
    if (channels.includes("SMS") && !smsTemplateId) return "已选 SMS 渠道，请选择 SMS 模板";
    if (audienceType === "segment" && !segmentId) return "请选择分群";
    if (audienceType === "tags" && tagIds.length === 0) return "请至少选择一个标签";
    if (audienceType === "sql" && !sqlQuery.trim()) return "请填写 SQL 圈人语句";
    if (sendMode === "scheduled" && !scheduledAt) return "请设置发送时间";
    return "";
  }

  async function create() {
    setErr("");
    if (step < 7) {
      // 进入第 6 步前先做估算
      if (step === 5) {
        await runEstimates();
      }
      return setStep((s) => (s + 1) as 1 | 2 | 3 | 4 | 5 | 6 | 7);
    }

    const v = validate();
    if (v) return setErr(v);

    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        name: name.trim(),
        objective: objective.trim() || undefined,
        activity: activity.trim() || undefined,
        country: country.trim() || undefined,
        language: language.trim() || undefined,
        channels: JSON.stringify(channels),
        edmTemplateId: channels.includes("EMAIL") ? edmTemplateId : undefined,
        smsTemplateId: channels.includes("SMS") ? smsTemplateId : undefined,
        landingPageId: landingPageId || undefined,
        landingUrl: landingUrl.trim() || undefined,
        audienceType,
        segmentId: audienceType === "segment" ? segmentId || undefined : undefined,
        tagIds: audienceType === "tags" ? JSON.stringify(tagIds) : undefined,
        sqlQuery: audienceType === "sql" ? sqlQuery : undefined,
        channel: channels[0],
        templateId: channels.includes("EMAIL") ? edmTemplateId : smsTemplateId,
        scheduledAt: sendMode === "scheduled" ? new Date(scheduledAt).toISOString() : undefined,
      };
      const created = await api<{ id: string }>("/api/campaigns", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      // 立即 / 定时发送：按渠道逐一下发
      if (sendMode !== "draft") {
        for (const ch of channels) {
          await api(`/api/campaigns/${created.id}/send`, {
            method: "POST",
            body: JSON.stringify({
              channel: ch,
              templateId: ch === "SMS" ? smsTemplateId : edmTemplateId,
              scheduleAt: sendMode === "scheduled" ? new Date(scheduledAt).toISOString() : undefined,
            }),
          });
        }
      }
      setCreatedId(created.id);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  if (loadingRef) return <div className="muted" style={{ padding: 24 }}>加载中…</div>;

  if (createdId) {
    return (
      <div className="card" style={{ padding: 24, maxWidth: 560 }}>
        <h1 style={{ fontSize: 20 }}>✅ 活动已创建{sendMode === "draft" ? "" : "并触发发送"}</h1>
        <p className="muted" style={{ fontSize: 14 }}>
          活动「{name}」已建立。
          {sendMode === "scheduled" && "已按定时入队。"}
        </p>
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <Link href={`/campaigns/${createdId}`} className="btn btn-primary">查看活动详情</Link>
          <Link href="/campaigns" className="btn">返回活动列表</Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Link href="/campaigns" className="btn">← 返回活动列表</Link>
      </div>
      <h1 style={{ fontSize: 22, marginBottom: 4 }}>创建营销活动</h1>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "12px 0 20px" }}>
        {STEPS.map((t, i) => {
          const n = i + 1;
          return (
            <span key={n} style={{ fontSize: 13, padding: "4px 10px", borderRadius: 999, background: step >= n ? "var(--brand)" : "#f1f5f9", color: step >= n ? "#fff" : "#64748b" }}>
              {n}. {t}
            </span>
          );
        })}
      </div>

      {err && <div style={{ color: "red", fontSize: 13, marginBottom: 8 }}>{err}</div>}

      <div className="card" style={{ padding: 20 }}>
        {step === 1 && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>活动名称 *</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="如：618 大促 EDM" />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>活动 / IP</label>
              <input className="input" value={activity} onChange={(e) => setActivity(e.target.value)} placeholder="如：F1 Madrid 2026" />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>目标国家</label>
              <input className="input" value={country} onChange={(e) => setCountry(e.target.value)} placeholder="如：UAE" />
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>目标语言</label>
              <input className="input" value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="如：zh / en" />
            </div>
            <div style={{ gridColumn: "1 / -1" }}>
              <label className="muted" style={{ fontSize: 13 }}>活动目标（可选）</label>
              <input className="input" value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="如：向 F1 潜客推送门票优惠" />
            </div>
          </div>
        )}

        {step === 2 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ display: "flex", gap: 8 }}>
              {(["segment", "tags", "sql"] as const).map((a) => (
                <button key={a} className="btn" style={{ background: audienceType === a ? "var(--brand)" : "#fff", color: audienceType === a ? "#fff" : "var(--text)" }} onClick={() => setAudienceType(a)}>
                  {a === "segment" ? "分群" : a === "tags" ? "标签组合" : "SQL 圈人"}
                </button>
              ))}
            </div>

            {audienceType === "segment" && (
              <div>
                <label className="muted" style={{ fontSize: 13 }}>选择分群 *</label>
                <select className="input" value={segmentId} onChange={(e) => setSegmentId(e.target.value)} style={{ marginTop: 6 }}>
                  <option value="">请选择分群</option>
                  {segments.map((s) => <option key={s.id} value={s.id}>{s.name}（{s.type === "dynamic" ? "动态" : "静态"}）</option>)}
                </select>
              </div>
            )}

            {audienceType === "tags" && (
              <div>
                <label className="muted" style={{ fontSize: 13 }}>标签组合（并集，拥有任一标签即命中）</label>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                  {tags.length === 0 ? <span className="muted">暂无标签，请先到「客户标签」创建</span> : tags.map((t) => (
                    <label key={t.id} style={{ fontSize: 14, border: "1px solid var(--border)", padding: "6px 10px", borderRadius: 8, background: tagIds.includes(t.id) ? "#eef2ff" : "#fff" }}>
                      <input type="checkbox" checked={tagIds.includes(t.id)} onChange={() => toggleTag(t.id)} /> {t.name}
                    </label>
                  ))}
                </div>
                <div style={{ marginTop: 8, fontSize: 13 }} className="muted">已选 {tagIds.length} 个标签</div>
              </div>
            )}

            {audienceType === "sql" && (
              <div>
                <label className="muted" style={{ fontSize: 13 }}>SQL 圈人（返回含 id 列的联系人）</label>
                <textarea className="input" rows={5} value={sqlQuery} onChange={(e) => setSqlQuery(e.target.value)} style={{ fontFamily: "ui-monospace, monospace", fontSize: 13, marginTop: 6 }}
                  placeholder={'SELECT id FROM Contact WHERE country = \'UAE\' AND status = \'active\''} />
                <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center" }}>
                  <button className="btn" onClick={testSql} disabled={sqlTesting} type="button">{sqlTesting ? "运行中…" : "试运行圈人"}</button>
                  {sqlCount !== null && !sqlTestErr && <span className="muted" style={{ fontSize: 13 }}>命中 {sqlCount} 人</span>}
                  {sqlTestErr && <span style={{ color: "#dc2626", fontSize: 13 }}>{sqlTestErr}</span>}
                  <Link href="/query" className="btn" style={{ fontSize: 13 }}>打开 SQL 圈人台 →</Link>
                </div>
              </div>
            )}
          </div>
        )}

        {step === 3 && (
          <div>
            <label className="muted" style={{ fontSize: 13 }}>选择渠道（可多选）</label>
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              {CHANNELS.map((c) => (
                <button key={c.key} className="btn" style={{ background: channels.includes(c.key) ? "var(--brand)" : "#fff", color: channels.includes(c.key) ? "#fff" : "var(--text)" }} onClick={() => toggleChannel(c.key)}>
                  {c.label}
                </button>
              ))}
            </div>
            <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>每个渠道将使用对应模板分别发送。</p>
          </div>
        )}

        {step === 4 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {channels.includes("EMAIL") && (
              <div>
                <label className="muted" style={{ fontSize: 13 }}>EDM 模板 *</label>
                <select className="input" value={edmTemplateId} onChange={(e) => setEdmTemplateId(e.target.value)} style={{ marginTop: 6 }}>
                  <option value="">请选择 EDM 模板</option>
                  {edmTpls.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </div>
            )}
            {channels.includes("SMS") && (
              <div>
                <label className="muted" style={{ fontSize: 13 }}>SMS 模板 *</label>
                <select className="input" value={smsTemplateId} onChange={(e) => setSmsTemplateId(e.target.value)} style={{ marginTop: 6 }}>
                  <option value="">请选择 SMS 模板</option>
                  {smsTpls.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </div>
            )}
          </div>
        )}

        {step === 5 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>关联落地页 / H5（可选）</label>
              <select className="input" value={landingPageId} onChange={(e) => setLandingPageId(e.target.value)} style={{ marginTop: 6 }}>
                <option value="">（不使用落地页）</option>
                {landingPages.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
              <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>模板中可用 {"{{landing_page_url}}"} 注入落地页链接。</p>
            </div>
            <div>
              <label className="muted" style={{ fontSize: 13 }}>跳转链接（无落地页时回退，可选）</label>
              <input className="input" value={landingUrl} onChange={(e) => setLandingUrl(e.target.value)} placeholder="https://…" style={{ marginTop: 6 }} />
            </div>
          </div>
        )}

        {step === 6 && (
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
              <button className="btn btn-primary" onClick={runEstimates} disabled={estimating} type="button">{estimating ? "估算中…" : "重新估算"}</button>
              <span className="muted" style={{ fontSize: 13 }}>按渠道展示过滤后的可发送人数</span>
            </div>
            {Object.keys(estimates).length === 0 ? (
              <div className="muted" style={{ fontSize: 14 }}>点击「重新估算」查看可触达人群与各项过滤。</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                {channels.map((ch) => {
                  const e = estimates[ch];
                  if (!e) return null;
                  return (
                    <div key={ch}>
                      <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 6 }}>{ch === "EMAIL" ? "📧 邮件 EDM" : "💬 短信 SMS"}</div>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                        <tbody>
                          <Row label="总人数" value={e.total} />
                          <Row label="可触达（有有效联系方式）" value={e.reachable} />
                          <Row label="退订过滤" value={e.unsubscribed} tone="warn" />
                          <Row label="黑名单 / bounce 过滤" value={e.blacklisted} tone="warn" />
                          <Row label="频控过滤（24h 上限）" value={e.freqLimited} tone="warn" />
                          <Row label="✅ 实际可发送" value={e.finalCount} tone="ok" bold />
                        </tbody>
                      </table>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {step === 7 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn" style={{ background: sendMode === "now" ? "var(--brand)" : "#fff", color: sendMode === "now" ? "#fff" : "var(--text)" }} onClick={() => setSendMode("now")}>立即发送</button>
              <button className="btn" style={{ background: sendMode === "scheduled" ? "var(--brand)" : "#fff", color: sendMode === "scheduled" ? "#fff" : "var(--text)" }} onClick={() => setSendMode("scheduled")}>定时发送</button>
              <button className="btn" style={{ background: sendMode === "draft" ? "var(--brand)" : "#fff", color: sendMode === "draft" ? "#fff" : "var(--text)" }} onClick={() => setSendMode("draft")}>仅存草稿</button>
            </div>
            {sendMode === "scheduled" && (
              <div>
                <label className="muted" style={{ fontSize: 13 }}>发送时间</label>
                <input className="input" type="datetime-local" value={scheduledAt} onChange={(e) => setScheduledAt(e.target.value)} style={{ marginTop: 6 }} />
              </div>
            )}
            <div className="muted" style={{ fontSize: 13 }}>
              渠道：{channels.map((c) => (c === "EMAIL" ? "EDM" : "SMS")).join(" + ")} ｜ 人群：
              {audienceType === "segment" ? "分群" : audienceType === "tags" ? "标签组合" : "SQL 圈人"} ｜
              落地页：{landingPageId ? "已关联" : landingUrl ? "跳转链接" : "无"}
            </div>
          </div>
        )}

        <div style={{ marginTop: 18, display: "flex", gap: 8 }}>
          {step > 1 && <button className="btn" onClick={() => setStep((s) => (s - 1) as 1 | 2 | 3 | 4 | 5 | 6 | 7)}>上一步</button>}
          <button className="btn btn-primary" onClick={create} disabled={saving}>
            {saving ? "处理中…" : step < 7 ? "下一步" : sendMode === "draft" ? "创建活动" : "创建并发送"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, tone, bold }: { label: string; value: number; tone?: "warn" | "ok"; bold?: boolean }) {
  const color = tone === "ok" ? "#16a34a" : tone === "warn" ? "#d97706" : "var(--text)";
  return (
    <tr style={{ borderTop: "1px solid var(--border)" }}>
      <td style={{ padding: "7px 12px" }} className="muted">{label}</td>
      <td style={{ padding: "7px 12px", textAlign: "right", fontWeight: bold ? 700 : 400, color }}>{value}</td>
    </tr>
  );
}
