import { prisma } from "@/lib/db";

export interface SegmentCondition {
  field:
    | "country"
    | "city"
    | "status"
    | "language"
    | "tag"
    | "lastActiveWithinDays"
    | "hasPurchased";
  op: "eq" | "neq" | "in" | "gt" | "lt" | "gte" | "lte";
  value: unknown;
}

export interface SegmentRule {
  combinator: "AND" | "OR";
  conditions: SegmentCondition[];
}

export async function listSegments(orgId: string) {
  return prisma.segment.findMany({
    where: { organizationId: orgId },
    include: { _count: { select: { contactSegments: true } } },
    orderBy: { name: "asc" },
  });
}

export async function createSegment(
  orgId: string,
  data: { name: string; type?: "static" | "dynamic"; rules?: SegmentRule; description?: string },
) {
  return prisma.segment.create({
    data: {
      organizationId: orgId,
      name: data.name,
      type: data.type ?? "dynamic",
      rules: (data.rules ?? null) as any,
      description: data.description,
    },
  });
}

export async function updateSegment(
  orgId: string,
  id: string,
  data: { name?: string; type?: "static" | "dynamic"; rules?: SegmentRule; description?: string },
) {
  return prisma.segment.update({
    where: { id },
    data: {
      name: data.name,
      type: data.type,
      rules: data.rules as any,
      description: data.description,
    },
  });
}

export async function deleteSegment(orgId: string, id: string) {
  return prisma.segment.deleteMany({ where: { organizationId: orgId, id } });
}

// 静态分群：直接增删成员
export async function addContactsToSegment(segmentId: string, contactIds: string[]) {
  return Promise.all(
    contactIds.map((cid) =>
      prisma.contactSegment.upsert({
        where: { contactId_segmentId: { contactId: cid, segmentId } },
        create: { contactId: cid, segmentId },
        update: {},
      }),
    ),
  );
}

export async function removeContactsFromSegment(segmentId: string, contactIds: string[]) {
  return prisma.contactSegment.deleteMany({
    where: { segmentId, contactId: { in: contactIds } },
  });
}

function matchCondition(contact: any, cond: SegmentCondition): boolean {
  const v = cond.value;
  switch (cond.field) {
    case "country":
    case "city":
    case "status":
    case "language":
      return applyOp(contact[cond.field], cond.op, v);
    case "tag": {
      const tags = (contact.contactTags ?? []).map((t: any) => t.tagId);
      if (cond.op === "in") return (v as string[]).some((t) => tags.includes(t));
      return tags.includes(v as string);
    }
    case "lastActiveWithinDays": {
      if (!contact.lastActiveAt) return false;
      const days = (Date.now() - new Date(contact.lastActiveAt).getTime()) / 86400000;
      return applyOp(days, cond.op, v as number);
    }
    case "hasPurchased":
      return contact._purchased === true;
    default:
      return false;
  }
}

function applyOp(actual: unknown, op: string, expected: unknown): boolean {
  switch (op) {
    case "eq":
      return actual === expected;
    case "neq":
      return actual !== expected;
    case "in":
      return Array.isArray(expected) && (expected as unknown[]).includes(actual);
    case "gt":
      return Number(actual) > Number(expected);
    case "lt":
      return Number(actual) < Number(expected);
    case "gte":
      return Number(actual) >= Number(expected);
    case "lte":
      return Number(actual) <= Number(expected);
    default:
      return false;
  }
}

// 动态分群求值：根据 rules 返回命中的 contactId 列表。
// 事件类条件（hasPurchased）需要先预加载，这里做最小化实现。
export async function evaluateSegment(orgId: string, rule: SegmentRule): Promise<string[]> {
  const contacts = await prisma.contact.findMany({
    where: { organizationId: orgId },
    include: { contactTags: true },
  });
  // 预计算 hasPurchased
  const purchasedContactIds = new Set(
    (
      await prisma.event.findMany({
        where: { organizationId: orgId, eventType: "PURCHASE" },
        select: { contactId: true },
        distinct: ["contactId"],
      })
    )
      .map((e) => e.contactId)
      .filter(Boolean) as string[],
  );

  return contacts
    .filter((c) => {
      const enriched = { ...c, _purchased: purchasedContactIds.has(c.id) };
      const results = rule.conditions.map((cond) => matchCondition(enriched, cond));
      return rule.combinator === "AND"
        ? results.every(Boolean)
        : results.some(Boolean);
    })
    .map((c) => c.id);
}

// 取分群成员（静态读 contactSegments；动态则即时求值并同步）
export async function getSegmentMembers(orgId: string, segmentId: string) {
  const seg = await prisma.segment.findFirst({
    where: { organizationId: orgId, id: segmentId },
  });
  if (!seg) return [];
  if (seg.type === "dynamic" && seg.rules) {
    const ids = await evaluateSegment(orgId, seg.rules as SegmentRule);
    return prisma.contact.findMany({
      where: { organizationId: orgId, id: { in: ids } },
    });
  }
  return prisma.contact.findMany({
    where: { organizationId: orgId, contactSegments: { some: { segmentId } } },
  });
}
