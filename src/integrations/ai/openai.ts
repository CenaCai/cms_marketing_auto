import type { AiProvider } from "./types";

// ---------------------------------------------------------------------
// OpenAI / 兼容协议接口（占位 / 留接口）
// 落地：npm i openai，配置 OPENAI_API_KEY / OPENAI_MODEL
// 建议：所有方法统一调用 chat.completions.create，并把 system prompt 写在
//       prompts/ 目录下，输出用 JSON mode (response_format: {type:"json_object"})
//       再用 zod 解析，保证结构化返回。
// ---------------------------------------------------------------------
export class OpenAiProvider implements AiProvider {
  readonly name = "openai";
  async generateCopy() {
    throw new Error("OpenAiProvider.generateCopy 尚未实现：请安装 openai 并补全调用。");
  }
  async recommendSendTime() {
    throw new Error("OpenAiProvider.recommendSendTime 尚未实现。");
  }
  async recommendSegment() {
    throw new Error("OpenAiProvider.recommendSegment 尚未实现。");
  }
  async generateWorkflowDraft() {
    throw new Error("OpenAiProvider.generateWorkflowDraft 尚未实现。");
  }
  async analyzeCampaign() {
    throw new Error("OpenAiProvider.analyzeCampaign 尚未实现。");
  }
}
