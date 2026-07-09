import { NextRequest } from "next/server";
import { getSession, requireRole, requirePermission } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { listSettings, saveSettings } from "@/services/setting.service";
import { setEmailProviderMode } from "@/integrations/email";
import { refreshAiConfig } from "@/lib/ai-config";
import { refreshMauticConfig } from "@/lib/mautic-config";

// GET /api/settings -> 当前所有设置（KV）
export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "MARKETING_OPERATOR");
    await requirePermission(session, "settings", "view");
    return ok(await listSettings());
  });
}

// PUT /api/settings -> 批量 upsert 设置；若含 email.provider 则即时切换发送通道
export async function PUT(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "MARKETING_OPERATOR");
    await requirePermission(session, "settings", "edit");
    const body = await req.json();
    const items: { key: string; value: string }[] = body.items ?? [];
    if (!Array.isArray(items)) throw new Error("items 必须是数组");

    await saveSettings(items);

    const providerItem = items.find((i) => i.key === "email.provider");
    if (providerItem) setEmailProviderMode(providerItem.value);

    // AI / Mautic 等也在保存后即时刷新运行时配置
    await refreshAiConfig();
    await refreshMauticConfig();

    return ok(await listSettings());
  });
}
