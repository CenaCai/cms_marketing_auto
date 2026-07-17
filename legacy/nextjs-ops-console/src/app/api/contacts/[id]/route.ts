import { NextRequest } from "next/server";
import { getSession, requirePermission } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { notFound } from "@/lib/errors";
import {
  getContact,
  updateContact,
  deleteContact,
} from "@/services/contact.service";

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "contacts", "view");
    const contact = await getContact(session.organizationId, params.id);
    if (!contact) throw notFound();
    return ok(contact);
  });
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "contacts", "edit");
    const body = await req.json().catch(() => ({}));
    const contact = await updateContact(session.organizationId, params.id, body);
    return ok(contact);
  });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "contacts", "delete");
    await deleteContact(session.organizationId, params.id);
    return ok({ deleted: true });
  });
}
