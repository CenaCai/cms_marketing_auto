import { NextRequest } from "next/server";
import { getSession, requirePermission } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import {
  getSegmentMembers,
  addContactsToSegment,
  removeContactsFromSegment,
} from "@/services/segment.service";

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "segments", "view");
    return ok(await getSegmentMembers(session.organizationId, params.id));
  });
}

// 静态分群增删成员
export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "segments", "edit");
    const { contactIds } = await req.json();
    await addContactsToSegment(params.id, contactIds);
    return ok({ ok: true });
  });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "segments", "edit");
    const { contactIds } = await req.json();
    await removeContactsFromSegment(params.id, contactIds);
    return ok({ ok: true });
  });
}
