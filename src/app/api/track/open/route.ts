import { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { ingestEvent } from "@/services/event.service";
import { ok } from "@/lib/response";

// EDM 打开追踪像素：1x1 透明 gif，并记录 email_opened 事件
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const logId = sp.get("logId");
  if (logId) {
    const log = await prisma.sendLog.findUnique({ where: { id: logId } });
    if (log) {
      await ingestEvent(log.organizationId, {
        contactId: log.contactId ?? undefined,
        eventName: "email_opened",
        eventType: "CUSTOM",
        source: "track_pixel",
        properties: { logId, channel: log.channel },
      }).catch(() => {});
    }
  }
  // 透明 1x1 gif
  const pixel = Buffer.from(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
    "base64",
  );
  return new Response(pixel, {
    status: 200,
    headers: { "content-type": "image/gif", "cache-control": "no-store" },
  });
}
