import nodemailer from "nodemailer";
import type { EmailMessage, EmailProvider, EmailResult } from "./types";
import { getEmailConfig } from "@/lib/email-config";

// 真实实现（开源）：使用 nodemailer 通过任意 SMTP 服务器发送。
// 配置来源：后台“设置”页（DB）优先，缺失时回退 .env（SMTP_HOST/PORT/USER/PASS）。
// 可对接 Gmail、Postfix、Mailgun SMTP、Amazon SES SMTP、腾讯云/阿里云邮件推送等。
export class SmtpEmailProvider implements EmailProvider {
  readonly name = "smtp";

  async send(msg: EmailMessage): Promise<EmailResult> {
    const cfg = await getEmailConfig();

    if (!cfg.host) {
      throw new Error(
        "SMTP 未配置：请在后台“设置 → 邮件通道”填写 SMTP_HOST（以及端口/账号/密码），或暂时切换到 mock 模式。",
      );
    }

    const transporter = nodemailer.createTransport({
      host: cfg.host,
      port: cfg.port,
      secure: cfg.secure,
      auth:
        cfg.user && cfg.pass ? { user: cfg.user, pass: cfg.pass } : undefined,
    });

    const info = await transporter.sendMail({
      from: msg.from ?? cfg.from,
      to: msg.to,
      subject: msg.subject,
      html: msg.html,
      text: msg.text,
      replyTo: msg.replyTo,
      headers: msg.tags ? { "X-Mail-Tags": msg.tags.join(",") } : undefined,
    });

    return {
      provider: "smtp",
      messageId: info.messageId,
      accepted: true,
      raw: info,
    };
  }
}
