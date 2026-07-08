import nodemailer from "nodemailer";
import type { EmailMessage, EmailProvider, EmailResult } from "./types";

// 真实实现（开源）：使用 nodemailer 通过任意 SMTP 服务器发送。
// 接入方式：设置 EMAIL_PROVIDER=smtp 并配置 SMTP_HOST/PORT/USER/PASS。
// 可对接 Gmail、Postfix、Mailgun SMTP、Amazon SES SMTP、腾讯云/阿里云邮件推送等。
export class SmtpEmailProvider implements EmailProvider {
  readonly name = "smtp";
  private transporter: nodemailer.Transporter;

  constructor() {
    this.transporter = nodemailer.createTransport({
      host: process.env.SMTP_HOST,
      port: Number(process.env.SMTP_PORT ?? 587),
      secure: process.env.SMTP_SECURE === "true",
      auth:
        process.env.SMTP_USER && process.env.SMTP_PASS
          ? { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS }
          : undefined,
    });
  }

  async send(msg: EmailMessage): Promise<EmailResult> {
    const info = await this.transporter.sendMail({
      from: msg.from ?? process.env.EMAIL_FROM,
      to: msg.to,
      subject: msg.subject,
      html: msg.html,
      text: msg.text,
      replyTo: msg.replyTo,
      headers: msg.tags
        ? { "X-Mail-Tags": msg.tags.join(",") }
        : undefined,
    });
    return {
      provider: "smtp",
      messageId: info.messageId,
      accepted: true,
      raw: info,
    };
  }
}
