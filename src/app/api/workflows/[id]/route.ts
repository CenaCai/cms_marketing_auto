import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { notFound } from "@/lib/errors";
import { workflowRepo } from "@/services/workflow.engine";
import type { WorkflowDefinition } from "@/services/workflow.engine";

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    const wf = await workflowRepo.get(session.organizationId, params.id);
    if (!wf) throw notFound();
    return ok(wf);
  });
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    const body = await req.json();
    return ok(
      await workflowRepo.update(session.organizationId, params.id, {
        name: body.name,
        description: body.description,
        definition: body.definition as WorkflowDefinition,
        enabled: body.enabled,
      }),
    );
  });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    await workflowRepo.remove(session.organizationId, params.id);
    return ok({ deleted: true });
  });
}
