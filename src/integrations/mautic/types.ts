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
// 待你提供 Mautic Base URL + API Token 即可真实同步。
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

export interface MauticClient {
  readonly name: string;
  getTags(): Promise<MauticTag[]>;
  createTag(name: string, color?: string): Promise<MauticTag>;
  getSegments(): Promise<MauticSegment[]>;
  getContacts(limit?: number): Promise<MauticContact[]>;
  createContact(c: { email: string; firstname?: string; lastname?: string }): Promise<MauticContact>;
  addContactToSegment(contactId: string, segmentId: string): Promise<void>;
}
