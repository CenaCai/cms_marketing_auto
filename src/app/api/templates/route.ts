import { NextRequest } from "next/server";
import { getSession, requirePermission } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import {
  listTemplates,
  createTemplate,
} from "@/services/template.service";
type TemplateType = string;

export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "templates", "view");
    const type = req.nextUrl.searchParams.get("type") as TemplateType | null;
    return ok(await listTemplates(session.organizationId, type ?? undefined));
  });
}

export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "templates", "create");
    const body = await req.json();
    return ok(await createTemplate(session.organizationId, body), 201);
  });
}
