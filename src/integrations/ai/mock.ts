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
    const topic = req.activityName ?? req.campaignName ?? "我们的新品";
    const offer = req.offer ? `（优惠：${req.offer}）` : "";
    const cta = req.cta ?? (lang === "en" ? "Learn more" : "立即了解");
    const tone = req.tone ?? (lang === "en" ? "" : "亲切");

    // 标题
    if (req.channel === "EDM_TITLE") {
      const title =
        lang === "en"
          ? `${topic} — Don't miss this ${offer}`
          : `${topic}｜限时${offer}等你来`;
      return {
        variants: [
          { content: title, note: "标准版" },
          { content: lang === "en" ? `Last call: ${topic}` : `最后机会：${topic}`, note: "紧迫感版" },
        ],
      };
    }

    // 邮件正文（HTML）
    const body = `<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#1f2937">
  <h1 style="font-size:22px;margin:0 0 12px">${topic}</h1>
  <p style="line-height:1.7;color:#374151">${tone ? `您好，${tone}地` : "您好，"}为您带来最新消息：${topic}。${offer ? `本次更有限时优惠 ${offer}，` : ""}期待您的参与。</p>
  <p style="line-height:1.7;color:#374151">点击下方按钮${cta}，了解更多详情。</p>
  <p style="margin:24px 0"><a href="{{landing_page_url}}" style="background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;display:inline-block">${cta}</a></p>
  <p style="font-size:12px;color:#9ca3af">若无法正常显示，请通过「邮箱客户端」查看。退订请点击邮件底部链接。</p>
</div>`;
    return {
      variants: [
        { content: body, note: "标准版" },
        {
          content: body.replace("期待您的参与。", "现在就行动，名额有限！").replace("为您带来", "特别为您带来"),
          note: "紧迫感版",
        },
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
