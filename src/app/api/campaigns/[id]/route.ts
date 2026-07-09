import { NextRequest } from "next/server";
import { getSession, requirePermission } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { getCampaign, updateCampaign } from "@/services/campaign.service";

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "campaigns", "view");
    const campaign = await getCampaign(session.organizationId, params.id);
    return ok(campaign);
  });
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "campaigns", "edit");
    const body = await req.json();
    return ok(await updateCampaign(session.organizationId, params.id, body));
  });
}
