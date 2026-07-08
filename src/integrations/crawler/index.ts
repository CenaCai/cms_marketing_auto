import { env } from "@/lib/env";
import type { CrawlerProvider } from "./types";
import { MockCrawlerProvider } from "./mock";
import { PlaywrightCrawlerProvider } from "./playwright";

let cached: CrawlerProvider | null = null;

export function getCrawlerProvider(): CrawlerProvider {
  if (cached) return cached;
  if (!env.crawlerEnabled) {
    // 默认直接返回 mock，即便未显式开启也绝不会触发真实爬取。
    cached = new MockCrawlerProvider();
    return cached;
  }
  switch (env.crawlerProvider) {
    case "playwright":
      cached = new PlaywrightCrawlerProvider();
      break;
    case "mock":
    default:
      cached = new MockCrawlerProvider();
  }
  return cached;
}

export type * from "./types";
