import { NextRequest } from "next/server";
import { getSession, requirePermission } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import {
  listContacts,
  createContact,
} from "@/services/contact.service";
type ContactStatus = string;

export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "contacts", "view");
    const sp = req.nextUrl.searchParams;
    const data = await listContacts(session.organizationId, {
      status: (sp.get("status") as ContactStatus) || undefined,
      search: sp.get("search") || undefined,
      tagIds: sp.get("tagIds")?.split(",").filter(Boolean),
      notTagIds: sp.get("notTagIds")?.split(",").filter(Boolean),
      limit: sp.get("limit") ? Number(sp.get("limit")) : 50,
      offset: sp.get("offset") ? Number(sp.get("offset")) : 0,
    });
    return ok(data);
  });
}

export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "contacts", "create");
    const body = await req.json().catch(() => ({}));
    const contact = await createContact(session.organizationId, body);
    return ok(contact, 201);
  });
}
