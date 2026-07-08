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
// OpenAI / 兼容协议接口（占位 / 留接口）
// 落地：npm i openai，配置 OPENAI_API_KEY / OPENAI_MODEL
// 建议：所有方法统一调用 chat.completions.create，并把 system prompt 写在
//       prompts/ 目录下，输出用 JSON mode (response_format: {type:"json_object"})
//       再用 zod 解析，保证结构化返回。
// ---------------------------------------------------------------------
export class OpenAiProvider implements AiProvider {
  readonly name = "openai";
  async generateCopy(_req: CopyRequest): Promise<CopyResult> {
    throw new Error("OpenAiProvider.generateCopy 尚未实现：请安装 openai 并补全调用。");
  }
  async recommendSendTime(_req: SendTimeRequest): Promise<SendTimeResult> {
    throw new Error("OpenAiProvider.recommendSendTime 尚未实现。");
  }
  async recommendSegment(_req: SegmentRequest): Promise<SegmentResult> {
    throw new Error("OpenAiProvider.recommendSegment 尚未实现。");
  }
  async generateWorkflowDraft(_req: WorkflowDraftRequest): Promise<WorkflowDraftResult> {
    throw new Error("OpenAiProvider.generateWorkflowDraft 尚未实现。");
  }
  async analyzeCampaign(_req: CampaignAnalysisRequest): Promise<CampaignAnalysisResult> {
    throw new Error("OpenAiProvider.analyzeCampaign 尚未实现。");
  }
}
