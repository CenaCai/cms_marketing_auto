import { prisma } from "@/lib/db";
import { addTagToContact } from "./tag.service";

export interface AutoTagRuleInput {
  name: string;
  description?: string;
  trigger: "EVENT" | "INACTIVITY";
  eventType?: string;
  matchMode?: "always" | "count";
  threshold?: number;
  windowDays?: number | null;
  propMatch?: { field: string; contains: string } | null;
  tagTemplate: string;
  inactiveDays?: number | null;
  enabled?: boolean;
}

// 4 个默认规则（首次访问自动播种，幂等）
export const DEFAULT_RULES: AutoTagRuleInput[] = [
  {
    name: "高意向 F1（浏览 F1 页面 2 次）",
    description: "当用户浏览 F1 页面累计 2 次，自动打标 high_intent_f1",
    trigger: "EVENT",
    eventType: "BROWSE",
    matchMode: "count",
    threshold: 2,
    windowDays: 30,
    propMatch: { field: "page", contains: "f1" },
    tagTemplate: "high_intent_f1",
  },
  {
    name: "EDM 互动（点击邮件）",
    description: "当用户点击 EDM 链接，自动打标 email_engaged",
    trigger: "EVENT",
    eventType: "CLICK_LINK",
    matchMode: "always",
    tagTemplate: "email_engaged",
  },
  {
    name: "已购买（purchased_{product}）",
    description: "当用户发生购买，自动打标 purchased_<产品>，产品取 properties.product",
    trigger: "EVENT",
    eventType: "PURCHASE",
    matchMode: "always",
    tagTemplate: "purchased_{product}",
  },
  {
    name: "30 天未活跃",
    description: "当用户超过 30 天未活跃，自动打标 inactive_30d（定时扫描）",
    trigger: "INACTIVITY",
    inactiveDays: 30,
    tagTemplate: "inactive_30d",
  },
];

export type AutoTagRule = {
  id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  trigger: string;
  eventType: string | null;
  matchMode: string;
  threshold: number;
  windowDays: number | null;
  propMatch: string | null;
  tagTemplate: string;
  inactiveDays: number | null;
  matched: number;
};

async function ensureTag(orgId: string, name: string) {
  const existing = await prisma.tag.findFirst({ where: { organizationId: orgId, name } });
  if (existing) return existing;
  return prisma.tag.create({ data: { organizationId: orgId, name, color: "#f59e0b" } });
}

function renderTagTemplate(template: string, properties: Record<string, any>): string {
  return template.replace(/\{(\w+)\}/g, (_, key) => {
    const v = properties?.[key];
    return v == null ? "unknown" : String(v);
  });
}

function propMatches(properties: Record<string, any>, propMatch?: string | null): boolean {
  if (!propMatch) return true;
  try {
    const pm = JSON.parse(propMatch);
    const val = properties?.[pm.field];
    if (val == null) return false;
    return String(val).toLowerCase().includes(String(pm.contains).toLowerCase());
  } catch {
    return false;
  }
}

// 统计该联系人在窗口内、命中属性过滤的同类型事件数
async function countMatchingEvents(
  orgId: string,
  contactId: string,
  eventType: string,
  propMatch?: string | null,
  windowDays?: number | null,
): Promise<number> {
  const since = windowDays ? new Date(Date.now() - windowDays * 86400000) : new Date(0);
  const events = await prisma.event.findMany({
    where: { organizationId: orgId, contactId, eventType, occurredAt: { gte: since } },
    select: { properties: true },
  });
  if (!propMatch) return events.length;
  return events.filter((e) => {
    try {
      const props = e.properties ? JSON.parse(e.properties) : {};
      return propMatches(props, propMatch);
    } catch {
      return false;
    }
  }).length;
}

// 计算规则已打标人数（兼容带变量的模板，如 purchased_{product}）
export async function ruleMatchedCount(orgId: string, rule: { tagTemplate: string }): Promise<number> {
  const tpl = rule.tagTemplate;
  const m = tpl.match(/^(.*?)\{(\w+)\}(.*)$/);
  if (!m) {
    const tag = await prisma.tag.findFirst({ where: { organizationId: orgId, name: tpl } });
    if (!tag) return 0;
    return prisma.contactTag.count({ where: { tagId: tag.id } });
  }
  const tags = await prisma.tag.findMany({
    where: { organizationId: orgId, name: { startsWith: m[1], endsWith: m[3] } },
  });
  if (tags.length === 0) return 0;
  return prisma.contactTag.count({ where: { tagId: { in: tags.map((t) => t.id) } } });
}

export async function listAutoTagRules(orgId: string): Promise<AutoTagRule[]> {
  const existing = await prisma.autoTagRule.findMany({
    where: { organizationId: orgId },
    orderBy: { createdAt: "asc" },
  });
  let rules = existing;
  if (rules.length === 0) {
    await seedDefaultRules(orgId);
    rules = await prisma.autoTagRule.findMany({
      where: { organizationId: orgId },
      orderBy: { createdAt: "asc" },
    });
  }
  const withMatched = await Promise.all(
    rules.map(async (r) => ({ ...r, matched: await ruleMatchedCount(orgId, r) }) as AutoTagRule),
  );
  return withMatched;
}

