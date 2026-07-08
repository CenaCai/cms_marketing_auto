import type { CrawlRequest, CrawlResult, CrawlerProvider } from "./types";

// ---------------------------------------------------------------------
// Playwright 接口（占位 / 留接口）—— 浏览器自动化爬取公开页面
// 落地：npm i playwright，并 `npx playwright install`
// 关键合规点（务必保留）：
//   1) 仅访问明确允许的公开来源白名单（在 config 中维护 allowedDomains）
//   2) 每条线索记录 sourceUrl
//   3) 命中邮箱/电话的线索默认标记 needsReview=true，禁止自动导入
//   4) 尊重 robots.txt 与目标站点的 ToS
// ---------------------------------------------------------------------
export class PlaywrightCrawlerProvider implements CrawlerProvider {
  readonly name = "playwright";
  async scrape(_req: CrawlRequest): Promise<CrawlResult> {
    throw new Error(
      "PlaywrightCrawlerProvider 尚未实现：请安装 playwright 并补全 scrape()，" +
        "严格保留 sourceUrl 与合规审核逻辑。",
    );
  }
}
