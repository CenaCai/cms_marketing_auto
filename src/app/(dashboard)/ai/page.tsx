"use client";

import { useState } from "react";
import { api } from "@/lib/api-client";

export default function AiPage() {
  const [activity, setActivity] = useState("F1 阿布扎比 2026");
  const [goal, setGoal] = useState("提升 F1 活动转化");
  const [copy, setCopy] = useState<any>(null);
  const [wf, setWf] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  async function genCopy() {
    setLoading(true);
    try {
      setCopy(
        await api("/api/ai/copy", {
          method: "POST",
          body: JSON.stringify({
            campaignName: goal,
            activityName: activity,
            channel: "EDM_BODY",
            language: "zh",
            cta: "立即购票",
          }),
        }),
      );
    } finally {
      setLoading(false);
    }
  }

  async function genWorkflow() {
    setLoading(true);
    try {
      setWf(await api("/api/ai/workflow", { method: "POST", body: JSON.stringify({ goal }) }));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: 16 }}>AI Assistant</h1>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div className="card">
          <h3 style={{ fontSize: 16, marginBottom: 8 }}>AI 文案生成</h3>
          <input className="input" placeholder="活动名称" value={activity} onChange={(e) => setActivity(e.target.value)} style={{ marginBottom: 8 }} />
          <button className="btn btn-primary" onClick={genCopy} disabled={loading}>生成文案</button>
          {copy && (
            <div style={{ marginTop: 12 }}>
              {copy.variants?.map((v: any, i: number) => (
                <div key={i} className="card" style={{ marginTop: 8, background: "#f8fafc" }}>
                  <div className="muted" style={{ fontSize: 12 }}>{v.note}</div>
                  <div style={{ fontSize: 14 }}>{v.content}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <h3 style={{ fontSize: 16, marginBottom: 8 }}>AI Workflow 草案</h3>
          <input className="input" placeholder="目标" value={goal} onChange={(e) => setGoal(e.target.value)} style={{ marginBottom: 8 }} />
          <button className="btn btn-primary" onClick={genWorkflow} disabled={loading}>生成草案</button>
          {wf && (
            <pre style={{ marginTop: 12, fontSize: 12, background: "#f8fafc", padding: 12, borderRadius: 8, overflow: "auto" }}>
              {JSON.stringify(wf, null, 2)}
            </pre>
          )}
        </div>
      </div>
      <div className="card muted" style={{ marginTop: 16, fontSize: 13 }}>
        当前 AI_PROVIDER=mock，返回结构化占位结果。在 <code>.env</code> 中切换 openai / anthropic / ollama 后即为真实大模型输出（接口已留好，见 THIRD_PARTY_INTEGRATIONS.md）。
      </div>
    </div>
  );
}
