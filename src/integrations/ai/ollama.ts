import type { AiProvider } from "./types";

// ---------------------------------------------------------------------
// Ollama（本地开源模型）接口（占位 / 留接口）
// 落地：本地运行 `ollama serve`，配置 OLLAMA_BASE_URL（默认 http://localhost:11434）
// 直接 POST {model, prompt, stream:false} 到 /api/generate，无需额外 SDK。
// ---------------------------------------------------------------------
export class OllamaProvider implements AiProvider {
  readonly name = "ollama";
  async generateCopy() {
    throw new Error("OllamaProvider.generateCopy 尚未实现。");
  }
  async recommendSendTime() {
    throw new Error("OllamaProvider.recommendSendTime 尚未实现。");
  }
  async recommendSegment() {
    throw new Error("OllamaProvider.recommendSegment 尚未实现。");
  }
  async generateWorkflowDraft() {
    throw new Error("OllamaProvider.generateWorkflowDraft 尚未实现。");
  }
  async analyzeCampaign() {
    throw new Error("OllamaProvider.analyzeCampaign 尚未实现。");
  }
}
