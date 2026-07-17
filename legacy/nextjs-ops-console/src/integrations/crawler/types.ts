// =====================================================================
// AI 爬虫引流 seam (V3.1) —— 合规受限模块
// ---------------------------------------------------------------------
// ⚠️ 合规要求（来自 PRD 7.1）：仅允许采集公开、合法、可商用的数据来源，
//    并保留来源记录；涉及邮箱/电话需支持退订、黑名单与合规审核。
//    该模块默认关闭 (CRAWLER_ENABLED=false)，且必须经过人工审核后才能导入。
//
// 第三方开源/库依赖（默认 mock）：
//   - playwright   —— 浏览器自动化爬取，npm i playwright
//   - apify        —— 托管爬虫平台 SDK，npm i apify-client
// =====================================================================

export interface CrawlRequest {
  country?: string;
  industry?: string;
  keywords: string[];
  platform?: string; // 例如 linkedin、公司官网、公开黄页
  limit?: number;
}

export interface Lead {
  companyName?: string;
  contactName?: string;
  email?: string;
  phone?: string;
  website?: string;
  socialUrl?: string;
  sourceUrl: string; // 必须保留来源
}

export interface CrawlResult {
  provider: string;
  leads: Lead[];
  note: string;
}

export interface CrawlerProvider {
  readonly name: string;
  // 实现方必须做合规校验：过滤非公开来源、记录 sourceUrl、对邮箱/电话打标待审核。
  scrape(req: CrawlRequest): Promise<CrawlResult>;
}
