import type { EmailMessage, EmailProvider, EmailResult } from "./types";

// ---------------------------------------------------------------------
// SendGrid 接口（占位 / 留接口）
// 真实落地步骤：
//   1) npm i @sendgrid/mail
//   2) 配置 SENDGRID_API_KEY
//   3) 实现下方 send()：sgMail.send({ to, from, subject, html, text })
// ---------------------------------------------------------------------
export class SendGridEmailProvider implements EmailProvider {
  readonly name = "sendgrid";
  async send(_msg: EmailMessage): Promise<EmailResult> {
    throw new Error(
      "SendGridEmailProvider 尚未实现：请安装 @sendgrid/mail 并补全 send() 逻辑。" +
        " 参考 THIRD_PARTY_INTEGRATIONS.md 的 Email 章节。",
    );
  }
}
