import { prisma } from "@/lib/db";
import { getQueue } from "@/integrations/queue";
import { addTagToContact, removeTagFromContact } from "./tag.service";
import { addContactsToSegment, removeContactsFromSegment } from "./segment.service";
import { getEmailProvider } from "@/integrations/email";
import { getSmsProvider } from "@/integrations/sms";
import { renderTemplate } from "./template.service";
type Channel = string;

// ----------------------- 工作流定义（JSON） -----------------------
// 与 PRD 6.1 对齐：Trigger / Condition / Action / Delay / Branch
// 本 MVP 引擎实现线性动作序列（含 wait 延迟），分支以条件动作占位。
export interface WorkflowAction {
  type:
    | "send_email"
    | "send_sms"
    | "add_tag"
    | "remove_tag"
    | "join_segment"
    | "leave_segment"
    | "call_webhook"
    | "wait";
  config: Record<string, any>;
}

export interface WorkflowDefinition {
  trigger:
    | { type: "event"; eventType?: string; eventName?: string }
    | { type: "tag_added"; tagId: string }
    | { type: "segment_joined"; segmentId: string }
    | { type: "webhook" }
    | { type: "custom_event"; eventName: string };
  actions: WorkflowAction[];
}

export interface TriggerContext {
  contactId?: string;
  eventName: string;
  eventType: string;
  properties: Record<string, unknown>;
}

// 注册 workflow_continue 处理器（用于 wait 延迟后继续剩余动作）
let registered = false;
function ensureRegistered() {
  if (registered) return;
  registered = true;
  getQueue().registerProcessor("workflow_continue", async (data) => {
    const { organizationId, contactId, actions } = data as any;
    await runActions(organizationId, contactId, actions as WorkflowAction[]);
  });
}

function triggerMatches(def: WorkflowDefinition, ctx: TriggerContext): boolean {
  const t = def.trigger;
  if (t.type === "event") {
    if (t.eventType && t.eventType !== ctx.eventType) return false;
    if (t.eventName && t.eventName !== ctx.eventName) return false;
    return true;
  }
  if (t.type === "custom_event") return t.eventName === ctx.eventName;
  // tag_added / segment_joined / webhook 由对应写入口单独触发，这里不处理
  return false;
}

// 事件写入后调用：匹配并触发已启用的工作流
export async function processWorkflowTriggers(orgId: string, ctx: TriggerContext) {
  if (!ctx.contactId) return;
  const workflows = await prisma.workflow.findMany({
    where: { organizationId: orgId, enabled: true },
  });
  for (const wf of workflows) {
    const def = JSON.parse(wf.definition) as WorkflowDefinition;
    if (!def?.trigger || !triggerMatches(def, ctx)) continue;
    await runActions(orgId, ctx.contactId, def.actions ?? []);
  }
}

async function runActions(
  orgId: string,
  contactId: string,
  actions: WorkflowAction[],
) {
  ensureRegistered();
  for (const action of actions) {
    try {
      switch (action.type) {
        case "add_tag":
          if (action.config.tagId)
            await addTagToContact(contactId, action.config.tagId);
          break;
        case "remove_tag":
          if (action.config.tagId)
            await removeTagFromContact(contactId, action.config.tagId);
          break;
        case "join_segment":
          if (action.config.segmentId)
            await addContactsToSegment(action.config.segmentId, [contactId]);
          break;
        case "leave_segment":
          if (action.config.segmentId)
            await removeContactsFromSegment(action.config.segmentId, [contactId]);
          break;
        case "send_email":
        case "send_sms":
          await sendAdHoc(orgId, contactId, action);
          break;
        case "call_webhook":
          if (action.config.url) {
            await fetch(action.config.url, {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify({ contactId, ...action.config.payload }),
            }).catch(() => {});
          }
          break;
        case "wait":
          // 延迟后继续剩余动作：把后续动作重新入队
          await getQueue().enqueue(
            "workflow_continue",
            {
              organizationId: orgId,
              contactId,
              actions: actions.slice(actions.indexOf(action) + 1),
            },
            { delayMs: Number(action.config.minutes ?? 60) * 60 * 1000 },
          );
          return; // 当前序列到此中断，由延迟任务续跑
      }
    } catch (e) {
      console.error(`[workflow] action ${action.type} failed`, e);
    }
  }
}

// 即时发送（工作流内调用）：按 action.config 中的模板/文案发送
async function sendAdHoc(
  orgId: string,
  contactId: string,
  action: WorkflowAction,
) {
  const contact = await prisma.contact.findUnique({ where: { id: contactId } });
  if (!contact) return;
  const channel: Channel = action.type === "send_email" ? "EMAIL" : "SMS";
  const to = channel === "EMAIL" ? contact.email : contact.phone;
  if (!to) return;

  const vars: Record<string, string> = {
    first_name: (contact.name ?? "").split(" ")[0] || "",
    name: contact.name ?? "",
    city: contact.city ?? "",
    country: contact.country ?? "",
  };

  let body = action.config.body ?? "";
  let subject = action.config.subject ?? "Notification";
  body = renderTemplate(body, vars);
  subject = renderTemplate(subject, vars);

  const providerName = channel === "EMAIL" ? getEmailProvider().name : getSmsProvider().name;
  try {
    const result =
      channel === "EMAIL"
        ? await getEmailProvider().send({ to, subject, html: body })
        : await getSmsProvider().send({ to, body });
    await prisma.sendLog.create({
      data: {
        organizationId: orgId,
        taskId: "__workflow__",
        contactId,
        channel,
        provider: result.provider,
        status: result.accepted ? "success" : "failed",
        messageId: result.messageId,
        sentAt: new Date(),
      },
    });
  } catch (e: any) {
    await prisma.sendLog.create({
      data: {
        organizationId: orgId,
        taskId: "__workflow__",
        contactId,
        channel,
        provider: providerName,
        status: "failed",
        errorMessage: e?.message ?? String(e),
      },
    });
  }
}

// 工作流 CRUD（供 API 调用）
export const workflowRepo = {
  get: (orgId: string, id: string) =>
    prisma.workflow.findFirst({ where: { organizationId: orgId, id } }),
  list: (orgId: string) =>
    prisma.workflow.findMany({ where: { organizationId: orgId }, orderBy: { createdAt: "desc" } }),
  create: (orgId: string, data: { name: string; description?: string; definition: WorkflowDefinition; enabled?: boolean }) =>
    prisma.workflow.create({
      data: { organizationId: orgId, name: data.name, description: data.description, definition: JSON.stringify(data.definition), enabled: data.enabled ?? false },
    }),
  update: (orgId: string, id: string, data: Partial<{ name: string; description: string; definition: WorkflowDefinition; enabled: boolean }>) =>
    prisma.workflow.update({
      where: { id },
      data: (() => {
        const { definition, ...rest } = data;
        return { ...rest, ...(definition !== undefined ? { definition: JSON.stringify(definition) } : {}) };
      })(),
    }),
  remove: (orgId: string, id: string) =>
    prisma.workflow.deleteMany({ where: { organizationId: orgId, id } }),
};
