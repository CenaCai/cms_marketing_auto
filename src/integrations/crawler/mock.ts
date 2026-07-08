import type { CrawlRequest, CrawlResult, CrawlerProvider, Lead } from "./types";

// 占位实现：返回样例线索，并强制带上 sourceUrl（合规要求）。不真实爬取。
export class MockCrawlerProvider implements CrawlerProvider {
  readonly name = "mock";

  async scrape(req: CrawlRequest): Promise<CrawlResult> {
    const leads: Lead[] = [
      {
        companyName: "Example Events Co.",
        contactName: "Jane Doe",
        email: "jane@example.com",
        phone: "+971500000000",
        website: "https://example.com",
        socialUrl: "https://linkedin.com/in/example",
        sourceUrl: "https://linkedin.com/public-directory/example",
      },
    ];
    console.info(
      `[crawler:mock] keywords=${req.keywords.join(",")} returned ${leads.length} leads (mock)`,
    );
    return {
      provider: "mock",
      leads,
      note: "[mock] 返回样例数据，且全部带有 sourceUrl。接入真实爬虫后需通过合规审核再导入。",
    };
  }
}
