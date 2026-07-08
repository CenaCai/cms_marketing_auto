import { prisma } from "@/lib/db";
import type { EventType } from "@prisma/client";
import { processWorkflowTriggers } from "./workflow.engine";

export interface IngestEventInput {
  contactId?: string;
  eventName: string;
  eventType?: EventType;
  source?: string;
  properties?: Record<string, unknown>;
  occurredAt?: string;
}

// 事件写入入口：API / Webhook / SDK 共用。写入后触发 Workflow 评估。
export async function ingestEvent(orgId: string, input: IngestEventInput) {
  // 去重键：避免重复事件（同一 contact + 事件 + 来源 + 1 分钟内）
  const occurred = input.occurredAt ? new Date(input.occurredAt) : new Date();
  const dedupKey = input.contactId
    ? `${orgId}:${input.contactId}:${input.eventName}:${Math.floor(occurred.getTime() / 60000)}`
    : undefined;

  const event = await prisma.event.create({
    data: {
      organizationId: orgId,
      contactId: input.contactId,
      eventName: input.eventName,
      eventType: input.eventType ?? "CUSTOM",
      source: input.source ?? "api",
      properties: (input.properties ?? null) as any,
      occurredAt: occurred,
      dedupKey,
    },
  });

  // 更新联系人最近活跃时间
  if (input.contactId) {
    await prisma.contact.updateMany({
      where: { id: input.contactId },
      data: { lastActiveAt: new Date() },
    });
  }

  // 触发自动化 Workflow（fire-and-forget，失败不影响事件落库）
  try {
    await processWorkflowTriggers(orgId, {
      contactId: input.contactId,
      eventName: input.eventName,
      eventType: event.eventType,
      properties: input.properties ?? {},
    });
  } catch (e) {
    console.error("[event:workflow] trigger failed", e);
  }

  return event;
}

export async function listEvents(
  orgId: string,
  opts: { contactId?: string; eventType?: EventType; limit?: number } = {},
) {
  return prisma.event.findMany({
    where: {
      organizationId: orgId,
      ...(opts.contactId ? { contactId: opts.contactId } : {}),
      ...(opts.eventType ? { eventType: opts.eventType } : {}),
    },
    orderBy: { occurredAt: "desc" },
    take: opts.limit ?? 100,
  });
}
