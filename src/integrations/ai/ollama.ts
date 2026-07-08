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
// Ollama / 本地开源模型接口（占位 / 留接口）
// 落地：直接 HTTP 调本机 Ollama 的 /api/generate（无需 SDK）
// 配置 OLLAMA_BASE_URL（默认 http://localhost:11434）
// ---------------------------------------------------------------------
export class OllamaProvider implements AiProvider {
  readonly name = "ollama";
  async generateCopy(_req: CopyRequest): Promise<CopyResult> {
    throw new Error("OllamaProvider.generateCopy 尚未实现：请补全对 OLLAMA_BASE_URL 的调用。");
  }
  async recommendSendTime(_req: SendTimeRequest): Promise<SendTimeResult> {
    throw new Error("OllamaProvider.recommendSendTime 尚未实现。");
  }
  async recommendSegment(_req: SegmentRequest): Promise<SegmentResult> {
    throw new Error("OllamaProvider.recommendSegment 尚未实现。");
  }
  async generateWorkflowDraft(_req: WorkflowDraftRequest): Promise<WorkflowDraftResult> {
    throw new Error("OllamaProvider.generateWorkflowDraft 尚未实现。");
  }
  async analyzeCampaign(_req: CampaignAnalysisRequest): Promise<CampaignAnalysisResult> {
    throw new Error("OllamaProvider.analyzeCampaign 尚未实现。");
  }
}
