import { getAiProvider } from "@/integrations/ai";
import type {
  CampaignAnalysisRequest,
  CopyRequest,
  SegmentRequest,
  SendTimeRequest,
  WorkflowDraftRequest,
} from "@/integrations/ai/types";

// AI 能力的统一入口（V3）。默认走 mock provider，可在 .env 切换 openai/anthropic/ollama。
export const aiService = {
  generateCopy: (req: CopyRequest) => getAiProvider().generateCopy(req),
  recommendSendTime: (req: SendTimeRequest) => getAiProvider().recommendSendTime(req),
  recommendSegment: (req: SegmentRequest) => getAiProvider().recommendSegment(req),
  generateWorkflowDraft: (req: WorkflowDraftRequest) =>
    getAiProvider().generateWorkflowDraft(req),
  analyzeCampaign: (req: CampaignAnalysisRequest) =>
    getAiProvider().analyzeCampaign(req),
};
