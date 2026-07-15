// =====================================================================
// Mautic 集成适配器（设计对齐 + REST API 同步接口）
// ---------------------------------------------------------------------
// 设计对齐说明（字段映射）：
//   Mautic 概念         → 本系统模型
//   Contact (lead)      → Contact        (email/firstname/lastname ↔ name/email)
//   Tag                 → Tag            (name 对齐；Mautic 支持 color)
//   Segment (leadlist)  → Segment(type=static)  (name 对齐)
// 我们的标签 / 分群 / 联系人数据模型即按上述对齐，便于双向同步。
// 沙箱内不运行 Mautic（PHP），这里提供标准 REST 客户端与 mock，
// 待你提供 Mautic Base URL + API 公钥/私钥即可真实同步。
// =====================================================================

export interface MauticTag {
  id: string;
  name: string;
  color?: string;
}

export interface MauticSegment {
  id: string;
  name: string;
  alias?: string;
}

export interface MauticContact {
  id: string;
  email?: string;
  firstname?: string;
  lastname?: string;
  tags?: string[];
}

export interface MauticEmail {
  id: string;
  name: string;
  subject?: string;
}

export interface MauticClient {
  readonly name: string;
  // 拉取（Mautic → 本系统）
  getTags(): Promise<MauticTag[]>;
  createTag(name: string, color?: string): Promise<MauticTag>;
  getSegments(): Promise<MauticSegment[]>;
  getContacts(limit?: number): Promise<MauticContact[]>;
  // 推送（本系统 → Mautic 执行层）
  findContactByEmail(email: string): Promise<MauticContact | null>;
  createContact(c: { email: string; firstname?: string; lastname?: string; tags?: string[] }): Promise<MauticContact>;
  editContact(id: string, fields: Record<string, unknown>): Promise<void>;
  createSegment(name: string): Promise<MauticSegment>;
  addContactToSegment(contactId: string, segmentId: string): Promise<void>;
  // 邮件（EDM 资源 + 真实发送 + 追踪，交由 Mautic 引擎）
  createEmail(name: string, subject: string, html: string): Promise<MauticEmail>;
  sendEmailToContact(emailId: string, contactId: string): Promise<void>;
  getEmailStats(emailId: string): Promise<any>;
  // 可视化 Campaign 旅程（在 Mautic UI 搭建，本系统触发/监控）
  addContactToCampaign(campaignId: string, contactId: string): Promise<void>;
}
