import { prisma } from "@/lib/db";
import type { ContactStatus } from "@prisma/client";

export interface ContactFilter {
  status?: ContactStatus;
  search?: string; // 匹配 name/email/phone
  tagIds?: string[]; // 需同时拥有（用于复合筛选的"全部"语义）
  notTagIds?: string[]; // 排除这些 tag
  limit?: number;
  offset?: number;
}

export async function listContacts(orgId: string, f: ContactFilter = {}) {
  const where: any = { organizationId: orgId };
  if (f.status) where.status = f.status;
  if (f.search) {
    where.OR = [
      { name: { contains: f.search, mode: "insensitive" } },
      { email: { contains: f.search, mode: "insensitive" } },
      { phone: { contains: f.search, mode: "insensitive" } },
    ];
  }
  if (f.tagIds?.length) {
    where.contactTags = { some: { tagId: { in: f.tagIds } } };
  }
  if (f.notTagIds?.length) {
    where.NOT = { contactTags: { some: { tagId: { in: f.notTagIds } } } };
  }
  const [items, total] = await Promise.all([
    prisma.contact.findMany({
      where,
      include: { contactTags: { include: { tag: true } } },
      orderBy: { createdAt: "desc" },
      take: f.limit ?? 50,
      skip: f.offset ?? 0,
    }),
    prisma.contact.count({ where }),
  ]);
  return { items, total };
}

export async function getContact(orgId: string, id: string) {
  return prisma.contact.findFirst({
    where: { organizationId: orgId, id },
    include: {
      contactTags: { include: { tag: true } },
      contactSegments: { include: { segment: true } },
      channels: true,
      customValues: { include: { field: true } },
      events: { orderBy: { occurredAt: "desc" }, take: 50 },
    },
  });
}

export async function createContact(
  orgId: string,
  data: {
    name?: string;
    email?: string;
    phone?: string;
    country?: string;
    city?: string;
    language?: string;
    source?: string;
  },
) {
  // 去重：邮箱或手机号已存在则更新，否则新建
  const existing = await prisma.contact.findFirst({
    where: {
      organizationId: orgId,
      OR: [
        data.email ? { email: data.email } : { id: "__none__" },
        data.phone ? { phone: data.phone } : { id: "__none__" },
      ],
    },
  });
  if (existing) {
    return prisma.contact.update({ where: { id: existing.id }, data });
  }
  return prisma.contact.create({ data: { organizationId: orgId, ...data } });
}

export async function updateContact(
  orgId: string,
  id: string,
  data: Record<string, unknown>,
) {
  return prisma.contact.update({ where: { id }, data: { ...data, organizationId: orgId } });
}

export async function deleteContact(orgId: string, id: string) {
  return prisma.contact.deleteMany({ where: { organizationId: orgId, id } });
}

// 复合标签筛选：any=包含任一, all=包含全部, none=不包含指定
export async function filterByTags(
  orgId: string,
  tagIds: string[],
  mode: "any" | "all" | "none",
) {
  const contacts = await prisma.contact.findMany({
    where: { organizationId: orgId },
    select: { id: true, contactTags: { select: { tagId: true } } },
  });
  return contacts
    .filter((c) => {
      const ids = c.contactTags.map((t) => t.tagId);
      if (mode === "any") return ids.some((t) => tagIds.includes(t));
      if (mode === "all") return tagIds.every((t) => ids.includes(t));
      if (mode === "none") return !ids.some((t) => tagIds.includes(t));
      return false;
    })
    .map((c) => c.id);
}
