import { prisma } from "@/lib/db";
import type { CampaignStatus, Channel } from "@prisma/client";

export async function listCampaigns(orgId: string) {
  return prisma.campaign.findMany({
    where: { organizationId: orgId },
    include: { segment: true, template: true, _count: { select: { sendTasks: true } } },
    orderBy: { createdAt: "desc" },
  });
}

export async function createCampaign(
  orgId: string,
  data: {
    name: string;
    objective?: string;
    segmentId?: string;
    channel: Channel;
    templateId?: string;
    scheduledAt?: string;
  },
) {
  return prisma.campaign.create({
    data: {
      organizationId: orgId,
      name: data.name,
      objective: data.objective,
      segmentId: data.segmentId,
      channel: data.channel,
      templateId: data.templateId,
      scheduledAt: data.scheduledAt ? new Date(data.scheduledAt) : null,
      status: data.scheduledAt ? "scheduled" : "draft",
    },
  });
}

export async function getCampaign(orgId: string, id: string) {
  return prisma.campaign.findFirst({
    where: { organizationId: orgId, id },
    include: { segment: true, template: true, sendTasks: true },
  });
}

export async function updateCampaign(
  orgId: string,
  id: string,
  data: Record<string, unknown>,
) {
  const clean: Record<string, unknown> = { ...data, organizationId: orgId };
  if (typeof data.scheduledAt === "string") clean.scheduledAt = new Date(data.scheduledAt);
  return prisma.campaign.update({ where: { id }, data: clean });
}

export async function setCampaignStatus(
  orgId: string,
  id: string,
  status: CampaignStatus,
) {
  return prisma.campaign.update({
    where: { id },
    data: { status, ...(status === "sent" ? { sentAt: new Date() } : {}) },
  });
}
