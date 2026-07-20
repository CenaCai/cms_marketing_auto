import { getMauticRuntime, setMauticRuntime, refreshMauticConfig } from "@/lib/mautic-config";
import type { MauticClient } from "./types";
import { MauticRestClient } from "./api";
import { MockMauticClient } from "./mock";

let cached: MauticClient | null = null;
let cacheKey = "";

// 根据后台实时配置选择 Mautic 客户端（未启用/未配置 → mock）。
export function getMauticClient(): MauticClient {
  const cfg = getMauticRuntime();
  const key = `${cfg.enabled}|${cfg.baseUrl}|${cfg.user}|${cfg.secret}`;
  if (cached && cacheKey === key) return cached;
  let client: MauticClient;
  if (cfg.enabled && cfg.baseUrl && cfg.user && cfg.secret) {
    client = new MauticRestClient(cfg.baseUrl, cfg.user, cfg.secret);
  } else {
    client = new MockMauticClient();
  }
  cached = client;
  cacheKey = key;
  return client;
}

export { refreshMauticConfig, setMauticRuntime };
export type * from "./types";
