// Mautic 集成运行时配置：读后台 Setting KV（设置 → Mautic 集成），保存即生效。
// 采用 Mautic 标准的 Basic Auth（API 公钥作为 user、私钥作为 secret）。
import { prisma } from "./db";

export interface MauticRuntimeConfig {
  enabled: boolean;
  baseUrl?: string;
  user?: string; // Mautic API 公钥 / API 用户名
  secret?: string; // Mautic API 私钥 / 密码
}

const KEYS = ["mautic.enabled", "mautic.baseUrl", "mautic.user", "mautic.secret"];

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
      user: m["mautic.user"] || undefined,
      secret: m["mautic.secret"] || undefined,
    };
  } catch {
    /* 数据库不可用时维持默认 */
  }
  return runtime;
}
