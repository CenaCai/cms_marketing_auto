// =====================================================================
// AI integration seam (V3: AI 辅助运营)
// ---------------------------------------------------------------------
// 第三方开源/SDK 依赖（默认 mock）：
//   - openai              —— OpenAI / 兼容 OpenAI 协议的模型，npm i openai
//   - @anthropic-ai/sdk   —— Claude 系列，npm i @anthropic-ai/sdk
//   - ollama (HTTP)       —— 本地/自建开源模型，无需 SDK，直接打 /api/generate
// 用途：AI 文案生成、发送时间推荐、自动分群、Workflow 草案、营销复盘。
// 默认 AI_PROVIDER=mock，返回结构化占位结果，便于前后端联调。
// =====================================================================

export interface CopyRequest {
  campaignName: string;
  activityName?: string;
  targetSegment?: string;
  country?: string;
  language?: string;
  tone?: string;
  offer?: string;
  cta?: string;
  channel: "EDM_TITLE" | "EDM_BODY" | "SMS" | "WHATSAPP" | "APP_PUSH" | "SOCIAL" | "AD";
}

export interface CopyResult {
  variants: { content: string; note?: string }[];
}

export interface SendTimeRequest {
  country?: string;
  timezone?: string;
  contactId?: string;
  history?: { opened: number; clicked: number; hour: number }[];
}

export interface SendTimeResult {
  recommendedAt: string; // ISO
  reason: string;
}

export interface SegmentRequest {
  organizationId: string;
  goal: string; // 例如 "识别高意向用户"
}

export interface SegmentResult {
  suggestions: {
    name: string;
    description: string;
    rules: Record<string, unknown>;
  }[];
}

export interface WorkflowDraftRequest {
  goal: string; // 例如 "提升 F1 活动转化"
}

export interface WorkflowDraftResult {
  trigger: string;
  conditions: string[];
  actions: string[];
  delays: string[];
  branches: string[];
  successMetric: string;
}

export interface CampaignAnalysisRequest {
  campaignId: string;
  metrics: Record<string, number>;
}

export interface CampaignAnalysisResult {
  summary: string;
  bestPerforming: { channel?: string; template?: string; segment?: string };
  suggestions: string[];
}

export interface AiProvider {
  readonly name: string;
  generateCopy(req: CopyRequest): Promise<CopyResult>;
  recommendSendTime(req: SendTimeRequest): Promise<SendTimeResult>;
  recommendSegment(req: SegmentRequest): Promise<SegmentResult>;
  generateWorkflowDraft(req: WorkflowDraftRequest): Promise<WorkflowDraftResult>;
  analyzeCampaign(req: CampaignAnalysisRequest): Promise<CampaignAnalysisResult>;
}
