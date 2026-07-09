// AI 运行时配置：优先读后台 Setting KV（可在「设置 → AI 配置」里改，保存即生效），
// 未配置时回退到环境变量。getAiRuntime() 为同步读取，供 ai/index 选择 provider。
import { prisma } from "./db";
import { env } from "./env";

export interface AiRuntimeConfig {
  provider: string; // mock | openai | anthropic | ollama
  openaiKey?: string;
  openaiBaseUrl?: string; // 兼容 OpenAI 协议的网关，如 DeepSeek
  openaiModel?: string;
  anthropicKey?: string;
  anthropicModel?: string;
  ollamaUrl?: string;
}

const KEYS = [
  "ai.provider",
  "ai.openaiKey",
  "ai.openaiBaseUrl",
  "ai.openaiModel",
  "ai.anthropicKey",
  "ai.anthropicModel",
  "ai.ollamaUrl",
];

// 初始值来自环境变量
let runtime: AiRuntimeConfig = {
  provider: env.aiProvider || "mock",
  openaiKey: process.env.OPENAI_API_KEY,
  openaiBaseUrl: process.env.OPENAI_BASE_URL,
  openaiModel: process.env.OPENAI_MODEL || "gpt-4o-mini",
  anthropicKey: process.env.ANTHROPIC_API_KEY,
  anthropicModel: process.env.ANTHROPIC_MODEL || "claude-3-5-sonnet-latest",
  ollamaUrl: process.env.OLLAMA_URL || "http://localhost:11434",
};

let loaded = false;

export function getAiRuntime(): AiRuntimeConfig {
  return runtime;
}

export function setAiRuntime(partial: Partial<AiRuntimeConfig>): void {
  runtime = { ...runtime, ...partial };
  loaded = true;
}

// 从 Setting KV 加载最新配置到运行时（在设置保存后、以及每次 AI 调用前调用）。
export async function refreshAiConfig(): Promise<AiRuntimeConfig> {
  try {
    const rows = await prisma.setting.findMany({ where: { key: { in: KEYS } } });
    const m: Record<string, string> = {};
    rows.forEach((r) => (m[r.key] = r.value));
    const next: AiRuntimeConfig = {
      provider: m["ai.provider"] || runtime.provider,
      openaiKey: m["ai.openaiKey"] || undefined,
      openaiBaseUrl: m["ai.openaiBaseUrl"] || undefined,
      openaiModel: m["ai.openaiModel"] || undefined,
      anthropicKey: m["ai.anthropicKey"] || undefined,
      anthropicModel: m["ai.anthropicModel"] || undefined,
      ollamaUrl: m["ai.ollamaUrl"] || undefined,
    };
    runtime = { ...runtime, ...next };
  } catch {
    // 数据库不可用时维持环境变量配置
  }
  loaded = true;
  return runtime;
}

export function aiConfigLoaded(): boolean {
  return loaded;
}
