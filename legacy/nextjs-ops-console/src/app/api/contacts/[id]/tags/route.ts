import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { addTagToContact, removeTagFromContact } from "@/services/tag.service";

// 给单个联系人打标签 / 移除标签
export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    await getSession(req);
    const { tagId } = await req.json();
    await addTagToContact(params.id, tagId);
    return ok({ ok: true });
  });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    await getSession(req);
    const sp = req.nextUrl.searchParams;
    await removeTagFromContact(params.id, sp.get("tagId")!);
    return ok({ ok: true });
  });
}
