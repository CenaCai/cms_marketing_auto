"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

interface SettingField {
  key: string;
  label: string;
  type: "text" | "password" | "select" | "checkbox";
  placeholder?: string;
  options?: string[];
}

const FIELDS: SettingField[] = [
  { key: "email.provider", label: "发送通道", type: "select", options: ["mock", "smtp", "sendgrid", "ses"] },
  { key: "email.from", label: "发件人 (From)", type: "text", placeholder: "Marketing <noreply@example.com>" },
  { key: "email.smtp.host", label: "SMTP 主机", type: "text", placeholder: "smtp.gmail.com" },
  { key: "email.smtp.port", label: "SMTP 端口", type: "text", placeholder: "587" },
  { key: "email.smtp.secure", label: "SSL/TLS (465 常用)", type: "checkbox" },
  { key: "email.smtp.user", label: "SMTP 账号", type: "text", placeholder: "your@email.com" },
  { key: "email.smtp.pass", label: "SMTP 密码 / 授权码", type: "password" },
];

export default function SettingsPage() {
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function load() {
    setLoading(true);
    try {
      const data = await api<Record<string, string>>("/api/settings");
      setValues(data ?? {});
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function set(key: string, v: string) {
    setValues((prev) => ({ ...prev, [key]: v }));
  }

  async function save() {
    setErr("");
    setMsg("");
    setSaving(true);
    try {
      const items = FIELDS.map((f) => ({ key: f.key, value: values[f.key] ?? "" }));
      await api("/api/settings", { method: "PUT", body: JSON.stringify({ items }) });
      setMsg("已保存。发送通道已即时生效（无需重启）。");
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  const provider = values["email.provider"] || "mock";

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: 4 }}>设置 · 邮件发送通道</h1>
      <p className="muted" style={{ fontSize: 13, marginBottom: 16 }}>
        在这里配置你的邮箱（SMTP），系统即可真实发送邮件。默认 mock 模式仅记录日志、不真实发送，便于先跑通流程。
      </p>

      {loading ? (
        <div className="card muted">加载中…</div>
      ) : (
        <div className="card">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, maxWidth: 720 }}>
            {FIELDS.map((f) => (
              <div key={f.key}>
                <label className="muted" style={{ fontSize: 13 }}>{f.label}</label>
                {f.type === "select" ? (
                  <select className="input" value={values[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value)}>
                    {(f.options ?? []).map((o) => (
                      <option key={o} value={o}>{o}</option>
                    ))}
                  </select>
                ) : f.type === "checkbox" ? (
                  <div style={{ paddingTop: 8 }}>
                    <label style={{ fontSize: 14 }}>
                      <input type="checkbox" checked={values[f.key] === "true"} onChange={(e) => set(f.key, e.target.checked ? "true" : "false")} /> 启用
                    </label>
                  </div>
                ) : (
                  <input className="input" type={f.type} value={values[f.key] ?? ""} placeholder={f.placeholder} onChange={(e) => set(f.key, e.target.value)} />
                )}
              </div>
            ))}
          </div>

          {provider === "smtp" && !values["email.smtp.host"] && (
            <div style={{ color: "#d97706", fontSize: 13, marginTop: 12 }}>
              当前为 SMTP 模式但未填写主机，发送会报错。请填写 SMTP 主机/端口/账号/密码。
            </div>
          )}

          {err && <div style={{ color: "red", fontSize: 13, marginTop: 10 }}>{err}</div>}
          {msg && <div style={{ color: "#16a34a", fontSize: 13, marginTop: 10 }}>{msg}</div>}

          <div style={{ marginTop: 16 }}>
            <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? "保存中…" : "保存设置"}</button>
          </div>
        </div>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <h3 style={{ fontSize: 15, marginBottom: 8 }}>常见邮箱 SMTP 参考</h3>
        <ul className="muted" style={{ fontSize: 13, lineHeight: 1.8, margin: 0, paddingLeft: 18 }}>
          <li>Gmail：smtp.gmail.com / 587 / 需开启“应用专用密码”</li>
          <li>企业邮箱（腾讯/阿里）：参考服务商文档的 SMTP 地址与端口</li>
          <li>Amazon SES SMTP / Mailgun / SendGrid：填入对应 SMTP 凭据</li>
          <li>本地测试：可用 Mailpit、MailHog 等本地 SMTP 收信</li>
        </ul>
      </div>
    </div>
  );
}
