import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { aiService } from "@/services/ai.service";
import { refreshAiConfig } from "@/lib/ai-config";
import type { SendTimeRequest } from "@/integrations/ai/types";

export async function POST(req: NextRequest) {
  return handle(async () => {
    await getSession(req);
    const body = await req.json();
    await refreshAiConfig();
    return ok(await aiService.recommendSendTime(body as SendTimeRequest));
  });
}
