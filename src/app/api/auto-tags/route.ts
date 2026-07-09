import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import {
  listAutoTagRules,
  createAutoTagRule,
  type AutoTagRuleInput,
} from "@/services/auto-tag.service";

export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    const rules = await listAutoTagRules(session.organizationId);
    return ok(rules);
  });
}

export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    const body = (await req.json()) as AutoTagRuleInput;
    if (!body.name || !body.trigger || !body.tagTemplate) {
      throw new Error("name / trigger / tagTemplate 必填");
    }
    const rule = await createAutoTagRule(session.organizationId, body);
    return ok(rule, 201);
  });
}
