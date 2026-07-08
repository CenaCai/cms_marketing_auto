import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { getSendTask } from "@/services/send.service";

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    return ok(await getSendTask(session.organizationId, params.id));
  });
}
