import { prisma } from "@/lib/db";
import { hashPassword } from "@/lib/auth";
import type { PermissionMap } from "@/lib/permissions";

export interface CreateUserInput {
  name: string;
  username?: string;
  email: string;
  password: string;
  role?: string; // ORG_ADMIN | MARKETING_OPERATOR | VIEWER
  permissions?: PermissionMap; // module -> action -> bool
}

export async function listUsers(orgId: string) {
  return prisma.user.findMany({
    where: { memberships: { some: { organizationId: orgId } } },
    include: {
      memberships: { where: { organizationId: orgId }, select: { role: true, status: true } },
      userPermissions: { where: { organizationId: orgId } },
    },
    orderBy: { createdAt: "asc" },
  });
}

export async function createUser(orgId: string, input: CreateUserInput) {
  const passwordHash = await hashPassword(input.password);
  // 用户名若提供需唯一
  const user = await prisma.user.create({
    data: {
      name: input.name,
      username: input.username?.trim() || undefined,
      email: input.email.trim(),
      passwordHash,
    },
  });
  await prisma.organizationMember.create({
    data: {
      organizationId: orgId,
      userId: user.id,
      role: input.role ?? "MARKETING_OPERATOR",
      status: "active",
    },
  });
  await savePermissions(orgId, user.id, input.permissions ?? {});
  return user;
}

async function savePermissions(orgId: string, userId: string, perms: PermissionMap) {
  // 先清后写（仅保留 allowed=true 的条目，未勾选即拒绝）
  await prisma.userPermission.deleteMany({ where: { organizationId: orgId, userId } });
  const rows: { organizationId: string; userId: string; module: string; action: string; allowed: boolean }[] = [];
  for (const [module, actions] of Object.entries(perms)) {
    for (const [action, allowed] of Object.entries(actions)) {
      if (allowed) rows.push({ organizationId: orgId, userId, module, action, allowed: true });
    }
  }
  if (rows.length) await prisma.userPermission.createMany({ data: rows });
}

export async function updateUser(
  orgId: string,
  userId: string,
  input: { role?: string; status?: string; permissions?: PermissionMap },
) {
  if (input.role || input.status) {
    await prisma.organizationMember.updateMany({
      where: { organizationId: orgId, userId },
      data: { ...(input.role ? { role: input.role } : {}), ...(input.status ? { status: input.status } : {}) },
    });
  }
  if (input.permissions) await savePermissions(orgId, userId, input.permissions);
  return prisma.user.findUnique({ where: { id: userId } });
}

export async function deleteUser(orgId: string, userId: string) {
  // 仅移除在本组织的成员关系与权限；不删除 User 行本身以免误伤其他组织。
  await prisma.userPermission.deleteMany({ where: { organizationId: orgId, userId } });
  await prisma.organizationMember.deleteMany({ where: { organizationId: orgId, userId } });
  return { ok: true };
}
