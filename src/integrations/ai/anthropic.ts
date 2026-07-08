import type { AiProvider } from "./types";

// ---------------------------------------------------------------------
// Anthropic Claude 接口（占位 / 留接口）
// 落地：npm i @anthropic-ai/sdk，配置 ANTHROPIC_API_KEY / ANTHROPIC_MODEL
// ---------------------------------------------------------------------
export class AnthropicProvider implements AiProvider {
  readonly name = "anthropic";
  async generateCopy() {
    throw new Error("AnthropicProvider.generateCopy 尚未实现。");
  }
  async recommendSendTime() {
    throw new Error("AnthropicProvider.recommendSendTime 尚未实现。");
  }
  async recommendSegment() {
    throw new Error("AnthropicProvider.recommendSegment 尚未实现。");
  }
  async generateWorkflowDraft() {
    throw new Error("AnthropicProvider.generateWorkflowDraft 尚未实现。");
  }
  async analyzeCampaign() {
    throw new Error("AnthropicProvider.analyzeCampaign 尚未实现。");
  }
}
