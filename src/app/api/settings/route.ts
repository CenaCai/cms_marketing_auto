import { NextRequest } from "next/server";
import { getSession, requireRole } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { listSettings, saveSettings } from "@/services/setting.service";
import { setEmailProviderMode } from "@/integrations/email";

// GET /api/settings -> 当前所有设置（KV）
export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "MARKETING_OPERATOR");
    return ok(await listSettings());
  });
}

// PUT /api/settings -> 批量 upsert 设置；若含 email.provider 则即时切换发送通道
export async function PUT(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "MARKETING_OPERATOR");
    const body = await req.json();
    const items: { key: string; value: string }[] = body.items ?? [];
    if (!Array.isArray(items)) throw new Error("items 必须是数组");

    await saveSettings(items);

    const providerItem = items.find((i) => i.key === "email.provider");
    if (providerItem) setEmailProviderMode(providerItem.value);

    return ok(await listSettings());
  });
}
