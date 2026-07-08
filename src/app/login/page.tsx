"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "@/lib/api-client";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit() {
    setErr("");
    setLoading(true);
    try {
      const res =
        mode === "login"
          ? await api("/api/auth/login", {
              method: "POST",
              body: JSON.stringify({ email, password }),
            })
          : await api("/api/auth/register", {
              method: "POST",
              body: JSON.stringify({ name, email, password }),
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
      <h1 style={{ fontSize: 20, marginBottom: 16 }}>CRM 营销自动化 · {mode === "login" ? "登录" : "注册"}</h1>
      {mode === "register" && (
        <input className="input" placeholder="姓名" value={name} onChange={(e) => setName(e.target.value)} style={{ marginBottom: 10 }} />
      )}
      <input className="input" placeholder="邮箱" value={email} onChange={(e) => setEmail(e.target.value)} style={{ marginBottom: 10 }} />
      <input className="input" type="password" placeholder="密码" value={password} onChange={(e) => setPassword(e.target.value)} style={{ marginBottom: 12 }} />
      {err && <div style={{ color: "red", fontSize: 13, marginBottom: 8 }}>{err}</div>}
      <button className="btn btn-primary" onClick={submit} disabled={loading} style={{ width: "100%" }}>
        {loading ? "处理中…" : mode === "login" ? "登录" : "注册并创建组织"}
      </button>
      <div style={{ marginTop: 12, fontSize: 13 }} className="muted">
        {mode === "login" ? (
          <span>没有账号？<a onClick={() => setMode("register")} style={{ color: "var(--brand)", cursor: "pointer" }}>去注册</a></span>
        ) : (
          <span>已有账号？<a onClick={() => setMode("login")} style={{ color: "var(--brand)", cursor: "pointer" }}>去登录</a></span>
        )}
      </div>
    </div>
  );
}
