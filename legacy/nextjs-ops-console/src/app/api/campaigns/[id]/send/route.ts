import { NextRequest } from "next/server";
import { getSession, requirePermission } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { createBatchSend } from "@/services/send.service";
import { getCampaign } from "@/services/campaign.service";
type Channel = string;

// 对 campaign 触发批量发送（支持多渠道 / 多模板）
export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  return handle(async () => {
    const session = await getSession(req);
    await requirePermission(session, "campaigns", "edit");
    const body = await req.json().catch(() => ({}));
    const campaign = await getCampaign(session.organizationId, params.id);
    if (!campaign) throw new Error("活动不存在");

    const channel = (body.channel ?? campaign.channel ?? "EMAIL") as Channel;
    const templateId =
      body.templateId ??
      (channel === "SMS" ? campaign.smsTemplateId : campaign.edmTemplateId) ??
      campaign.templateId ??
      undefined;

    // 解析人群：优先用请求显式指定，否则回退到活动配置
    const audienceType = body.audienceType ?? campaign.audienceType ?? undefined;
    let segmentId = body.segmentId ?? campaign.segmentId ?? undefined;
    let tagIds = body.tagIds ?? (campaign.tagIds ? JSON.parse(campaign.tagIds) : undefined);
    let sqlQuery = body.sqlQuery ?? campaign.sqlQuery ?? undefined;
    // 兼容旧活动：无 audienceType 但有 segmentId
    if (!audienceType && segmentId) {
      // 沿用 segment
    }

    const result = await createBatchSend(session.organizationId, {
      campaignId: params.id,
      channel,
      templateId,
      segmentId,
      tagIds,
      sqlQuery,
      scheduleAt: body.scheduleAt,
    });
    return ok(result, 201);
  });
}
