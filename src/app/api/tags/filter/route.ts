import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { filterByTags } from "@/services/contact.service";

// 复合标签筛选：mode = any(包含任一) / all(包含全部) / none(不包含指定)
export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    const { tagIds, mode } = await req.json();
    const ids = await filterByTags(session.organizationId, tagIds, mode);
    return ok({ contactIds: ids, count: ids.length });
  });
}
