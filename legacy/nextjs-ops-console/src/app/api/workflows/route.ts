import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { workflowRepo } from "@/services/workflow.engine";
import type { WorkflowDefinition } from "@/services/workflow.engine";

export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    return ok(await workflowRepo.list(session.organizationId));
  });
}

export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    const body = await req.json();
    return ok(
      await workflowRepo.create(session.organizationId, {
        name: body.name,
        description: body.description,
        definition: body.definition as WorkflowDefinition,
        enabled: body.enabled,
      }),
      201,
    );
  });
}
