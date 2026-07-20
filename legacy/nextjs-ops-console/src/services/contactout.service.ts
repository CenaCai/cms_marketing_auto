import { prisma } from "@/lib/db";
import { getContactOutProvider, PROSPECT_TAG } from "@/integrations/contactout";
import { toContactFields } from "@/integrations/contactout/mapper";
import type { ContactOutSearchRequest } from "@/integrations/contactout/types";

// =====================================================================
// ContactOut 潜客导入服务
// 数据流：ContactOut API → 本系统「数据资产层」（Contact 表，source=contactout）
//        → 统一打「潜客」标签。Mautic 同步（已有的 /integrations/mautic/sync）
//        可在后续把这批联系人推送到 Mautic 执行层。
// 合规：导入仅写入数据资产层；正式触达前仍需合法基础（见 API route 的 compliance 提示）。
// =====================================================================

export interface ContactOutImportResult {
  requested: number;
  imported: number;
  skippedNoEmail: number;
  tagApplied: number;
  totalAvailable: number;
  skipped: string[];
  note: string;
}

function isValidEmail(e?: string | null): boolean {
  return typeof e === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e);
}

export async function importLeadsFromContactOut(
  orgId: string,
  req: ContactOutSearchRequest,
): Promise<ContactOutImportResult> {
  const provider = getContactOutProvider();
  const result: ContactOutImportResult = {
    requested: req.limit ?? 25,
    imported: 0,
    skippedNoEmail: 0,
    tagApplied: 0,
    totalAvailable: 0,
    skipped: [],
    note: "",
  };

  // mock / 未启用：不写库，仅回显样例，避免污染数据资产层
  if (provider.name === "contactout-mock") {
    const mockRes = await provider.search(req);
    result.totalAvailable = mockRes.totalResults;
    result.note =
      "ContactOut 未启用或未配置 API key，返回 mock 样例（未写入数据库）。" +
      ` mock 返回 ${mockRes.leads.length} 条样例。`;
    return result;
  }

  const searchRes = await provider.search(req);
  result.totalAvailable = searchRes.totalResults;

  // 确保「潜客」标签存在（复用 Mautic 推送时也会同步过去）
  const tag = await prisma.tag.upsert({
    where: { organizationId_name: { organizationId: orgId, name: PROSPECT_TAG } },
    create: {
      organizationId: orgId,
      name: PROSPECT_TAG,
      color: "#f59e0b",
      description: "来自 ContactOut 数据源的潜客",
    },
    update: { description: "来自 ContactOut 数据源的潜客" },
  });

  for (const lead of searchRes.leads) {
    if (!isValidEmail(lead.email)) {
      result.skippedNoEmail++;
      result.skipped.push(`跳过无邮箱线索: ${lead.linkedinUrl}`);
      continue;
    }
    try {
      const fields = toContactFields(lead, orgId);
      const contact = await prisma.contact.upsert({
        where: { organizationId_email: { organizationId: orgId, email: lead.email! } },
        create: fields,
        update: fields,
      });
      await prisma.contactTag.upsert({
        where: { contactId_tagId: { contactId: contact.id, tagId: tag.id } },
        create: { contactId: contact.id, tagId: tag.id },
        update: {},
      });
      result.imported++;
      result.tagApplied++;
    } catch (e) {
      result.skipped.push(`导入失败 ${lead.email}: ${(e as Error).message}`);
    }
  }

  result.note = `已从 ContactOut 导入 ${result.imported} 名潜客（共匹配 ${result.totalAvailable} 条）；无邮箱 ${result.skippedNoEmail} 条已跳过。`;
  return result;
}
