// =====================================================================
// Email integration seam
// ---------------------------------------------------------------------
// 第三方开源依赖：
//   - nodemailer (SMTP, OSS)  —— 已实现，可直接用于任意 SMTP 服务
//   - @aws-sdk/client-ses      —— 接口已留，待安装并填 AWS 凭证
//   - @sendgrid/mail           —— 接口已留，待安装并填 API Key
// 默认 EMAIL_PROVIDER=mock，仅打印日志、不真实发送，便于本地开发。
// =====================================================================

export interface EmailMessage {
  to: string;
  subject: string;
  html?: string;
  text?: string;
  from?: string;
  // 用于打开/点击回执追踪的 messageId（由 provider 返回）
  replyTo?: string;
  tags?: string[];
}

export interface EmailResult {
  provider: string;
  messageId?: string;
  accepted: boolean;
  raw?: unknown; // provider 原始响应，便于排查
}

export interface EmailProvider {
  readonly name: string;
  send(msg: EmailMessage): Promise<EmailResult>;
}
