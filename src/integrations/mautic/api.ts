import type {
  MauticClient,
  MauticContact,
  MauticSegment,
  MauticTag,
} from "./types";

// Mautic REST API 客户端（Basic Auth：API 公钥作为 user、私钥作为 secret）。
// 文档端点：联系人 /api/contacts，标签 /api/tags，分群(lead list) /api/lists。
// 注意 Mautic 列表接口返回形如 { tags: { "12": {...}, ... } }，需要抽键。
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

  private static dictValues<T>(obj: Record<string, T> | undefined | null): T[] {
    return obj ? Object.values(obj) : [];
  }

  async getTags(): Promise<MauticTag[]> {
    const data = await this.get<any>("/api/tags");
    return MauticRestClient.dictValues<MauticTag>(data.tags).map((t: any) => ({
      id: String(t.id),
      name: t.name,
      color: t.color,
    }));
  }

  async createTag(name: string, color?: string): Promise<MauticTag> {
    const data = await this.post("/api/tags/new", { name, color });
    const t = MauticRestClient.dictValues<any>(data.tags)[0] ?? {};
    return { id: String(t.id), name: t.tag ?? name, color: t.color };
  }

  async getSegments(): Promise<MauticSegment[]> {
    const data = await this.get<any>("/api/lists");
    return MauticRestClient.dictValues<MauticSegment>(data.lists).map((s: any) => ({
      id: String(s.id),
      name: s.name,
      alias: s.alias,
    }));
  }

  async createSegment(name: string): Promise<MauticSegment> {
    const data = await this.post("/api/lists", { name });
    const s = MauticRestClient.dictValues<any>(data.list ?? data.lists)[0] ?? {};
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
    const created = MauticRestClient.dictValues<any>(data.contact ?? data.contacts)[0] ?? {};
    return { id: String(created.id), email: c.email };
  }

  async editContact(id: string, fields: Record<string, unknown>): Promise<void> {
    await this.post(`/api/contacts/${id}/edit`, fields);
  }

  async addContactToSegment(contactId: string, segmentId: string): Promise<void> {
    await this.post(`/api/lists/${segmentId}/contact/${contactId}/add`, {});
  }
}
