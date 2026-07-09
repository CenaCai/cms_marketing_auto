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

interface Section {
  id: string;
  title: string;
  desc?: string;
  fields: SettingField[];
}

const SECTIONS: Section[] = [
  {
    id: "email",
    title: "邮件发送通道",
    desc: "配置 SMTP 后即可真实发送邮件；默认 mock 仅记录日志，便于先跑通流程。",
    fields: [
      { key: "email.provider", label: "发送通道", type: "select", options: ["mock", "smtp", "sendgrid", "ses"] },
      { key: "email.from", label: "发件人 (From)", type: "text", placeholder: "Marketing <noreply@example.com>" },
      { key: "email.smtp.host", label: "SMTP 主机", type: "text", placeholder: "smtp.gmail.com" },
      { key: "email.smtp.port", label: "SMTP 端口", type: "text", placeholder: "587" },
      { key: "email.smtp.secure", label: "SSL/TLS (465 常用)", type: "checkbox" },
      { key: "email.smtp.user", label: "SMTP 账号", type: "text", placeholder: "your@email.com" },
      { key: "email.smtp.pass", label: "SMTP 密码 / 授权码", type: "password" },
    ],
  },
  {
    id: "ai",
    title: "AI 配置（文案生成等）",
    desc: "选择模型供应商并填写 API Key（可填 OpenAI / DeepSeek 等兼容网关）。不填则使用本地智能模板生成，演示也能跑。",
    fields: [
      { key: "ai.provider", label: "AI 供应商", type: "select", options: ["mock", "openai", "anthropic", "ollama"] },
      { key: "ai.openaiKey", label: "OpenAI / 兼容网关 Key", type: "password", placeholder: "sk-..." },
      { key: "ai.openaiBaseUrl", label: "API Base URL", type: "text", placeholder: "https://api.openai.com/v1（DeepSeek: https://api.deepseek.com/v1）" },
      { key: "ai.openaiModel", label: "模型名", type: "text", placeholder: "gpt-4o-mini" },
      { key: "ai.anthropicKey", label: "Anthropic Key", type: "password" },
      { key: "ai.ollamaUrl", label: "Ollama 地址", type: "text", placeholder: "http://localhost:11434" },
    ],
  },
  {
    id: "mautic",
    title: "Mautic 集成（标签体系对齐）",
    desc: "对接 Mautic 实例，同步标签 / 分群 / 联系人。沙箱内不运行 Mautic，填写后可在「账号/集成」中触发同步。",
    fields: [
      { key: "mautic.enabled", label: "启用 Mautic 同步", type: "checkbox" },
      { key: "mautic.baseUrl", label: "Mautic Base URL", type: "text", placeholder: "https://your-mautic.example.com" },
      { key: "mautic.token", label: "API Token", type: "password" },
    ],
  },
];

export default function SettingsPage() {
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
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

  async function save(section: Section) {
    setErr("");
    setMsg("");
    setSavingId(section.id);
    try {
      const items = section.fields.map((f) => ({ key: f.key, value: values[f.key] ?? "" }));
      await api("/api/settings", { method: "PUT", body: JSON.stringify({ items }) });
      setMsg(`「${section.title}」已保存并即时生效（无需重启）。`);
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSavingId(null);
    }
  }

  if (loading) return <div className="card muted">加载中…</div>;

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: 4 }}>设置</h1>
      <p className="muted" style={{ fontSize: 13, marginBottom: 16 }}>
        后台配置，保存即生效（无需重启服务）。涉及密钥的配置均存于数据库，不会进入代码仓库。
      </p>

      {SECTIONS.map((section) => {
        const provider = values[section.fields[0]?.key] ?? "";
        return (
          <div className="card" key={section.id} style={{ marginBottom: 16 }}>
            <h2 style={{ fontSize: 16, marginBottom: 4 }}>{section.title}</h2>
            {section.desc && <p className="muted" style={{ fontSize: 13, margin: "0 0 12px" }}>{section.desc}</p>}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, maxWidth: 760 }}>
              {section.fields.map((f) => (
                <div key={f.key}>
                  <label className="muted" style={{ fontSize: 13 }}>{f.label}</label>
                  {f.type === "select" ? (
                    <select className="input" value={values[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value)}>
                      {(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
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

            {section.id === "email" && provider === "smtp" && !values["email.smtp.host"] && (
              <div style={{ color: "#d97706", fontSize: 13, marginTop: 12 }}>
                当前为 SMTP 模式但未填写主机，发送会报错。请填写 SMTP 主机/端口/账号/密码。
              </div>
            )}

            <div style={{ marginTop: 14 }}>
              <button className="btn btn-primary" onClick={() => save(section)} disabled={savingId === section.id}>
                {savingId === section.id ? "保存中…" : "保存"}
              </button>
            </div>
          </div>
        );
      })}

      {err && <div style={{ color: "red", fontSize: 13, marginTop: 6 }}>{err}</div>}
      {msg && <div style={{ color: "#16a34a", fontSize: 13, marginTop: 6 }}>{msg}</div>}

      <div className="card" style={{ marginTop: 8 }}>
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
