import { NextRequest } from "next/server";
import { getSession, requireRole } from "@/lib/auth";
import { handle, ok, fail } from "@/lib/response";
import { getCrawlerProvider } from "@/integrations/crawler";
import { env } from "@/lib/env";

// AI 爬虫引流（V3.1）—— 合规受限模块
// 即使关闭，也只会返回 mock 样例；真实爬取需 CRAWLER_ENABLED=true 且经合规审核。
export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "ORG_ADMIN");
    const body = await req.json();
    const provider = getCrawlerProvider();
    const result = await provider.scrape({
      country: body.country,
      industry: body.industry,
      keywords: body.keywords ?? [],
      platform: body.platform,
      limit: body.limit,
    });
    return ok({
      ...result,
      // 合规提示：所有线索必须先经人工审核，不得自动导入联系人中心
      compliance: {
        enabled: env.crawlerEnabled,
        needsReview: true,
        warning:
          "涉及邮箱/电话的线索默认待审核；仅允许采集公开、合法、可商用来源，并保留 sourceUrl。",
      },
    });
  });
}
