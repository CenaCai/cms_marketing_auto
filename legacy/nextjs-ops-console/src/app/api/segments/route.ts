import { NextRequest } from "next/server";
import { getSession, requirePermission } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import {
  listSegments,
  createSegment,
} from "@/services/segment.service";

export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "segments", "view");
    return ok(await listSegments(session.organizationId));
  });
}

export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "segments", "create");
    const body = await req.json();
    return ok(await createSegment(session.organizationId, body), 201);
  });
}
