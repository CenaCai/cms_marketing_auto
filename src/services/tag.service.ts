import { prisma } from "@/lib/db";

export async function listTags(orgId: string) {
  return prisma.tag.findMany({
    where: { organizationId: orgId },
    include: { _count: { select: { contactTags: true } } },
    orderBy: { name: "asc" },
  });
}

export async function createTag(
  orgId: string,
  data: { name: string; color?: string; description?: string },
) {
  return prisma.tag.create({ data: { organizationId: orgId, ...data } });
}

export async function updateTag(
  orgId: string,
  id: string,
  data: { name?: string; color?: string; description?: string },
) {
  return prisma.tag.update({ where: { id }, data });
}

export async function deleteTag(orgId: string, id: string) {
  return prisma.tag.deleteMany({ where: { organizationId: orgId, id } });
}

export async function addTagToContact(contactId: string, tagId: string) {
  return prisma.contactTag.upsert({
    where: { contactId_tagId: { contactId, tagId } },
    create: { contactId, tagId },
    update: {},
  });
}

export async function removeTagFromContact(contactId: string, tagId: string) {
  return prisma.contactTag.deleteMany({ where: { contactId, tagId } });
}

// 批量打标签：对同一批联系人写入多个 tag
export async function bulkAddTags(contactIds: string[], tagIds: string[]) {
  const ops = contactIds.flatMap((cid) =>
    tagIds.map((tid) =>
      prisma.contactTag.upsert({
        where: { contactId_tagId: { contactId: cid, tagId: tid } },
        create: { contactId: cid, tagId: tid },
        update: {},
      }),
    ),
  );
  return Promise.all(ops);
}
