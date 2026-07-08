import { env } from "@/lib/env";
import type { AiProvider } from "./types";
import { MockAiProvider } from "./mock";
import { OpenAiProvider } from "./openai";
import { AnthropicProvider } from "./anthropic";
import { OllamaProvider } from "./ollama";

let cached: AiProvider | null = null;

export function getAiProvider(): AiProvider {
  if (cached) return cached;
  switch (env.aiProvider) {
    case "openai":
      cached = new OpenAiProvider();
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
  return cached;
}

export type * from "./types";
