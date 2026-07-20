import { env } from "@/lib/env";
import type { ContactOutProvider } from "./types";
import { MockContactOutProvider } from "./mock";
import { ContactOutClient } from "./client";

let cached: ContactOutProvider | null = null;

// 工厂：未开启或未配置 key 时返回 mock（绝不真实调用 API、绝不写库）。
export function getContactOutProvider(): ContactOutProvider {
  if (cached) return cached;
  if (!env.contactoutEnabled || !env.contactoutApiKey) {
    cached = new MockContactOutProvider();
    return cached;
  }
  cached = new ContactOutClient(env.contactoutApiKey);
  return cached;
}

export type * from "./types";
export { PROSPECT_TAG } from "./mapper";
