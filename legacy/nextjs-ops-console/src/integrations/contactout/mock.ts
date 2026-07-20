import type {
  ContactOutProvider,
  ContactOutResult,
  ContactOutSearchRequest,
  NormalizedLead,
} from "./types";

// 占位实现：返回样例潜客（带邮箱/公司/地区），不真实调用 API，也不写库。
// 仅用于未配置 key / 未开启时的安全演示。
export class MockContactOutProvider implements ContactOutProvider {
  readonly name = "contactout-mock";

  async search(req: ContactOutSearchRequest): Promise<ContactOutResult> {
    const leads: NormalizedLead[] = [
      {
        linkedinUrl: "https://linkedin.com/in/sample-jane",
        fullName: "Jane Doe",
        email: "jane.doe@example.com",
        phone: "+971500000001",
        companyName: "Example Events Co.",
        companyDomain: "example.com",
        location: "Dubai, United Arab Emirates",
        country: "United Arab Emirates",
      },
      {
        linkedinUrl: "https://linkedin.com/in/sample-john",
        fullName: "John Smith",
        email: "john.smith@example.com",
        phone: "+6588000001",
        companyName: "Acme Pte Ltd",
        companyDomain: "acme.com",
        location: "Singapore",
        country: "Singapore",
      },
    ];
    console.info(`[contactout:mock] returned ${leads.length} leads (mock, not written to DB)`);
    return {
      provider: "contactout-mock",
      leads,
      totalResults: leads.length,
      note: "[mock] 返回样例潜客（未写入数据库）。配置 CONTACTOUT_API_KEY 并开启 CONTACTOUT_ENABLED 后才会真实拉取并写入。",
    };
  }
}
