import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { getCampaign, updateCampaign } from "@/services/campaign.service";

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
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
    const body = await req.json();
    return ok(await updateCampaign(session.organizationId, params.id, body));
  });
}
