import { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { handle, ok } from "@/lib/response";
import { badRequest } from "@/lib/errors";

// =====================================================================
// Mautic → 本系统 行为回流（闭环关键一环）
// 在 Mautic 后台配置 Webhook，指向：<本系统>/api/integrations/mautic/webhook?org=<组织ID>
// Mautic 打开/点击/退订事件将回写本系统 Event 中心，
// 进而驱动「行为→自动打标」与「SQL 精准圈人」。
// 兼容 Mautic 原生 webhook 结构 与 简单测试结构（{event,email,timestamp}）。
// =====================================================================

const EVENT_MAP: Record<string, string> = {
  "mautic.email_on_open": "email_opened",
  "mautic.email_on_click": "email_clicked",
  "mautic.email_on_unsubscribe": "email_unsubscribed",
  "mautic.email_on_send": "email_sent",
};

function extractEmail(item: any): string | null {
  if (!item) return null;
  const lead = item.lead ?? item.contact ?? {};
  return lead.email ?? lead.fields?.core?.email ?? item.email ?? null;
}

export async function POST(req: NextRequest) {
  return handle(async () => {
    const orgParam = req.nextUrl.searchParams.get("org");
    const org = orgParam
      ? await prisma.organization.findUnique({ where: { id: orgParam } })
      : await prisma.organization.findFirst();
    if (!org) throw badRequest("未知组织");

    let body: any;
    try {
      body = await req.json();
    } catch {
      throw badRequest("无效 JSON");
    }

    const events: { type: string; email: string | null; raw: any; ts?: number }[] = [];

    if (body && body.event && body.email) {
      // 简单测试结构
      events.push({ type: String(body.event), email: body.email, raw: body, ts: body.timestamp });
    } else {
      // Mautic 原生 webhook：键为触发器名，值为事件数组
      for (const key of Object.keys(body ?? {})) {
        let mapped = EVENT_MAP[key];
        if (!mapped && key.startsWith("mautic.email_on_")) {
          mapped = "email_" + key.slice("mautic.email_on_".length);
        }
        if (!mapped) continue;
        const arr = Array.isArray(body[key]) ? body[key] : [body[key]];
        for (const item of arr) {
          events.push({ type: mapped, email: extractEmail(item), raw: item, ts: item?.timestamp });
        }
      }
    }

    let created = 0;
    const errors: string[] = [];
    for (const ev of events) {
      if (!ev.email) {
        errors.push(`跳过无邮箱事件(${ev.type})`);
        continue;
      }
      const contact = await prisma.contact.findFirst({
        where: { organizationId: org.id, email: ev.email },
      });
      if (!contact) {
        errors.push(`未找到联系人: ${ev.email}`);
        continue;
      }
      const occurred = ev.ts ? new Date(ev.ts * 1000) : new Date();
      const dedupKey = `${org.id}:${contact.id}:${ev.type}:${ev.ts ?? occurred.toISOString()}`;
      await prisma.event.upsert({
        where: { dedupKey },
        create: {
          organizationId: org.id,
          contactId: contact.id,
          eventType: "CUSTOM",
          eventName: ev.type,
          source: "mautic",
          properties: JSON.stringify(ev.raw),
          occurredAt: occurred,
          dedupKey,
        },
        update: {},
      });
      created++;
    }

    return ok({ received: events.length, created, errors });
  });
}
