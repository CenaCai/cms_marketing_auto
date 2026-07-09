import { NextRequest } from "next/server";
import { getSession, requireRole } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { refreshMauticConfig } from "@/lib/mautic-config";
import { pullTagsAndSegmentsFromMautic, pushToMautic } from "@/services/mautic.service";

// 触发 Mautic 同步。
// mode=pull：Mautic 标签/分群 → 本系统
// mode=push（默认）：本系统联系人/标签/分群 → Mautic 执行层
export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "SUPER_ADMIN");
    await refreshMauticConfig();

    let mode = "push";
    try {
      const b = await req.json();
      if (b?.mode === "pull") mode = "pull";
    } catch {
      /* 默认 push */
    }

    const result =
      mode === "pull"
        ? await pullTagsAndSegmentsFromMautic(session.organizationId)
        : await pushToMautic(session.organizationId);

    return ok({ mode, result });
  });
}
