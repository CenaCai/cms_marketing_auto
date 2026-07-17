import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { evaluateSegment } from "@/services/segment.service";

// 即时求值动态分群规则，并返回命中的联系人数量/列表
export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    const seg = await (await import("@/lib/db")).prisma.segment.findFirst({
      where: { organizationId: session.organizationId, id: params.id },
    });
    if (!seg || seg.type !== "dynamic" || !seg.rules) return ok({ ids: [], count: 0 });
    const ids = await evaluateSegment(session.organizationId, JSON.parse(seg.rules));
    return ok({ ids, count: ids.length });
  });
}
