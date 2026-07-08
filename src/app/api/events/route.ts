import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { ingestEvent, listEvents } from "@/services/event.service";
import type { EventType } from "@prisma/client";

// 事件写入（API / SDK 共用），写入后自动触发 Workflow
export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    const body = await req.json();
    const event = await ingestEvent(session.organizationId, {
      contactId: body.contactId,
      eventName: body.eventName,
      eventType: body.eventType as EventType,
      source: body.source ?? "api",
      properties: body.properties,
      occurredAt: body.occurredAt,
    });
    return ok(event, 201);
  });
}

export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    const sp = req.nextUrl.searchParams;
    const events = await listEvents(session.organizationId, {
      contactId: sp.get("contactId") || undefined,
      eventType: (sp.get("eventType") as EventType) || undefined,
      limit: sp.get("limit") ? Number(sp.get("limit")) : 100,
    });
    return ok(events);
  });
}
