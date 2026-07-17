import { NextRequest } from "next/server";
import { getSession, requirePermission } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { badRequest } from "@/lib/errors";
import { prisma } from "@/lib/db";
import { checkSql, bindOrg } from "@/lib/sql-guard";

const ROW_LIMIT = 5000;

// 真实 SQL 精准圈人：在 organizationId 隔离范围内执行只读 SELECT。
export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "contacts", "view");

    const body = await req.json().catch(() => ({}));
    const sql = (body?.sql ?? "").trim();
    const check = checkSql(sql);
    if (!check.ok) throw badRequest(check.error!);

    const finalSql = bindOrg(sql, session.organizationId);
    const rows = (await prisma.$queryRawUnsafe(finalSql)) as Record<string, any>[];
    const truncated = rows.length > ROW_LIMIT;
    const limited = truncated ? rows.slice(0, ROW_LIMIT) : rows;
    const columns = limited.length ? Object.keys(limited[0]) : [];

    // 审计：任何圈人查询都留痕
    await prisma.systemLog
      .create({
        data: {
          organizationId: session.organizationId,
          type: "OPERATION",
          actorId: session.userId,
          action: "SQL_QUERY",
          target: sql.slice(0, 200),
        },
      })
      .catch(() => {});

    return ok({
      columns,
      rows: limited,
      total: rows.length,
      truncated,
      note: truncated ? `结果超过 ${ROW_LIMIT} 行，已截断展示前 ${ROW_LIMIT} 行` : undefined,
    });
  });
}
