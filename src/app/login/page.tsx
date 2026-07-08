"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "@/lib/api-client";

export default function LoginPage() {
  const router = useRouter();
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit() {
    setErr("");
    setLoading(true);
    try {
      const res = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: account, password }),
      });
      setToken(res.token);
      router.push("/");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 380, margin: "80px auto" }} className="card">
      <h1 style={{ fontSize: 20, marginBottom: 16 }}>CRM 营销自动化 · 登录</h1>
      <input
        className="input"
        placeholder="邮箱或用户名"
        value={account}
        onChange={(e) => setAccount(e.target.value)}
        style={{ marginBottom: 10 }}
      />
      <input
        className="input"
        type="password"
        placeholder="密码"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        style={{ marginBottom: 12 }}
      />
      {err && <div style={{ color: "red", fontSize: 13, marginBottom: 8 }}>{err}</div>}
      <button className="btn btn-primary" onClick={submit} disabled={loading} style={{ width: "100%" }}>
        {loading ? "处理中…" : "登录"}
      </button>
    </div>
  );
}
