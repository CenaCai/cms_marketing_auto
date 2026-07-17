import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { sweepInactivity } from "@/services/auto-tag.service";

// 手动触发「不活跃扫描」：给超过阈值未活跃的联系人打标（如 inactive_30d）
export async function POST(_req: NextRequest) {
  return handle(async () => {
    const session = await getSession(_req);
    const result = await sweepInactivity(session.organizationId);
    return ok(result);
  });
}
