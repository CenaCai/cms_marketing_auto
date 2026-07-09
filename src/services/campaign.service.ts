import { prisma } from "@/lib/db";
import { checkSql, bindOrg } from "@/lib/sql-guard";
import { badRequest } from "@/lib/errors";
import { evaluateSegment } from "./segment.service";
type CampaignStatus = string;
type Channel = string;

const FREQ_LIMIT_PER_DAY = 5;

export async function listCampaigns(orgId: string) {
  return prisma.campaign.findMany({
    where: { organizationId: orgId },
    include: { segment: true, template: true, _count: { select: { sendTasks: true } } },
    orderBy: { createdAt: "desc" },
  });
}

export async function createCampaign(
  orgId: string,
  data: {
    name: string;
    objective?: string;
    segmentId?: string;
    channel: Channel;
    templateId?: string;
    scheduledAt?: string;
    activity?: string;
    country?: string;
    language?: string;
    channels?: string; // JSON 数组
    edmTemplateId?: string;
    smsTemplateId?: string;
    landingPageId?: string;
    landingUrl?: string;
    audienceType?: string;
    tagIds?: string; // JSON 数组
    sqlQuery?: string;
  },
) {
  const scheduled = !!data.scheduledAt;
  return prisma.campaign.create({
    data: {
      organizationId: orgId,
      name: data.name,
      objective: data.objective ?? null,
      segmentId: data.segmentId ?? null,
      channel: data.channel,
      templateId: data.templateId ?? null,
      scheduledAt: data.scheduledAt ? new Date(data.scheduledAt) : null,
      status: scheduled ? "scheduled" : "draft",
      activity: data.activity ?? null,
      country: data.country ?? null,
      language: data.language ?? null,
      channels: data.channels ?? null,
      edmTemplateId: data.edmTemplateId ?? null,
      smsTemplateId: data.smsTemplateId ?? null,
      landingPageId: data.landingPageId ?? null,
      landingUrl: data.landingUrl ?? null,
      audienceType: data.audienceType ?? null,
      tagIds: data.tagIds ?? null,
      sqlQuery: data.sqlQuery ?? null,
    },
  });
}

export async function getCampaign(orgId: string, id: string) {
  return prisma.campaign.findFirst({
    where: { organizationId: orgId, id },
    include: { segment: true, template: true, sendTasks: true },
  });
}

export async function updateCampaign(
  orgId: string,
  id: string,
  data: Record<string, unknown>,
) {
  const clean: Record<string, unknown> = { ...data, organizationId: orgId };
  if (typeof data.scheduledAt === "string") clean.scheduledAt = new Date(data.scheduledAt);
  return prisma.campaign.update({ where: { id }, data: clean });
}

export async function setCampaignStatus(
  orgId: string,
  id: string,
  status: CampaignStatus,
) {
  return prisma.campaign.update({
    where: { id },
    data: { status, ...(status === "sent" ? { sentAt: new Date() } : {}) },
  });
}

// 解析目标联系人 id 列表（分群 / 标签 / SQL 三种圈人方式）
async function resolveAudienceIds(
  orgId: string,
  input: { audienceType?: string; segmentId?: string; tagIds?: string; sqlQuery?: string },
): Promise<string[]> {
  if (input.audienceType === "segment" && input.segmentId) {
    const seg = await prisma.segment.findFirst({ where: { organizationId: orgId, id: input.segmentId } });
    if (!seg) return [];
    if (seg.type === "dynamic" && seg.rules) {
      return evaluateSegment(orgId, JSON.parse(seg.rules));
    }
    const members = await prisma.contactSegment.findMany({ where: { segmentId: input.segmentId }, select: { contactId: true } });
    return members.map((m) => m.contactId);
  }
  if (input.audienceType === "tags" && input.tagIds) {
    const ids = JSON.parse(input.tagIds) as string[];
    if (!ids.length) return [];
    const contacts = await prisma.contact.findMany({
      where: { organizationId: orgId, contactTags: { some: { tagId: { in: ids } } } },
      select: { id: true },
    });
    return contacts.map((c) => c.id);
  }
  if (input.audienceType === "sql" && input.sqlQuery) {
    const check = checkSql(input.sqlQuery);
    if (!check.ok) throw badRequest(check.error!);
    const rows = (await prisma.$queryRawUnsafe(bindOrg(input.sqlQuery, orgId))) as Record<string, any>[];
    return rows.map((r) => r.id).filter(Boolean).map(String);
  }
  return [];
}

export type AudienceEstimate = {
  total: number;
  reachable: number;
  unsubscribed: number;
  blacklisted: number; // 黑名单 + bounced
  freqLimited: number;
  finalCount: number;
};

// 发送前检查：基于渠道与圈人方式，估算各过滤环节的留存人数
export async function estimateAudience(
  orgId: string,
  input: { channel: Channel; audienceType?: string; segmentId?: string; tagIds?: string; sqlQuery?: string },
): Promise<AudienceEstimate> {
  const ids = await resolveAudienceIds(orgId, input);
  const total = ids.length;
  if (total === 0) {
    return { total: 0, reachable: 0, unsubscribed: 0, blacklisted: 0, freqLimited: 0, finalCount: 0 };
  }

  const targets = await prisma.contact.findMany({
    where: { organizationId: orgId, id: { in: ids } },
    select: { id: true, email: true, phone: true, status: true },
  });

  const reachableContacts = targets.filter((c) =>
    input.channel === "EMAIL" ? !!c.email : !!c.phone,
  );
  const reachable = reachableContacts.length;

  const unsubscribed = reachableContacts.filter((c) => c.status === "unsubscribed").length;
  const blacklisted = reachableContacts.filter(
    (c) => c.status === "blacklisted" || c.status === "bounced",
  ).length;
  const eligible = reachableContacts.filter(
    (c) => !["unsubscribed", "blacklisted", "bounced"].includes(c.status),
  );
  const eligibleIds = eligible.map((c) => c.id);

  let freqLimited = 0;
  if (eligibleIds.length) {
    const since = new Date(Date.now() - 24 * 3600 * 1000);
    const grouped = await prisma.sendLog.groupBy({
      by: ["contactId"],
      where: { contactId: { in: eligibleIds }, channel: input.channel, status: "success", sentAt: { gte: since } },
      _count: { _all: true },
    });
    freqLimited = grouped.filter((g) => g._count._all >= FREQ_LIMIT_PER_DAY).length;
  }

  const finalCount = Math.max(0, eligible.length - freqLimited);
  return { total, reachable, unsubscribed, blacklisted, freqLimited, finalCount };
}
