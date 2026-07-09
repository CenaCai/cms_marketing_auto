import { NextRequest } from "next/server";
import { getSession, requirePermission } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { estimateAudience } from "@/services/campaign.service";

// 发送前检查：基于渠道 + 圈人方式估算人群与过滤留存
export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "campaigns", "view");
    const body = await req.json().catch(() => ({}));
    const channel = (body?.channel ?? "EMAIL") as string;
    const result = await estimateAudience(session.organizationId, {
      channel,
      audienceType: body?.audienceType,
      segmentId: body?.segmentId,
      tagIds: body?.tagIds,
      sqlQuery: body?.sqlQuery,
    });
    return ok(result);
  });
}
