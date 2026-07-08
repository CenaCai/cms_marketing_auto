import { NextRequest } from "next/server";
import { getSession, requireRole } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import {
  parseCsv,
  parseExcel,
  importContacts,
  type ContactFieldMap,
} from "@/services/import.service";
import { prisma } from "@/lib/db";

// 数据导入：CSV 文本 或 Excel(base64)。先解析 -> 字段映射 -> 去重导入 -> 记录 ImportJob
export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "MARKETING_OPERATOR");
    const body = await req.json();
    const map = (body.map ?? {}) as ContactFieldMap;
    const rows = await (async () => {
      if (body.format === "excel") {
        const buf = Buffer.from(body.base64, "base64");
        return parseExcel(buf, map);
      }
      return parseCsv(body.csvText ?? "", map);
    })();

    const result = await importContacts(session.organizationId, rows);
    const job = await prisma.importJob.create({
      data: {
        organizationId: session.organizationId,
        fileName: body.fileName ?? "upload",
        status: "completed",
        totalCount: result.total,
        successCount: result.success,
        failedCount: result.failed,
        duplicateCount: result.duplicate,
        report: { errors: result.errors } as any,
      },
    });
    return ok({ jobId: job.id, ...result }, 201);
  });
}
