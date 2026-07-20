import type {
  ContactOutProvider,
  ContactOutResult,
  ContactOutSearchRequest,
  ContactOutProfile,
  ContactOutSearchResponse,
  NormalizedLead,
} from "./types";

const SEARCH_URL = "https://api.contactout.com/v1/people/search";
const PAGE_SIZE = 25; // ContactOut 固定每页 25
const RATE_LIMIT_MS = 1100; // 60 次/分钟上限 → 留余量，约 1.1s/页
const MAX_LIMIT = 500; // 单次导入上限，避免意外耗尽 credit

// ContactOut 真实 API 客户端（token 头认证 + 翻页 + 限流保护）
export class ContactOutClient implements ContactOutProvider {
  readonly name = "contactout-api";
  private apiKey: string;

  constructor(apiKey: string) {
    this.apiKey = apiKey;
  }

  private async searchPage(page: number, req: ContactOutSearchRequest): Promise<ContactOutSearchResponse> {
    const body = {
      page,
      job_title: req.job_title ?? [],
      company: req.company ?? [],
      location: req.location ?? [],
      name: req.name,
      reveal_info: req.reveal_info ?? true,
      // 显式请求身份/公司/地区字段；contact_info 始终返回
      output_fields: req.output_fields ?? [
        "full_name",
        "name",
        "headline",
        "title",
        "company",
        "location",
        "country",
        "industry",
      ],
    };
    const resp = await fetch(SEARCH_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        token: this.apiKey,
      },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      throw new Error(`ContactOut search 失败 ${resp.status}: ${txt.slice(0, 200)}`);
    }
    return (await resp.json()) as ContactOutSearchResponse;
  }

  async search(req: ContactOutSearchRequest): Promise<ContactOutResult> {
    const limit = Math.max(1, Math.min(req.limit ?? PAGE_SIZE, MAX_LIMIT));
    const maxPages = Math.ceil(limit / PAGE_SIZE);
    const leads: NormalizedLead[] = [];
    let totalResults = 0;

    for (let page = 1; page <= maxPages; page++) {
      const data = await this.searchPage(page, req);
      if (page === 1) totalResults = data?.metadata?.total_results ?? 0;

      const profiles: Record<string, ContactOutProfile> = data?.profiles ?? {};
      for (const [linkedinUrl, p] of Object.entries(profiles)) {
        const norm = normalize(linkedinUrl, p);
        if (norm) leads.push(norm);
        if (leads.length >= limit) break;
      }
      if (leads.length >= limit) break;
      if (page < maxPages) await sleep(RATE_LIMIT_MS);
    }

    return {
      provider: this.name,
      leads: leads.slice(0, limit),
      totalResults,
      note: `ContactOut 实拉 ${leads.length} 条（reveal_info=true 已消耗邮箱/电话 credit）。`,
    };
  }
}

// 展平 + 选取首选联系方式。无邮箱的 profile 无法作为联系人主键，返回 null（由 service 计入跳过）。
function normalize(url: string, p: ContactOutProfile): NormalizedLead | null {
  const info = p.contact_info ?? {};
  const email = info.work_emails?.[0] ?? info.personal_emails?.[0] ?? info.emails?.[0];
  const phone = info.phones?.[0];
  if (!email) return null;
  return {
    linkedinUrl: url,
    fullName: p.full_name ?? p.name,
    email,
    phone,
    companyName: p.company?.name,
    companyDomain: p.company?.domain,
    location: p.location,
    country: p.country,
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
