import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import {
  updateSegment,
  deleteSegment,
} from "@/services/segment.service";

export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    const body = await req.json();
    return ok(await updateSegment(session.organizationId, params.id, body));
  });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    await deleteSegment(session.organizationId, params.id);
    return ok({ deleted: true });
  });
}
