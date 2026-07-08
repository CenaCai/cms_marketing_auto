import { NextRequest } from "next/server";
import { getSession } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { prisma } from "@/lib/db";
import type { Channel, ConsentStatus } from "@prisma/client";

// V4 多渠道：联系人的额外触达渠道（WhatsApp / Telegram / App User ID ...）
export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    await getSession(req);
    const channels = await prisma.contactChannel.findMany({
      where: { contactId: params.id },
    });
    return ok(channels);
  });
}

export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    await getSession(req);
    const body = await req.json();
    const channel = await prisma.contactChannel.create({
      data: {
        contactId: params.id,
        channel: body.channel as Channel,
        identifier: body.identifier,
        verified: body.verified ?? false,
        consentStatus: (body.consentStatus as ConsentStatus) ?? "unknown",
      },
    });
    return ok(channel, 201);
  });
}
