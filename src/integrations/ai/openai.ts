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
import type { AiRuntimeConfig } from "@/lib/ai-config";

// ---------------------------------------------------------------------
// OpenAI / 兼容协议实现（gpt-4o-mini 等；通过 baseUrl 可接 DeepSeek、本地
// vLLM、Azure OpenAI 等任何兼容 /chat/completions 的网关）。
// 使用原生 fetch（Node 18+ 内置），无需额外 SDK。
// ---------------------------------------------------------------------
export class OpenAiProvider implements AiProvider {
  readonly name = "openai";
  private cfg: AiRuntimeConfig;

  constructor(cfg: AiRuntimeConfig) {
    this.cfg = cfg;
  }

  private get key(): string {
    const k = this.cfg.openaiKey ?? process.env.OPENAI_API_KEY;
    if (!k) throw new Error("未配置 OpenAI API Key：请在「设置 → AI 配置」填写 ai.openaiKey。");
    return k;
  }

  private get baseUrl(): string {
    return (this.cfg.openaiBaseUrl ?? process.env.OPENAI_BASE_URL ?? "https://api.openai.com/v1").replace(
      /\/$/,
      "",
    );
  }

  private get model(): string {
    return this.cfg.openaiModel ?? process.env.OPENAI_MODEL ?? "gpt-4o-mini";
  }

  // 统一 chat 调用，返回文本
  private async chat(system: string, user: string, maxTokens = 800): Promise<string> {
    const resp = await fetch(`${this.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.key}`,
      },
      body: JSON.stringify({
        model: this.model,
        messages: [
          { role: "system", content: system },
          { role: "user", content: user },
        ],
        max_tokens: maxTokens,
        temperature: 0.8,
      }),
    });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      throw new Error(`OpenAI 调用失败 ${resp.status}: ${txt.slice(0, 300)}`);
    }
    const data = (await resp.json()) as any;
    return data?.choices?.[0]?.message?.content?.trim() ?? "";
  }

  async generateCopy(req: CopyRequest): Promise<CopyResult> {
    const lang = req.language ?? "zh";
    const isTitle = req.channel === "EDM_TITLE";

    const ctx = [
      req.campaignName && `活动：${req.campaignName}`,
      req.activityName && `主题：${req.activityName}`,
      req.targetSegment && `目标人群：${req.targetSegment}`,
      req.country && `国家/地区：${req.country}`,
      req.tone && `语气：${req.tone}`,
      req.offer && `优惠：${req.offer}`,
      req.cta && `行动号召：${req.cta}`,
    ]
      .filter(Boolean)
      .join("；");

    if (isTitle) {
      const out = await this.chat(
        `你是资深邮件营销文案专家，擅长写高打开率的邮件标题。只输出标题本身，不要解释、不要引号。语言：${
          lang === "en" ? "English" : "中文"
        }。`,
        `为以下营销内容生成一个吸引人且真实的邮件标题（不超过 30 字/40 字符）：${ctx}`,
        60,
      );
      return { variants: [{ content: out, note: "AI 生成标题" }] };
    }

    const out = await this.chat(
      `你是资深邮件营销文案专家，擅长写高转化率的 EDM 邮件正文。请直接输出可用于发送的 HTML 邮件正文（含简洁排版、段落、强调重点、明确的 CTA 按钮文字占位），不要输出解释，不要使用 markdown 代码块包裹。语言：${
        lang === "en" ? "English" : "中文"
      }。`,
      `为以下营销内容生成一封完整的邮件正文 HTML：${ctx}`,
      1200,
    );
    return { variants: [{ content: out, note: "AI 生成正文" }] };
  }

  async recommendSendTime(req: SendTimeRequest): Promise<SendTimeResult> {
    const out = await this.chat(
      "你是邮件发送时间优化专家。基于给定信息给出最佳发送时间（ISO 8601）和简短理由。只输出 JSON：{\"recommendedAt\":\"<iso>\",\"reason\":\"<中文理由>\"}。",
      `国家/时区：${req.timezone ?? req.country ?? "UTC"}；历史打开时段：${JSON.stringify(
        req.history ?? [],
      )}`,
      200,
    );
    try {
      const j = JSON.parse(out);
      return { recommendedAt: j.recommendedAt, reason: j.reason };
    } catch {
      const date = new Date();
      date.setUTCHours(10, 0, 0, 0);
      return { recommendedAt: date.toISOString(), reason: out.slice(0, 120) };
    }
  }

  async recommendSegment(req: SegmentRequest): Promise<SegmentResult> {
    const out = await this.chat(
      "你是用户分群策略专家。只输出 JSON：{\"suggestions\":[{\"name\":\"<snake_case>\",\"description\":\"<中文>\",\"rules\":{...}}]}。",
      `营销目标：${req.goal}`,
      400,
    );
    try {
      const j = JSON.parse(out);
      return { suggestions: j.suggestions ?? [] };
    } catch {
      return {
        suggestions: [
          { name: "high_intent", description: `目标 "${req.goal}" 的高意向用户`, rules: { hasPurchased: false } },
        ],
      };
    }
  }

  async generateWorkflowDraft(req: WorkflowDraftRequest): Promise<WorkflowDraftResult> {
    const out = await this.chat(
      "你是营销自动化流程专家。只输出 JSON：{\"trigger\":\"\",\"conditions\":[],\"actions\":[],\"delays\":[],\"branches\":[],\"successMetric\":\"\"}。",
      `目标：${req.goal}`,
      500,
    );
    try {
      return JSON.parse(out);
    } catch {
      return {
        trigger: "用户注册/订阅",
        conditions: ["是否活跃"],
        actions: ["发送欢迎邮件"],
        delays: ["1 天"],
        branches: ["已购买 → 结束", "未购买 → 提醒"],
        successMetric: req.goal,
      };
    }
  }

  async analyzeCampaign(
    req: CampaignAnalysisRequest,
  ): Promise<CampaignAnalysisResult> {
    const out = await this.chat(
      "你是营销复盘专家。基于指标给出中文复盘。只输出 JSON：{\"summary\":\"\",\"bestPerforming\":{\"channel\":\"\",\"template\":\"\",\"segment\":\"\"},\"suggestions\":[]}。",
      `Campaign ${req.campaignId} 指标：${JSON.stringify(req.metrics)}`,
      500,
    );
    try {
      return JSON.parse(out);
    } catch {
      return {
        summary: `收到指标：${JSON.stringify(req.metrics)}`,
        bestPerforming: { channel: "EMAIL" },
        suggestions: ["对未打开用户二次触达"],
      };
    }
  }
}
