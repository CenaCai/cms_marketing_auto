import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { updateTag, deleteTag } from "@/services/tag.service";

export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    await getSession(req);
    const body = await req.json();
    return ok(await updateTag(params.id, body));
  });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    await getSession(req);
    await deleteTag(params.id);
    return ok({ deleted: true });
  });
}
