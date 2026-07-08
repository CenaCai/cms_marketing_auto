import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import {
  listTemplates,
  createTemplate,
} from "@/services/template.service";
import type { TemplateType } from "@prisma/client";

export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    const type = req.nextUrl.searchParams.get("type") as TemplateType | null;
    return ok(await listTemplates(session.organizationId, type ?? undefined));
  });
}

export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    const body = await req.json();
    return ok(await createTemplate(session.organizationId, body), 201);
  });
}
