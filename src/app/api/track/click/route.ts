import { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { ingestEvent } from "@/services/event.service";
import { ok } from "@/lib/response";

// 链接点击追踪：记录 link_clicked 事件后 302 跳转真实落地页
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const logId = sp.get("logId");
  const url = sp.get("url") || "/";
  if (logId) {
    const log = await prisma.sendLog.findUnique({ where: { id: logId } });
    if (log) {
      await ingestEvent(log.organizationId, {
        contactId: log.contactId ?? undefined,
        eventName: "link_clicked",
        eventType: "CUSTOM",
        source: "track_click",
        properties: { logId, url, channel: log.channel },
      }).catch(() => {});
    }
  }
  return Response.redirect(url, 302);
}
