import { NextRequest } from "next/server";
import { getSession, requireRole } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { listUsers, createUser } from "@/services/user.service";

// 列出本组织全部账号
export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "SUPER_ADMIN");
    return ok(await listUsers(session.organizationId));
  });
}

// 开通运营账号（含权限矩阵）
export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "SUPER_ADMIN");
    const body = await req.json();
    if (!body.email || !body.password || !body.name) {
      throw new Error("name / email / password 必填");
    }
    const user = await createUser(session.organizationId, {
      name: body.name,
      username: body.username,
      email: body.email,
      password: body.password,
      role: body.role,
      permissions: body.permissions ?? {},
    });
    return ok({ id: user.id, email: user.email, name: user.name }, 201);
  });
}
