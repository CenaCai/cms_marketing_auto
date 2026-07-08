import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { getChannelStats } from "@/services/analytics.service";
import type { Channel } from "@prisma/client";

// 渠道统计：?channel=EMAIL | SMS
export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    const channel = (req.nextUrl.searchParams.get("channel") as Channel) ?? "EMAIL";
    return ok(await getChannelStats(session.organizationId, channel));
  });
}
