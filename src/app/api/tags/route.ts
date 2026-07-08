import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { listTags, createTag } from "@/services/tag.service";

export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    return ok(await listTags(session.organizationId));
  });
}

export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    const body = await req.json();
    return ok(await createTag(session.organizationId, body), 201);
  });
}
