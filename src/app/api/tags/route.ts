import { NextRequest } from "next/server";
import { getSession, requirePermission } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { listTags, createTag } from "@/services/tag.service";

export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "tags", "view");
    return ok(await listTags(session.organizationId));
  });
}

export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "tags", "create");
    const body = await req.json();
    return ok(await createTag(session.organizationId, body), 201);
  });
}
