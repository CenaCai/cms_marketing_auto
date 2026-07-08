import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { aiService } from "@/services/ai.service";
import type { CampaignAnalysisRequest } from "@/integrations/ai/types";

export async function POST(req: NextRequest) {
  return handle(async () => {
    await getSession(req);
    const body = await req.json();
    return ok(await aiService.analyzeCampaign(body as CampaignAnalysisRequest));
  });
}
