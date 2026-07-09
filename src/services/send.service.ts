import { prisma } from "@/lib/db";
import { getQueue } from "@/integrations/queue";
import { getEmailProvider } from "@/integrations/email";
import { getSmsProvider } from "@/integrations/sms";
import { renderTemplate } from "./template.service";
type Channel = string;

// 频控：同一联系人同一渠道 24h 内最多发送次数
const FREQ_LIMIT_PER_DAY = 5;

// 注册队列处理器（内存队列在 import 时即生效）。
// 生产环境使用 bullmq 时，请将此处逻辑搬到 scripts/worker.ts 的 Worker 中。
let registered = false;
export function registerSendProcessor() {
  if (registered) return;
  registered = true;
  getQueue().registerProcessor("send_one", async (data) => {
    await processSingleSend(data as unknown as SingleSendJob);
  });
}

interface SingleSendJob {
  organizationId: string;
  taskId: string;
  contactId: string;
  channel: Channel;
}

const BASE_URL = process.env.APP_BASE_URL ?? "http://localhost:3000";

async function processSingleSend(job: SingleSendJob) {
  const { organizationId, taskId, contactId, channel } = job;

  const contact = await prisma.contact.findUnique({ where: { id: contactId } });
  const task = await prisma.sendTask.findUnique({
    where: { id: taskId },
    include: { campaign: { include: { template: true } } },
  });
  if (!contact || !task) return;

  const template = task.campaign?.template;
  const to = channel === "EMAIL" ? contact.email : contact.phone;

  // ---- 过滤规则 ----
  const skip = (reason: string) =>
    prisma.sendLog.create({
      data: {
        organizationId,
        taskId,
        contactId,
        channel,
        provider: "system",
        status: "skipped",
        errorMessage: reason,
      },
    });

  if (!to) return skip("无有效联系方式");
  if (contact.status === "unsubscribed") return skip("已退订");
  if (contact.status === "bounced") return skip("邮箱 bounce");
  if (contact.status === "blacklisted") return skip("黑名单");

  // 频控
  const since = new Date(Date.now() - 24 * 3600 * 1000);
  const recent = await prisma.sendLog.count({
    where: { contactId, channel, status: "success", sentAt: { gte: since } },
  });
  if (recent >= FREQ_LIMIT_PER_DAY) return skip("超过频控上限");

  // ---- 渲染 ----
  const vars: Record<string, string> = {
    first_name: (contact.name ?? "").split(" ")[0] || contact.name || "",
    name: contact.name ?? "",
    city: contact.city ?? "",
    country: contact.country ?? "",
  };
  let body = template?.body ?? "";
  let subject = template?.subject ?? task.campaign?.name ?? "Notification";

  if (channel === "EMAIL" && template) {
    // 注入打开追踪像素 + 链接点击追踪
    const openUrl = `${BASE_URL}/api/track/open?logId={{LOG_ID}}`;
    const clickWrap = (url: string) =>
      `${BASE_URL}/api/track/click?logId={{LOG_ID}}&url=${encodeURIComponent(url)}`;
    body = renderTemplate(body, { ...vars, landing_page_url: clickWrap("{{landing_page_url}}") });
    // 简单把 landing_page_url 占位替换为包装链接（如模板直接写 {{landing_page_url}}）
    subject = renderTemplate(subject, vars);
    body = `${body}\n<img src="${openUrl}" width="1" height="1" alt="" />`;
  } else if (template) {
    body = renderTemplate(body, vars);
  }

  // 占位 LOG_ID 在拿到 messageId 前无法预知，改为发送后回写（简化：先用临时标记，追踪接口按 contact+task 匹配）
  const providerName = channel === "EMAIL" ? getEmailProvider().name : getSmsProvider().name;
  try {
    const result =
      channel === "EMAIL"
        ? await getEmailProvider().send({ to: to!, subject, html: body })
        : await getSmsProvider().send({ to: to!, body });

    await prisma.sendLog.create({
      data: {
        organizationId,
        taskId,
        contactId,
        channel,
        provider: result.provider,
        status: result.accepted ? "success" : "failed",
        messageId: result.messageId,
        sentAt: new Date(),
      },
    });
    await prisma.sendTask.update({
      where: { id: taskId },
      data: result.accepted
        ? { successCount: { increment: 1 } }
        : { failedCount: { increment: 1 } },
    });
  } catch (e: any) {
    await prisma.sendLog.create({
      data: {
        organizationId,
        taskId,
        contactId,
        channel,
        provider: providerName,
        status: "failed",
        errorMessage: e?.message ?? String(e),
      },
    });
    await prisma.sendTask.update({
      where: { id: taskId },
      data: { failedCount: { increment: 1 } },
    });
  }
}

export interface BatchSendInput {
  campaignId: string;
  segmentId?: string;
  templateId?: string;
  channel: Channel;
  scheduleAt?: string; // ISO，定时发送
  contactIds?: string[]; // 直接指定（不走分群）
  tagIds?: string[]; // 按标签选人（多个标签取并集）
}

// 创建批量发送：解析目标联系人 -> 过滤 -> 创建任务 -> 入队
export async function createBatchSend(orgId: string, input: BatchSendInput) {
  registerSendProcessor();

  let targetIds: string[];
  if (input.contactIds?.length) {
    targetIds = input.contactIds;
  } else if (input.tagIds?.length) {
    // 按标签选人：拥有任一所选标签的联系人（并集）
    const contacts = await prisma.contact.findMany({
      where: {
        organizationId: orgId,
        contactTags: { some: { tagId: { in: input.tagIds } } },
      },
      select: { id: true },
    });
    targetIds = contacts.map((c) => c.id);
  } else if (input.segmentId) {
    const seg = await prisma.segment.findFirst({
      where: { organizationId: orgId, id: input.segmentId },
    });
    if (!seg) throw new Error("segment 不存在");
    if (seg.type === "dynamic" && seg.rules) {
      // 复用 segment 求值
      const { evaluateSegment } = await import("./segment.service");
      targetIds = await evaluateSegment(orgId, JSON.parse(seg.rules));
    } else {
      const members = await prisma.contactSegment.findMany({
        where: { segmentId: input.segmentId },
        select: { contactId: true },
      });
      targetIds = members.map((m) => m.contactId);
    }
  } else {
    throw new Error("必须指定 contactIds / tagIds / segmentId 之一");
  }

  const task = await prisma.sendTask.create({
    data: {
      organizationId: orgId,
      campaignId: input.campaignId,
      channel: input.channel,
      status: "queued",
      totalCount: targetIds.length,
    },
  });

  const delayMs = input.scheduleAt
    ? Math.max(0, new Date(input.scheduleAt).getTime() - Date.now())
    : 0;

  const queue = getQueue();
  for (const cid of targetIds) {
    await queue.enqueue(
      "send_one",
      { organizationId: orgId, taskId: task.id, contactId: cid, channel: input.channel },
      { delayMs },
    );
  }

  // 更新 campaign 状态
  await prisma.campaign.updateMany({
    where: { id: input.campaignId },
    data: { status: "sending" },
  });

  return { taskId: task.id, totalCount: targetIds.length, scheduled: !!input.scheduleAt };
}

export async function getSendTask(orgId: string, taskId: string) {
  return prisma.sendTask.findFirst({
    where: { organizationId: orgId, id: taskId },
    include: {
      logs: { orderBy: { sentAt: "desc" }, take: 50 },
      campaign: true,
    },
  });
}
