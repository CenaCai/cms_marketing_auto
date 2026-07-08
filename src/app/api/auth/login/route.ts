import { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { verifyPassword, signToken } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { unauthorized, badRequest } from "@/lib/errors";

export async function POST(req: NextRequest) {
  return handle(async () => {
    const body = await req.json().catch(() => ({}));
    const { email, username, password } = body ?? {};
    if ((!email && !username) || !password) {
      throw badRequest("email / username / password 必填");
    }

    const user = email
      ? await prisma.user.findUnique({ where: { email } })
      : await prisma.user.findUnique({ where: { username: username as string } });
    if (!user || !(await verifyPassword(password, user.passwordHash))) {
      throw unauthorized("账号或密码错误");
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
