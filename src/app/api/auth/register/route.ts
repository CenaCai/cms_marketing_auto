import { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { hashPassword, signToken } from "@/lib/auth";
import { handle, ok, fail } from "@/lib/response";
import { badRequest, conflict } from "@/lib/errors";

export async function POST(req: NextRequest) {
  return handle(async () => {
    const body = await req.json().catch(() => ({}));
    const { name, email, password, organizationName } = body ?? {};
    if (!name || !email || !password) {
      throw badRequest("name / email / password 必填");
    }
    const exist = await prisma.user.findUnique({ where: { email } });
    if (exist) throw conflict("邮箱已注册");

    const passwordHash = await hashPassword(password);
    const user = await prisma.user.create({
      data: { name, email, passwordHash },
    });
    // 注册时创建默认组织 + 成员关系（ORG_ADMIN）
    const org = await prisma.organization.create({
      data: {
        name: organizationName || `${name} 的组织`,
        members: {
          create: { userId: user.id, role: "ORG_ADMIN" },
        },
      },
    });
    const token = signToken({
      userId: user.id,
      organizationId: org.id,
      role: "ORG_ADMIN",
    });
    return ok({ token, user: { id: user.id, name, email }, organizationId: org.id });
  });
}
