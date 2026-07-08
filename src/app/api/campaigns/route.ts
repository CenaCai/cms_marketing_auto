import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import {
  listCampaigns,
  createCampaign,
} from "@/services/campaign.service";
type Channel = string;

export async function GET(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    return ok(await listCampaigns(session.organizationId));
  });
}

export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    const body = await req.json();
    return ok(
      await createCampaign(session.organizationId, {
        name: body.name,
        objective: body.objective,
        segmentId: body.segmentId,
        channel: body.channel as Channel,
        templateId: body.templateId,
        scheduledAt: body.scheduledAt,
      }),
      201,
    );
  });
}
