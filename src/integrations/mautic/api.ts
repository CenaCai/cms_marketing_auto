import type {
  MauticClient,
  MauticContact,
  MauticSegment,
  MauticTag,
} from "./types";

// Mautic REST API 客户端（Bearer Token）。文档：Mautic /api/* 端点。
// 注意 Mautic 列表接口返回形如 { tags: { "12": {...}, ... } }，需要抽键。
export class MauticRestClient implements MauticClient {
  readonly name = "mautic-rest";
  private baseUrl: string;
  private token: string;

  constructor(baseUrl: string, token: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.token = token;
  }

  private async get<T>(path: string): Promise<any> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      headers: { Authorization: `Bearer ${this.token}` },
    });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      throw new Error(`Mautic GET ${path} 失败 ${resp.status}: ${txt.slice(0, 200)}`);
    }
    return resp.json();
  }

  private async post(path: string, body: Record<string, unknown>): Promise<any> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      throw new Error(`Mautic POST ${path} 失败 ${resp.status}: ${txt.slice(0, 200)}`);
    }
    return resp.json();
  }

  private static dictValues<T>(obj: Record<string, T> | undefined): T[] {
    return obj ? Object.values(obj) : [];
  }

  async getTags(): Promise<MauticTag[]> {
    const data = await this.get<any>("/api/tags");
    return MauticRestClient.dictValues<MauticTag>(data.tags).map((t) => ({
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
    const data = await this.get<any>("/api/segments");
    return MauticRestClient.dictValues<MauticSegment>(data.lists).map((s) => ({
      id: String(s.id),
      name: s.name,
      alias: s.alias,
    }));
  }

  async getContacts(limit = 100): Promise<MauticContact[]> {
    const data = await this.get<any>(`/api/contacts?limit=${limit}`);
    return MauticRestClient.dictValues<any>(data.contacts).map((c) => ({
      id: String(c.id),
      email: c.fields?.core?.email ?? c.email,
      firstname: c.fields?.core?.firstname ?? c.firstname,
      lastname: c.fields?.core?.lastname ?? c.lastname,
      tags: (c.tags ? Object.values(c.tags).map((t: any) => t.tag) : []) as string[],
    }));
  }

  async createContact(c: { email: string; firstname?: string; lastname?: string }): Promise<MauticContact> {
    const data = await this.post("/api/contacts/new", {
      email: c.email,
      firstname: c.firstname,
      lastname: c.lastname,
    });
    const created = MauticRestClient.dictValues<any>(data.contact ?? data.contacts)[0] ?? {};
    return { id: String(created.id), email: c.email };
  }

  async addContactToSegment(contactId: string, segmentId: string): Promise<void> {
    await this.post(`/api/segments/${segmentId}/contact/${contactId}/add`, {});
  }
}
