import { prisma } from "@/lib/db";
import type { Channel } from "@prisma/client";

// 基于 send_logs 聚合 EDM / SMS 指标。
// 打开/点击来自追踪事件（track/open, track/click），这里统计已落库的回执。
export async function getChannelStats(orgId: string, channel: Channel) {
  const logs = await prisma.sendLog.groupBy({
    by: ["status"],
    where: { organizationId: orgId, channel },
    _count: { _all: true },
  });
  const count = (s: string) => logs.find((l) => l.status === s)?._count._all ?? 0;

  const total = logs.reduce((a, l) => a + l._count._all, 0);
  const sent = count("success");
  const failed = count("failed");
  const skipped = count("skipped");

  // 打开/点击：以事件中心回执为准
  const opened = await prisma.event.count({
    where: { organizationId: orgId, eventType: "CUSTOM", eventName: "email_opened" },
  });
  const clicked = await prisma.event.count({
    where: { organizationId: orgId, eventType: "CUSTOM", eventName: "link_clicked" },
  });

  return {
    channel,
    total,
    sent,
    failed,
    skipped,
    opened,
    clicked,
    openRate: sent ? Number(((opened / sent) * 100).toFixed(2)) : 0,
    clickRate: sent ? Number(((clicked / sent) * 100).toFixed(2)) : 0,
  };
}

export async function getCampaignStats(orgId: string, campaignId: string) {
  const tasks = await prisma.sendTask.findMany({
    where: { organizationId: orgId, campaignId },
    include: { logs: true },
  });
  const sent = tasks.reduce((a, t) => a + t.successCount, 0);
  const failed = tasks.reduce((a, t) => a + t.failedCount, 0);
  return { campaignId, tasks: tasks.length, sent, failed };
}
