"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";

export default function ReportsPage() {
  const [email, setEmail] = useState<any>(null);
  const [sms, setSms] = useState<any>(null);

  useEffect(() => {
    api("/api/analytics?channel=EMAIL").then(setEmail).catch(() => {});
    api("/api/analytics?channel=SMS").then(setSms).catch(() => {});
  }, []);

  const Card = ({ title, d }: { title: string; d: any }) => (
    <div className="card">
      <h3 style={{ fontSize: 16, marginBottom: 8 }}>{title}</h3>
      {!d ? (
        <div className="muted">加载中…</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 14 }}>
          {Object.entries(d).map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px dashed var(--border)", padding: "4px 0" }}>
              <span className="muted">{k}</span>
              <b>{String(v)}</b>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: 16 }}>Reports</h1>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card title="EDM 统计" d={email} />
        <Card title="SMS 统计" d={sms} />
      </div>
    </div>
  );
}
