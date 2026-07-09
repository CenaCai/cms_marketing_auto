// Mautic 集成运行时配置：读后台 Setting KV（设置 → Mautic 集成），保存即生效。
import { prisma } from "./db";

export interface MauticRuntimeConfig {
  enabled: boolean;
  baseUrl?: string;
  token?: string;
}

const KEYS = ["mautic.enabled", "mautic.baseUrl", "mautic.token"];

let runtime: MauticRuntimeConfig = {
  enabled: false,
};

export function getMauticRuntime(): MauticRuntimeConfig {
  return runtime;
}

export function setMauticRuntime(partial: Partial<MauticRuntimeConfig>): void {
  runtime = { ...runtime, ...partial };
}

export async function refreshMauticConfig(): Promise<MauticRuntimeConfig> {
  try {
    const rows = await prisma.setting.findMany({ where: { key: { in: KEYS } } });
    const m: Record<string, string> = {};
    rows.forEach((r) => (m[r.key] = r.value));
    runtime = {
      enabled: m["mautic.enabled"] === "true",
      baseUrl: m["mautic.baseUrl"] || undefined,
      token: m["mautic.token"] || undefined,
    };
  } catch {
    /* 数据库不可用时维持默认 */
  }
  return runtime;
}
