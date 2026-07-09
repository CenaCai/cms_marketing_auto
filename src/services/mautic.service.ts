import { prisma } from "@/lib/db";
import { getMauticClient } from "@/integrations/mautic";

// 将 Mautic 的标签 / 分群（lead lists）同步到本系统（设计对齐：
// Mautic Tag→Tag，Mautic Segment→Segment(type=static)）。
// 反向同步（本系统 → Mautic）可按需扩展，接口已预留。
export interface SyncResult {
  tagsCreated: number;
  segmentsCreated: number;
  skipped: string[];
}

export async function pullTagsAndSegmentsFromMautic(orgId: string): Promise<SyncResult> {
  const client = getMauticClient();
  const result: SyncResult = { tagsCreated: 0, segmentsCreated: 0, skipped: [] };

  if (client.name === "mautic-mock") {
    result.skipped.push("Mautic 未启用或未配置，跳过同步（mock 模式）");
    return result;
  }

  // 标签
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

  // 分群（映射为静态 Segment）
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
