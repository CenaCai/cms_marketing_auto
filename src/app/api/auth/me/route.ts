import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { prisma } from "@/lib/db";

export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    const [user, org, memberships] = await Promise.all([
      prisma.user.findUnique({ where: { id: session.userId } }),
      prisma.organization.findUnique({ where: { id: session.organizationId } }),
      prisma.organizationMember.findMany({
        where: { userId: session.userId, status: "active" },
        include: { organization: true },
      }),
    ]);
    return ok({ session, user, organization: org, memberships });
  });
}
