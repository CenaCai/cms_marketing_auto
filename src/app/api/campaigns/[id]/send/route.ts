import { NextRequest } from "next/server";
import { getSession, requireRole } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { createBatchSend } from "@/services/send.service";
type Channel = string;

// 对 campaign 触发批量发送（EDM / SMS）
export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "MARKETING_OPERATOR");
    const body = await req.json().catch(() => ({}));
    const result = await createBatchSend(session.organizationId, {
      campaignId: params.id,
      segmentId: body.segmentId,
      contactIds: body.contactIds,
      channel: (body.channel ?? "EMAIL") as Channel,
      scheduleAt: body.scheduleAt,
    });
    return ok(result, 201);
  });
}
