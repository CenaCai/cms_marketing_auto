import { prisma } from "@/lib/db";
import { EMAIL_SETTING_KEYS, invalidateEmailConfigCache } from "@/lib/email-config";

export async function listSettings(): Promise<Record<string, string>> {
  const rows = await prisma.setting.findMany();
  const map: Record<string, string> = {};
  for (const k of EMAIL_SETTING_KEYS) map[k] = "";
  for (const r of rows) map[r.key] = r.value;
  return map;
}

export async function getSetting(key: string): Promise<string | null> {
  const r = await prisma.setting.findUnique({ where: { key } });
  return r?.value ?? null;
}

export async function saveSettings(items: { key: string; value: string }[]) {
  for (const it of items) {
    if (!it.key) continue;
    await prisma.setting.upsert({
      where: { key: it.key },
      update: { value: it.value },
      create: { key: it.key, value: it.value },
    });
  }
  invalidateEmailConfigCache();
}
