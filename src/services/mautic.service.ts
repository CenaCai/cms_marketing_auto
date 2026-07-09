import { prisma } from "@/lib/db";
import { getMauticClient } from "@/integrations/mautic";

// =====================================================================
// Mautic 双向同步服务
// 方向 C（混合模式）：Next.js 是「数据资产层」（联系人/标签/分群/SQL 圈人），
// Mautic 是「执行层」（发信 / 落地页 / 可视化 Campaign）。
// 因此主同步方向是【本系统 → Mautic 推送】；同时支持【Mautic → 本系统】拉取标签/分群。
// =====================================================================

export interface PullResult {
  tagsCreated: number;
  segmentsCreated: number;
  skipped: string[];
}

export interface PushResult {
  contactsPushed: number;
  tagsEnsured: number;
  segmentsCreated: number;
  segmentMembersAdded: number;
  skipped: string[];
}

// Mautic → 本系统：拉取标签 / 分群（lead lists 映射为静态 Segment）
export async function pullTagsAndSegmentsFromMautic(orgId: string): Promise<PullResult> {
  const client = getMauticClient();
  const result: PullResult = { tagsCreated: 0, segmentsCreated: 0, skipped: [] };

  if (client.name === "mautic-mock") {
    result.skipped.push("Mautic 未启用或未配置，跳过同步（mock 模式）");
    return result;
  }

  const mauticTags = await client.getTags();
  for (const t of mauticTags) {
    if (!t.name) continue;
    await prisma.tag.upsert({
      where: { organizationId_name: { organizationId: orgId, name: t.name } },
      create: { organizationId: orgId, name: t.name, color: t.color ?? undefined },
      update: { color: t.color ?? undefined },
    });
    result.tagsCreated++;
  }

  const mauticSegments = await client.getSegments();
  for (const s of mauticSegments) {
    if (!s.name) continue;
    await prisma.segment.upsert({
      where: { organizationId_name: { organizationId: orgId, name: s.name } },
      create: { organizationId: orgId, name: s.name, type: "static", description: "来自 Mautic 同步" },
      update: { description: "来自 Mautic 同步" },
    });
    result.segmentsCreated++;
  }

  return result;
}

// 本系统 → Mautic：推送标签 / 联系人(带标签) / 静态分群(含成员)，作为执行层数据源
export async function pushToMautic(orgId: string): Promise<PushResult> {
  const client = getMauticClient();
  const result: PushResult = {
    contactsPushed: 0,
    tagsEnsured: 0,
    segmentsCreated: 0,
    segmentMembersAdded: 0,
    skipped: [],
  };

  if (client.name === "mautic-mock") {
    result.skipped.push("Mautic 未启用或未配置，跳过推送（mock 模式）");
    return result;
  }

  // 1) 确保标签存在（仅创建 Mautic 中缺失的，避免重名报错）
  const existingTags = new Set((await client.getTags()).map((t) => t.name));
  const localTags = await prisma.tag.findMany({ where: { organizationId: orgId } });
  for (const t of localTags) {
    if (!t.name) continue;
    if (!existingTags.has(t.name)) {
      await client.createTag(t.name, t.color ?? undefined);
    }
    result.tagsEnsured++;
  }

  // 2) 推送联系人（按 email upsert，并带标签）
  const contacts = await prisma.contact.findMany({
    where: { organizationId: orgId, email: { not: null } },
    include: { contactTags: { include: { tag: true } } },
  });
  for (const c of contacts) {
    const [first, ...rest] = (c.name ?? "").split(" ");
    const last = rest.join(" ");
    const tagNames = c.contactTags.map((ct) => ct.tag.name);
    const existing = await client.findContactByEmail(c.email!);
    if (existing) {
      await client.editContact(existing.id, { firstname: first, lastname: last, tags: tagNames });
    } else {
      await client.createContact({ email: c.email!, firstname: first, lastname: last, tags: tagNames });
    }
    result.contactsPushed++;
  }

  // 3) 推送静态分群 → Mautic lead list，并加入成员
  const segments = await prisma.segment.findMany({ where: { organizationId: orgId, type: "static" } });
  for (const s of segments) {
    const mSeg = await client.createSegment(s.name);
    const members = await prisma.contactSegment.findMany({
      where: { segmentId: s.id },
      include: { contact: true },
    });
    for (const m of members) {
      if (!m.contact.email) continue;
      let cid = (await client.findContactByEmail(m.contact.email))?.id;
      if (!cid) {
        cid = (await client.createContact({ email: m.contact.email })).id;
      }
      await client.addContactToSegment(cid, mSeg.id);
      result.segmentMembersAdded++;
    }
    result.segmentsCreated++;
  }

  return result;
}