export async function seedDefaultRules(orgId: string) {
  for (const r of DEFAULT_RULES) {
    const exists = await prisma.autoTagRule.findFirst({ where: { organizationId: orgId, name: r.name } });
    if (exists) continue;
    await createAutoTagRule(orgId, r);
  }
}

export async function createAutoTagRule(orgId: string, data: AutoTagRuleInput) {
  return prisma.autoTagRule.create({
    data: {
      organizationId: orgId,
      name: data.name,
      description: data.description,
      enabled: data.enabled ?? true,
      trigger: data.trigger,
      eventType: data.eventType ?? null,
      matchMode: data.matchMode ?? "always",
      threshold: data.threshold ?? 1,
      windowDays: data.windowDays ?? null,
      propMatch: data.propMatch ? JSON.stringify(data.propMatch) : null,
      tagTemplate: data.tagTemplate,
      inactiveDays: data.inactiveDays ?? null,
    },
  });
}

export async function updateAutoTagRule(orgId: string, id: string, data: Partial<AutoTagRuleInput>) {
  const existing = await prisma.autoTagRule.findFirst({ where: { organizationId: orgId, id } });
  if (!existing) throw new Error("规则不存在");
  return prisma.autoTagRule.update({
    where: { id },
    data: {
      ...(data.name !== undefined ? { name: data.name } : {}),
      ...(data.description !== undefined ? { description: data.description } : {}),
      ...(data.enabled !== undefined ? { enabled: data.enabled } : {}),
      ...(data.trigger !== undefined ? { trigger: data.trigger } : {}),
      ...(data.eventType !== undefined ? { eventType: data.eventType } : {}),
      ...(data.matchMode !== undefined ? { matchMode: data.matchMode } : {}),
      ...(data.threshold !== undefined ? { threshold: data.threshold } : {}),
      ...(data.windowDays !== undefined ? { windowDays: data.windowDays } : {}),
      ...(data.propMatch !== undefined ? { propMatch: data.propMatch ? JSON.stringify(data.propMatch) : null } : {}),
      ...(data.tagTemplate !== undefined ? { tagTemplate: data.tagTemplate } : {}),
      ...(data.inactiveDays !== undefined ? { inactiveDays: data.inactiveDays } : {}),
    },
  });
}

export async function deleteAutoTagRule(orgId: string, id: string) {
  return prisma.autoTagRule.deleteMany({ where: { organizationId: orgId, id } });
}

// 事件写入后调用：匹配并应用 EVENT 类规则
export async function evaluateOnEvent(
  orgId: string,
  ctx: { contactId?: string; eventType: string; eventName: string; properties: Record<string, any> },
) {
  if (!ctx.contactId) return;
  const rules = await prisma.autoTagRule.findMany({
    where: { organizationId: orgId, enabled: true, trigger: "EVENT", eventType: ctx.eventType },
  });
  for (const rule of rules) {
    const props = ctx.properties ?? {};
    if (!propMatches(props, rule.propMatch)) continue;
    let shouldTag = false;
    if (rule.matchMode === "count") {
      const count = await countMatchingEvents(orgId, ctx.contactId, rule.eventType!, rule.propMatch, rule.windowDays);
      shouldTag = count >= rule.threshold;
    } else {
      shouldTag = true;
    }
    if (shouldTag) {
      const tagName = renderTagTemplate(rule.tagTemplate, props);
      const tag = await ensureTag(orgId, tagName);
      await addTagToContact(ctx.contactId, tag.id);
    }
  }
}

// 不活跃扫描：匹配并应用 INACTIVITY 类规则（可由定时任务/手动触发）
export async function sweepInactivity(orgId: string) {
  const rules = await prisma.autoTagRule.findMany({
    where: { organizationId: orgId, enabled: true, trigger: "INACTIVITY" },
  });
  let totalTagged = 0;
  for (const rule of rules) {
    const days = rule.inactiveDays ?? 30;
    const cutoff = new Date(Date.now() - days * 86400000);
    const tagName = renderTagTemplate(rule.tagTemplate, {});
    const tag = await ensureTag(orgId, tagName);
    const contacts = await prisma.contact.findMany({
      where: {
        organizationId: orgId,
        NOT: { contactTags: { some: { tagId: tag.id } } },
        OR: [{ lastActiveAt: { lt: cutoff } }, { lastActiveAt: null, createdAt: { lt: cutoff } }],
      },
      select: { id: true },
    });
    for (const c of contacts) {
      await addTagToContact(c.id, tag.id);
      totalTagged++;
    }
  }
  return { tagged: totalTagged };
}
