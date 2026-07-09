import { NextRequest } from "next/server";
import { getSession, requireRole } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { refreshMauticConfig } from "@/lib/mautic-config";
import { pullTagsAndSegmentsFromMautic } from "@/services/mautic.service";

// 触发从 Mautic 同步标签 / 分群到本系统
export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "SUPER_ADMIN");
    await refreshMauticConfig();
    const result = await pullTagsAndSegmentsFromMautic(session.organizationId);
    return ok(result);
  });
}
