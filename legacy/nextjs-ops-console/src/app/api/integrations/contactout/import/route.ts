import { NextRequest } from "next/server";
import { getSession, requireRole } from "@/lib/auth";
import { handle, ok } from "@/lib/response";
import { importLeadsFromContactOut } from "@/services/contactout.service";
import { env } from "@/lib/env";

// ContactOut 潜客导入（持牌 B2B 数据源）
// 写入本系统 Contact 表并打「潜客」标签。真实触达前须人工审核 + 合法基础。
export async function POST(req: NextRequest) {
  return handle(async () => {
    const session = await getSession(req);
    requireRole(session, "ORG_ADMIN");
    const body = await req.json();
    const result = await importLeadsFromContactOut(session.organizationId, {
      job_title: body.job_title ?? [],
      company: body.company ?? [],
      location: body.location ?? [],
      name: body.name,
      limit: body.limit ?? 25,
      reveal_info: true, // 拉取邮箱/电话，会消耗 credit
    });
    return ok({
      ...result,
      // 合规提示：所有线索必须先经人工审核，不得自动触达
      compliance: {
        enabled: env.contactoutEnabled,
        needsReview: true,
        warning:
          "ContactOut 返回的邮箱/电话属第三方来源 PII。导入仅写入数据资产层并打「潜客」标签；" +
          "正式触达前需确认合法基础（legitimate interest 评估或 consent）并保留退订渠道。",
      },
    });
  });
}
