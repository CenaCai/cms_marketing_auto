import { NextRequest } from "next/server";
import { getSession, requirePermission } from "@/lib/auth";
import { getSegmentMembers } from "@/services/segment.service";

// 导出某个分组（静态/动态）下的联系人列表为 CSV
export async function GET(req: NextRequest, { params }: { params: { id: string } }) {
  let session;
  try {
    session = await getSession(req);
    await requirePermission(session, "segments", "view");
  } catch (e: any) {
    return Response.json({ error: e?.message ?? "unauthorized" }, { status: 401 });
  }

  const members = await getSegmentMembers(session.organizationId, params.id);
  const header = ["name", "email", "phone", "country", "city", "status"];
  const rows = members.map((m) => [
    m.name ?? "",
    m.email ?? "",
    m.phone ?? "",
    m.country ?? "",
    m.city ?? "",
    m.status,
  ]);
  const escape = (v: string) => `"${String(v).replace(/"/g, '""')}"`;
  const csv = [header, ...rows].map((r) => r.map(escape).join(",")).join("\n");
  // 加 BOM 以便 Excel 正确识别 UTF-8
  return new Response("﻿" + csv, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="segment-${params.id}.csv"`,
    },
  });
}
