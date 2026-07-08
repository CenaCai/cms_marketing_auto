import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { updateTemplate } from "@/services/template.service";

export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    const body = await req.json();
    return ok(await updateTemplate(session.organizationId, params.id, body));
  });
}
