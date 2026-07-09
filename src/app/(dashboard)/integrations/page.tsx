"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

interface SyncOut {
  mode: string;
  result: Record<string, unknown>;
}

export default function IntegrationsPage() {
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [out, setOut] = useState<SyncOut | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  async function load() {
    setLoading(true);
    try {
      const data = await api<Record<string, string>>("/api/settings");
      setSettings(data ?? {});
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const enabled = settings["mautic.enabled"] === "true" && !!settings["mautic.baseUrl"];
  const webhookUrl = `${typeof window !== "undefined" ? window.location.origin : ""}/api/integrations/mautic/webhook`;

  async function runSync(mode: "push" | "pull") {
    setBusy(mode);
    setErr("");
    setMsg("");
    try {
      const data = await api<SyncOut>("/api/integrations/mautic/sync", {
        method: "POST",
        body: JSON.stringify({ mode }),
      });
      setOut(data);
      setMsg(mode === "push" ? "已推送数据到 Mautic 执行层。" : "已从 Mautic 拉取标签/分群。");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function simulate() {
    setBusy("simulate");
    setErr("");
    setMsg("");
    try {
      const contacts = await api<any>("/api/contacts");
      const rows: { email: string }[] =
        contacts?.rows ?? contacts?.data?.rows ?? contacts?.items ?? [];
      const email = rows[0]?.email;
      if (!email) {
        setErr("没有可用于模拟的联系人，请先导入一个带邮箱的联系人。");
        return;
      }
      const res = await fetch(webhookUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event: "email_opened", email, timestamp: Math.floor(Date.now() / 1000) }),
      });
      const j = await res.json();
      setOut({ mode: "webhook-sim", result: j });
      setMsg(`已模拟 Mautic 打开事件回流（${email}）→ 写入事件中心。`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <div className="card muted">加载中…</div>;

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: 4 }}>集成（Mautic 执行层）</h1>
      <p className="muted" style={{ fontSize: 13, marginBottom: 16 }}>
        混合模式：Next.js 做「数据资产层」（联系人 / 标签 / 分群 / SQL 圈人），Mautic 做「执行层」（发信 / 落地页 / 可视化 Campaign）。
        下方负责把数据推送给 Mautic，并把 Mautic 的打开/点击行为回流到本系统事件中心，闭合营销闭环。
      </p>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 8 }}>连接状态</h2>
        <div style={{ fontSize: 14 }}>
          {enabled ? (
            <span style={{ color: "#16a34a" }}>● 已配置（{settings["mautic.baseUrl"]}）— 可触发真实同步</span>
          ) : (
            <span style={{ color: "#d97706" }}>● 未启用 / 未配置 — 当前为 mock 模式（不会真实连接 Mautic）</span>
          )}
        </div>
        <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>
          配置入口：左侧「设置 → Mautic 集成」填写 Base URL、API 公钥(user)、私钥(secret) 并启用。保存即生效。
        </p>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 8 }}>行为回流 Webhook</h2>
        <p className="muted" style={{ fontSize: 13, marginBottom: 6 }}>
          在 Mautic 后台「Webhook」中填入下方地址，即可把邮件打开/点击/退订实时回写本系统事件中心：
        </p>
        <code
          style={{
            display: "block",
            background: "#0f172a",
            color: "#e2e8f0",
            padding: 10,
            borderRadius: 8,
            fontSize: 12,
            wordBreak: "break-all",
          }}
        >
          {webhookUrl}
        </code>
        <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
          多组织时追加 <code>?org=&lt;组织ID&gt;</code>；单组织默认指向首个组织。
        </p>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 8 }}>同步操作</h2>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button className="btn btn-primary" onClick={() => runSync("push")} disabled={busy !== null}>
            {busy === "push" ? "推送中…" : "① 推送数据到 Mautic"}
          </button>
          <button className="btn" onClick={() => runSync("pull")} disabled={busy !== null}>
            {busy === "pull" ? "拉取中…" : "② 从 Mautic 拉取标签/分群"}
          </button>
          <button className="btn" onClick={simulate} disabled={busy !== null}>
            {busy === "simulate" ? "模拟中…" : "③ 模拟行为回流（测试）"}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>
          ① 把本系统联系人(带标签)/静态分群推到 Mautic，作为发送目标；② 把 Mautic 侧新增的标签/分群拉回本系统；③ 在本地模拟一次 Mautic 打开事件，验证回流闭环。
        </p>
      </div>

      {out && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ fontSize: 15, marginBottom: 6 }}>执行结果（{out.mode}）</h3>
          <pre
            style={{
              background: "#f8fafc",
              border: "1px solid var(--border)",
              borderRadius: 8,
              padding: 12,
              fontSize: 12,
              overflowX: "auto",
              margin: 0,
            }}
          >
            {JSON.stringify(out.result, null, 2)}
          </pre>
        </div>
      )}

      {err && <div style={{ color: "red", fontSize: 13 }}>{err}</div>}
      {msg && <div style={{ color: "#16a34a", fontSize: 13 }}>{msg}</div>}
    </div>
  );
}
