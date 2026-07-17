import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { notFound } from "@/lib/errors";
import {
  updateAutoTagRule,
  deleteAutoTagRule,
  type AutoTagRuleInput,
} from "@/services/auto-tag.service";

export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    const existing = await updateAutoTagRule(session.organizationId, params.id, (await req.json()) as Partial<AutoTagRuleInput>);
    if (!existing) throw notFound("规则不存在");
    return ok(existing);
  });
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(_req);
    await deleteAutoTagRule(session.organizationId, params.id);
    return ok({ ok: true });
  });
}
