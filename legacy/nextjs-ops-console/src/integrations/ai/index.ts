import { getAiRuntime } from "@/lib/ai-config";
import type { AiProvider } from "./types";
import { MockAiProvider } from "./mock";
import { OpenAiProvider } from "./openai";
import { AnthropicProvider } from "./anthropic";
import { OllamaProvider } from "./ollama";

let cached: AiProvider | null = null;
let cachedKey = "";

// 根据后台实时配置选择 provider（支持在「设置 → AI 配置」切换，保存即生效）。
export function getAiProvider(): AiProvider {
  const cfg = getAiRuntime();
  const key = `${cfg.provider}|${cfg.openaiModel}|${cfg.openaiBaseUrl}|${cfg.anthropicModel}|${cfg.ollamaUrl}`;
  if (cached && cachedKey === key) return cached;
  switch (cfg.provider) {
    case "openai":
      cached = new OpenAiProvider(cfg);
      break;
    case "anthropic":
      cached = new AnthropicProvider();
      break;
    case "ollama":
      cached = new OllamaProvider();
      break;
    case "mock":
    default:
      cached = new MockAiProvider();
  }
  cachedKey = key;
  return cached;
}

export type * from "./types";
