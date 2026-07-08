import type {
  AiProvider,
  CampaignAnalysisRequest,
  CampaignAnalysisResult,
  CopyRequest,
  CopyResult,
  SegmentRequest,
  SegmentResult,
  SendTimeRequest,
  SendTimeResult,
  WorkflowDraftRequest,
  WorkflowDraftResult,
} from "./types";

// 占位实现：不调用任何真实大模型，返回结构化样例，保证前端可联调。
export class MockAiProvider implements AiProvider {
  readonly name = "mock";

  async generateCopy(req: CopyRequest): Promise<CopyResult> {
    const lang = req.language ?? "zh";
    const offer = req.offer ? `（优惠：${req.offer}）` : "";
    const base =
      lang === "en"
        ? `Don't miss ${req.activityName ?? req.campaignName}! ${req.cta ?? "Book now"}${offer}`
        : `别错过 ${req.activityName ?? req.campaignName}！${req.cta ?? "立即报名"}${offer}`;
    return {
      variants: [
        { content: base, note: "默认版本" },
        { content: `${base} [A/B 变体 B]`, note: "强调紧迫感" },
      ],
    };
  }

  async recommendSendTime(req: SendTimeRequest): Promise<SendTimeResult> {
    // 规则占位：默认推荐目标时区当天 10:00
    const tz = req.timezone ?? "UTC";
    const date = new Date();
    date.setUTCHours(10, 0, 0, 0);
    return {
      recommendedAt: date.toISOString(),
      reason: `[mock] 基于规则：默认推荐 ${tz} 10:00，后续可接模型。`,
    };
  }

  async recommendSegment(req: SegmentRequest): Promise<SegmentResult> {
    return {
      suggestions: [
        {
          name: "high_intent",
          description: `目标 "${req.goal}" 的高意向用户`,
          rules: { lastActiveWithinDays: 7, hasPurchase: false },
        },
        {
          name: "silent_30d",
          description: "30 天未活跃用户",
          rules: { lastActiveWithinDays: -30 },
        },
      ],
    };
  }

  async generateWorkflowDraft(req: WorkflowDraftRequest): Promise<WorkflowDraftResult> {
    return {
      trigger: "用户浏览活动页",
      conditions: ["是否购买"],
      actions: ["Wait 2 小时", "Send EDM：门票提醒", "Wait 1 天"],
      delays: ["2 小时", "1 天"],
      branches: ["Yes → End", "No → Send EDM / SMS"],
      successMetric: `目标 "${req.goal}" 的转化率提升`,
    };
  }

  async analyzeCampaign(
    req: CampaignAnalysisRequest,
  ): Promise<CampaignAnalysisResult> {
    return {
      summary: `[mock] 已收到指标：${JSON.stringify(req.metrics)}。后续接入模型后给出自然语言复盘。`,
      bestPerforming: { channel: "EMAIL", template: "v1", segment: "high_intent" },
      suggestions: [
        "对未打开用户进行二次触达",
        "将发送时间调整到本地晚 8 点",
      ],
    };
  }
}
