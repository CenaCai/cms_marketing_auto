// =====================================================================
// ContactOut 数据源 seam（持牌 B2B 数据源）
// ---------------------------------------------------------------------
// ContactOut 是付费数据源 API（contactout.com），返回数据来自其授权数据库
// （声明 CCPA & GDPR Compliant）。它与「爬虫」有本质区别：我们是在查询一个
// 合法授权的数据接口，而非抓取第三方网站。
//
// ⚠️ 合规边界：即便数据源合法，导入的邮箱/电话仍属第三方来源 PII。
//    写入本系统后须经过人工审核，并在正式触达前确认合法基础
//    （legitimate interest 评估或 consent），保留退订渠道。
//
// 官方 API：POST https://api.contactout.com/v1/people/search
//   认证：请求头  token: <API_KEY>
//   body: job_title[] / company[] / location[] / name / page / reveal_info / output_fields[]
//   返回：status_code + metadata{page,page_size(=25),total_results}
//         + profiles（对象，键为 LinkedIn URL）
//   计费：每返回 1 个 profile 消耗 1 搜索 credit；reveal_info=true 时
//         每个带联系方式的 profile 再消耗 1 邮箱/电话 credit。
//   限流：People Search 60 次/分钟。
// =====================================================================

// 业务侧搜索条件（limit 为想要的总条数，内部按 25/页翻页）
export interface ContactOutSearchRequest {
  job_title?: string[];
  company?: string[];
  location?: string[];
  name?: string;
  page?: number;
  reveal_info?: boolean;
  output_fields?: string[];
  limit?: number;
}

// profiles 对象中，某个 LinkedIn URL 对应的值
export interface ContactOutProfile {
  full_name?: string;
  name?: string;
  headline?: string;
  title?: string;
  company?: { name?: string; domain?: string; url?: string };
  location?: string;
  country?: string;
  industry?: string;
  li_vanity?: string;
  contact_availability?: {
    personal_email?: boolean;
    work_email?: boolean;
    phone?: boolean;
  };
  contact_info?: {
    emails?: string[];
    personal_emails?: string[];
    work_emails?: string[];
    phones?: string[];
  };
}

// 搜索响应（profiles 是对象，键=LinkedIn URL）
export interface ContactOutSearchResponse {
  status_code: number;
  metadata?: { page: number; page_size: number; total_results: number };
  profiles?: Record<string, ContactOutProfile>;
}

// 归一化后的线索（已展平，便于落库）
export interface NormalizedLead {
  linkedinUrl: string;
  fullName?: string;
  email?: string;
  phone?: string;
  companyName?: string;
  companyDomain?: string;
  location?: string;
  country?: string;
}

export interface ContactOutResult {
  provider: string;
  leads: NormalizedLead[];
  totalResults: number;
  note: string;
}

export interface ContactOutProvider {
  readonly name: string;
  search(req: ContactOutSearchRequest): Promise<ContactOutResult>;
}
