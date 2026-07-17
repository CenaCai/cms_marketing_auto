import { NextRequest } from "next/server";
import { getSession, requirePermission } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { updateTag, deleteTag } from "@/services/tag.service";

export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "tags", "edit");
    const body = await req.json();
    return ok(await updateTag(session.organizationId, params.id, body));
  });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "tags", "delete");
    await deleteTag(session.organizationId, params.id);
    return ok({ deleted: true });
  });
}
