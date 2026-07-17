"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

export default function DashboardPage() {
  const [stats, setStats] = useState<any>(null);

  useEffect(() => {
    Promise.all([
      api("/api/analytics?channel=EMAIL").catch(() => null),
      api("/api/contacts?limit=1").catch(() => null),
      api("/api/campaigns").catch(() => null),
    ]).then(([email, contacts, campaigns]) => {
      setStats({ email, contacts, campaigns });
    });
  }, []);

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: 16 }}>Dashboard</h1>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
        <div className="card">
          <div className="muted" style={{ fontSize: 13 }}>联系人总数</div>
          <div style={{ fontSize: 26, fontWeight: 700 }}>{stats?.contacts?.total ?? "—"}</div>
        </div>
        <div className="card">
          <div className="muted" style={{ fontSize: 13 }}>Campaign 数</div>
          <div style={{ fontSize: 26, fontWeight: 700 }}>{stats?.campaigns?.length ?? "—"}</div>
        </div>
        <div className="card">
          <div className="muted" style={{ fontSize: 13 }}>EDM 发送数</div>
          <div style={{ fontSize: 26, fontWeight: 700 }}>{stats?.email?.sent ?? "—"}</div>
        </div>
        <div className="card">
          <div className="muted" style={{ fontSize: 13 }}>EDM 打开率</div>
          <div style={{ fontSize: 26, fontWeight: 700 }}>{stats?.email?.openRate ?? "—"}%</div>
        </div>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h3 style={{ fontSize: 16, marginBottom: 8 }}>快速开始</h3>
        <ol className="muted" style={{ fontSize: 14, lineHeight: 1.8 }}>
          <li>在 <b>Settings</b> 中配置发送通道（Email / SMS provider）。</li>
          <li>在 <b>Contacts</b> 导入客户，打 <b>Tags</b> 并建 <b>Segments</b>。</li>
          <li>创建 <b>Templates</b> 与 <b>Campaigns</b>，触发批量发送。</li>
          <li>用 <b>AI Assistant</b> 生成文案 / 推荐分群 / 复盘。</li>
        </ol>
      </div>
    </div>
  );
}
