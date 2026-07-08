"use client";

// 浏览器端 API 客户端：从 localStorage 取 token，统一附带 Authorization。
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("cms_token");
}

export function setToken(t: string) {
  localStorage.setItem("cms_token", t);
}

export function clearToken() {
  localStorage.removeItem("cms_token");
}

export async function api<T = any>(
  path: string,
  opts: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const res = await fetch(path, {
    ...opts,
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(json.message || `请求失败 (${res.status})`);
  }
  return json.data as T;
}
