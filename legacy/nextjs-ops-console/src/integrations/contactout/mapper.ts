import type { NormalizedLead } from "./types";

// 线索落库时统一打上的标签
export const PROSPECT_TAG = "潜客";

// 将归一化线索映射为本系统 Contact 字段（用于 prisma upsert）。
// 注意：Contact 模型已新增 company 列；country/location → country/city。
export function toContactFields(lead: NormalizedLead, orgId: string) {
  return {
    organizationId: orgId,
    name: lead.fullName ?? undefined,
    email: lead.email,
    phone: lead.phone ?? undefined,
    company: lead.companyName ?? undefined,
    country: lead.country ?? undefined,
    city: lead.location ?? undefined,
    source: "contactout",
    status: "active" as const,
  };
}
