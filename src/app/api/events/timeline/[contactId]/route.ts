import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { listEvents } from "@/services/event.service";

// 单个联系人的行为时间线（V2 用户行为监控）
export async function GET(
  req: NextRequest,
  { params }: { params: { contactId: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    const events = await listEvents(session.organizationId, {
      contactId: params.contactId,
      limit: 200,
    });
    return ok(events);
  });
}
