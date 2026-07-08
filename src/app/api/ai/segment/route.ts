import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { aiService } from "@/services/ai.service";
import type { SegmentRequest } from "@/integrations/ai/types";

export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    const body = await req.json();
    return ok(
      await aiService.recommendSegment({
        organizationId: session.organizationId,
        goal: body.goal,
      }),
    );
  });
}
