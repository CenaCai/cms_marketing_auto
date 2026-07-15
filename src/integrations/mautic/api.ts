import type {
  MauticClient,
  MauticContact,
  MauticSegment,
  MauticTag,
} from "./types";

// Mautic REST API 客户端（Basic Auth：用 Mautic 用户登录账号作为 user、登录密码作为 secret）。
// 已按 Mautic 7 实际端点/字段校准（2026-07-13 实测）：
//   标签  GET /api/tags            POST /api/tags/new  body { tag, color }   返回 { tag:{id,tag} }
//   分群  GET /api/segments         POST /api/segments/new body { name }     返回 { list:{id,name} }
//   联系人 POST /api/contacts/new   PATCH /api/contacts/{id}/edit   DELETE /api/contacts/{id}/delete
//   加人  POST /api/segments/{sid}/contact/{cid}/add
// 注意：Mautic 7 用 HTTP 动词路由（编辑=PATCH、删除=DELETE），且列表返回形如 { tags:{ "12":{...} } } 需抽键。
export class MauticRestClient implements MauticClient {
  readonly name = "mautic-rest";
  private baseUrl: string;
  private auth: string;

  constructor(baseUrl: string, user: string, secret: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.auth = "Basic " + Buffer.from(`${user}:${secret}`).toString("base64");
  }

  private headers(extra?: Record<string, string>) {
    return { Authorization: this.auth, ...(extra ?? {}) };
  }

  private async get<T = any>(path: string): Promise<any> {
    const resp = await fetch(`${this.baseUrl}${path}`, { headers: this.headers() });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      throw new Error(`Mautic GET ${path} 失败 ${resp.status}: ${txt.slice(0, 200)}`);
    }
    return resp.json();
  }

  private async post(path: string, body: Record<string, unknown> = {}): Promise<any> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: this.headers({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      throw new Error(`Mautic POST ${path} 失败 ${resp.status}: ${txt.slice(0, 200)}`);
    }
    return resp.json();
  }

  private async patch(path: string, body: Record<string, unknown> = {}): Promise<any> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: "PATCH",
      headers: this.headers({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      throw new Error(`Mautic PATCH ${path} 失败 ${resp.status}: ${txt.slice(0, 200)}`);
    }
    return resp.json();
  }

  private static dictValues<T>(obj: Record<string, T> | undefined | null): T[] {
    return obj ? Object.values(obj) : [];
  }

  async getTags(): Promise<MauticTag[]> {
    const data = await this.get<any>("/api/tags");
    return MauticRestClient.dictValues<MauticTag>(data.tags).map((t: any) => ({
      id: String(t.id),
      name: t.tag,
      color: t.color,
    }));
  }

  async createTag(name: string, color?: string): Promise<MauticTag> {
    const data = await this.post("/api/tags/new", { tag: name, color });
    const t = data.tag ?? {};
    return { id: String(t.id), name: t.tag ?? name, color: t.color };
  }

  async getSegments(): Promise<MauticSegment[]> {
    const data = await this.get<any>("/api/segments");
    return MauticRestClient.dictValues<MauticSegment>(data.lists).map((s: any) => ({
      id: String(s.id),
      name: s.name,
      alias: s.alias,
    }));
  }

  async createSegment(name: string): Promise<MauticSegment> {
    const data = await this.post("/api/segments/new", { name });
    const s = data.list ?? {};
    return { id: String(s.id), name: s.name ?? name };
  }

  async getContacts(limit = 100): Promise<MauticContact[]> {
    const data = await this.get<any>(`/api/contacts?limit=${limit}`);
    return MauticRestClient.dictValues<any>(data.contacts).map((c: any) => ({
      id: String(c.id),
      email: c.fields?.core?.email ?? c.email,
      firstname: c.fields?.core?.firstname ?? c.firstname,
      lastname: c.fields?.core?.lastname ?? c.lastname,
      tags: c.tags ? (Object.values(c.tags).map((t: any) => t.tag) as string[]) : [],
    }));
  }

  async findContactByEmail(email: string): Promise<MauticContact | null> {
    const data = await this.get<any>(`/api/contacts?search=email:${encodeURIComponent(email)}`);
    const list = MauticRestClient.dictValues<any>(data.contacts);
    if (!list.length) return null;
    const c = list[0];
    return { id: String(c.id), email: c.fields?.core?.email ?? c.email };
  }

  async createContact(c: { email: string; firstname?: string; lastname?: string; tags?: string[] }): Promise<MauticContact> {
    const data = await this.post("/api/contacts/new", {
      email: c.email,
      firstname: c.firstname,
      lastname: c.lastname,
      tags: c.tags ?? [],
    });
    const obj: any =
      data.contact ?? (data.contacts ? MauticRestClient.dictValues<any>(data.contacts)[0] : undefined) ?? {};
    return { id: String(obj.id), email: c.email };
  }

  async editContact(id: string, fields: Record<string, unknown>): Promise<void> {
    await this.patch(`/api/contacts/${id}/edit`, fields);
  }

  async addContactToSegment(contactId: string, segmentId: string): Promise<void> {
    await this.post(`/api/segments/${segmentId}/contact/${contactId}/add`, {});
  }

  // ---- 邮件：EDM 资源 + 真实发送（Mautic 引擎负责传输与打开/点击追踪）----
  async createEmail(name: string, subject: string, html: string): Promise<MauticEmail> {
    const data = await this.post("/api/emails/new", {
      name,
      subject,
      customHtml: html,
      emailType: "template",
    });
    const e = data.email ?? {};
    return { id: String(e.id), name: e.name ?? name, subject: e.subject ?? subject };
  }

  async sendEmailToContact(emailId: string, contactId: string): Promise<void> {
    // Mautic 把邮件发给指定联系人；配置真实 mailer_dsn 后即真发，并自动注入打开/点击追踪像素。
    await this.post(`/api/emails/${emailId}/send?id=${encodeURIComponent(contactId)}`, {});
  }

  async getEmailStats(emailId: string): Promise<any> {
    // Mautic 7 无独立 /stats 端点；打开/点击计数在邮件详情里（readCount/hitCount）。
    const data = await this.get<any>(`/api/emails/${emailId}`);
    const e = data.email ?? {};
    return { readCount: e.readCount ?? 0, hitCount: e.hitCount ?? 0 };
  }

  // ---- 可视化 Campaign 旅程：在 Mautic UI 搭建，本系统按 id 触发/监控 ----
  async addContactToCampaign(campaignId: string, contactId: string): Promise<void> {
    await this.post(`/api/campaigns/${campaignId}/contact/${contactId}/add`, {});
  }
}
