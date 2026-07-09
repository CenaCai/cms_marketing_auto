import { NextRequest } from "next/server";
import { getSession, requireRole } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { updateUser, deleteUser } from "@/services/user.service";

// 更新账号（角色 / 状态 / 权限矩阵）
export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "SUPER_ADMIN");
    const body = await req.json();
    await updateUser(session.organizationId, params.id, {
      role: body.role,
      status: body.status,
      permissions: body.permissions,
    });
    return ok({ ok: true });
  });
}

// 删除账号（移除本组织成员关系与权限）
export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "SUPER_ADMIN");
    if (params.id === session.userId) throw new Error("不能删除当前登录账号");
    await deleteUser(session.organizationId, params.id);
    return ok({ deleted: true });
  });
}
