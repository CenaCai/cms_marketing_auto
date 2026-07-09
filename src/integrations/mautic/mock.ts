import type { MauticClient, MauticContact, MauticSegment, MauticTag } from "./types";

// Mock 客户端：未配置 Mautic 时使用，返回空数据，便于本地联调而不报错。
export class MockMauticClient implements MauticClient {
  readonly name = "mautic-mock";
  async getTags(): Promise<MauticTag[]> {
    return [];
  }
  async createTag(): Promise<MauticTag> {
    return { id: "0", name: "" };
  }
  async getSegments(): Promise<MauticSegment[]> {
    return [];
  }
  async getContacts(): Promise<MauticContact[]> {
    return [];
  }
  async findContactByEmail(): Promise<MauticContact | null> {
    return null;
  }
  async createContact(): Promise<MauticContact> {
    return { id: "0" };
  }
  async editContact(): Promise<void> {
    /* noop */
  }
  async createSegment(): Promise<MauticSegment> {
    return { id: "0", name: "" };
  }
  async addContactToSegment(): Promise<void> {
    /* noop */
  }
}
