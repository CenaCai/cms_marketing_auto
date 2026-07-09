import bcrypt from "bcryptjs";
import jwt, { type SignOptions } from "jsonwebtoken";
import { NextRequest } from "next/server";
import { env } from "./env";
import { prisma } from "./db";
import { unauthorized, forbidden } from "./errors";
// SQLite 模式下枚举用普通字符串表示；保留类型别名以保持业务代码不变。
type MemberRole = string;

// --------------------------- Passwords -------------------------------

export async function hashPassword(plain: string): Promise<string> {
  return bcrypt.hash(plain, 10);
}

export async function verifyPassword(
  plain: string,
  hash: string,
): Promise<boolean> {
  return bcrypt.compare(plain, hash);
}

// ----------------------------- JWT -----------------------------------

export interface TokenPayload {
  userId: string;
  organizationId: string;
  role: MemberRole;
}

export function signToken(payload: TokenPayload): string {
  return jwt.sign(payload, env.jwtSecret, {
    expiresIn: env.jwtExpiresIn as SignOptions["expiresIn"],
  });
}

export function verifyToken(token: string): TokenPayload {
  return jwt.verify(token, env.jwtSecret) as TokenPayload;
}

// --------------------- Session / RBAC --------------------------------

export interface Session {
  userId: string;
  organizationId: string;
  role: MemberRole;
}

const ROLE_RANK: Record<MemberRole, number> = {
  VIEWER: 0,
  MARKETING_OPERATOR: 1,
  ORG_ADMIN: 2,
  SUPER_ADMIN: 3,
};

// 解析请求中的 Bearer token，并加载当前组织与角色。
export async function getSession(req: NextRequest): Promise<Session> {
  const header = req.headers.get("authorization") ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  if (!token) throw unauthorized();

  let payload: TokenPayload;
  try {
    payload = verifyToken(token);
  } catch {
    throw unauthorized("token 无效或已过期");
  }

  const member = await prisma.organizationMember.findUnique({
    where: {
      organizationId_userId: {
        organizationId: payload.organizationId,
        userId: payload.userId,
      },
    },
  });
  if (!member || member.status !== "active") {
    throw forbidden("该组织成员不可用");
  }
  return {
    userId: payload.userId,
    organizationId: payload.organizationId,
    role: member.role,
  };
}

// 角色门禁：要求至少达到给定角色。Super Admin 始终放行。
export function requireRole(session: Session, min: MemberRole): void {
  if (session.role === "SUPER_ADMIN") return;
  if (ROLE_RANK[session.role] < ROLE_RANK[min]) {
    throw forbidden(`需要 ${min} 及以上权限`);
  }
}

// --------------------- 细粒度权限（模块 × 增删改查） ---------------------
// SUPER_ADMIN 始终放行；其余按 UserPermission 表中该用户在该模块该操作的记录判断。
export type CrudAction = "view" | "create" | "edit" | "delete";

export async function requirePermission(
  session: Session,
  module: string,
  action: CrudAction,
): Promise<void> {
  if (session.role === "SUPER_ADMIN") return; // 全权
  const perm = await prisma.userPermission.findFirst({
    where: {
      organizationId: session.organizationId,
      userId: session.userId,
      module,
      action,
      allowed: true,
    },
  });
  if (!perm) throw forbidden(`无「${module}:${action}」权限，请联系管理员开通`);
}

// 读取某用户的完整权限矩阵（用于前端渲染勾选框 / 页面可见性判断）。
export async function getPermissions(
  orgId: string,
  userId: string,
): Promise<Record<string, Record<string, boolean>>> {
  const rows = await prisma.userPermission.findMany({
    where: { organizationId: orgId, userId, allowed: true },
  });
  const map: Record<string, Record<string, boolean>> = {};
  for (const r of rows) {
    map[r.module] = map[r.module] ?? {};
    map[r.module][r.action] = true;
  }
  return map;
}

// 从 URL 解析组织隔离参数（多数接口强制 organizationId = session.organizationId）
export function orgScoped(session: Session): { organizationId: string } {
  return { organizationId: session.organizationId };
}
