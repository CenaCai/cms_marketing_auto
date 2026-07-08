import { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { verifyPassword, signToken } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { unauthorized, badRequest } from "@/lib/errors";

export async function POST(req: NextRequest) {
  return handle(async () => {
    const body = await req.json().catch(() => ({}));
    const { email, password } = body ?? {};
    if (!email || !password) throw badRequest("email / password 必填");

    const user = await prisma.user.findUnique({ where: { email } });
    if (!user || !(await verifyPassword(password, user.passwordHash))) {
      throw unauthorized("邮箱或密码错误");
    }
    const member = await prisma.organizationMember.findFirst({
      where: { userId: user.id, status: "active" },
    });
    if (!member) throw unauthorized("该用户未加入任何组织");
    const token = signToken({
      userId: user.id,
      organizationId: member.organizationId,
      role: member.role,
    });
    return ok({ token, user: { id: user.id, name: user.name, email } });
  });
}
