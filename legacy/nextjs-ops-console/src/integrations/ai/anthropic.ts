import type {
  AiProvider,
  CopyRequest,
  CopyResult,
  SendTimeRequest,
  SendTimeResult,
  SegmentRequest,
  SegmentResult,
  WorkflowDraftRequest,
  WorkflowDraftResult,
  CampaignAnalysisRequest,
  CampaignAnalysisResult,
} from "./types";

// ---------------------------------------------------------------------
// Anthropic / Claude 接口（占位 / 留接口）
// 落地：npm i @anthropic-ai/sdk，配置 ANTHROPIC_API_KEY / ANTHROPIC_MODEL
// 建议：messages.create + tool_use 返回结构化 JSON，再用 zod 解析。
// ---------------------------------------------------------------------
export class AnthropicProvider implements AiProvider {
  readonly name = "anthropic";
  async generateCopy(_req: CopyRequest): Promise<CopyResult> {
    throw new Error("AnthropicProvider.generateCopy 尚未实现：请安装 @anthropic-ai/sdk 并补全调用。");
  }
  async recommendSendTime(_req: SendTimeRequest): Promise<SendTimeResult> {
    throw new Error("AnthropicProvider.recommendSendTime 尚未实现。");
  }
  async recommendSegment(_req: SegmentRequest): Promise<SegmentResult> {
    throw new Error("AnthropicProvider.recommendSegment 尚未实现。");
  }
  async generateWorkflowDraft(_req: WorkflowDraftRequest): Promise<WorkflowDraftResult> {
    throw new Error("AnthropicProvider.generateWorkflowDraft 尚未实现。");
  }
  async analyzeCampaign(_req: CampaignAnalysisRequest): Promise<CampaignAnalysisResult> {
    throw new Error("AnthropicProvider.analyzeCampaign 尚未实现。");
  }
}
