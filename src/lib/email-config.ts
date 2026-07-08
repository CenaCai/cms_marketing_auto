import { prisma } from "@/lib/db";

export interface EmailConfig {
  provider: string;
  from?: string;
  host?: string;
  port: number;
  secure: boolean;
  user?: string;
  pass?: string;
}

// 后台设置相关的 key（与 .env 同名，便于回退）
export const EMAIL_SETTING_KEYS = [
  "email.provider",
  "email.from",
  "email.smtp.host",
  "email.smtp.port",
  "email.smtp.secure",
  "email.smtp.user",
  "email.smtp.pass",
];

let cache: { data: EmailConfig; at: number } | null = null;
const TTL = 10_000; // 10s 内复用，避免每条邮件都查库

// 实时读取邮件配置：后台设置优先，缺失时回退到 .env
export async function getEmailConfig(): Promise<EmailConfig> {
  const now = Date.now();
  if (cache && now - cache.at < TTL) return cache.data;

  const rows = await prisma.setting.findMany({
    where: { key: { in: EMAIL_SETTING_KEYS } },
  });
  const m: Record<string, string> = {};
  for (const r of rows) m[r.key] = r.value;

  const data: EmailConfig = {
    provider: (m["email.provider"] || process.env.EMAIL_PROVIDER || "mock").toLowerCase(),
    from: m["email.from"] || process.env.EMAIL_FROM,
    host: m["email.smtp.host"] || process.env.SMTP_HOST,
    port: Number(m["email.smtp.port"] || process.env.SMTP_PORT || 587),
    secure: (m["email.smtp.secure"] || process.env.SMTP_SECURE) === "true",
    user: m["email.smtp.user"] || process.env.SMTP_USER,
    pass: m["email.smtp.pass"] || process.env.SMTP_PASS,
  };
  cache = { data, at: now };
  return data;
}

// 设置变更后主动失效缓存
export function invalidateEmailConfigCache() {
  cache = null;
}
