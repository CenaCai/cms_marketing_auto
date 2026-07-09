import { NextRequest } from "next/server";
import { getSession, requirePermission } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { bulkAddTags } from "@/services/tag.service";

// 批量给一批联系人打多个标签
export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "tags", "create");
    const { contactIds, tagIds } = await req.json();
    if (!Array.isArray(contactIds) || !Array.isArray(tagIds) || contactIds.length === 0 || tagIds.length === 0) {
      throw new Error("contactIds 与 tagIds 均为必填数组");
    }
    await bulkAddTags(contactIds, tagIds);
    return ok({ ok: true, count: contactIds.length * tagIds.length });
  });
}
