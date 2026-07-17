import type { EmailProvider } from "./types";
import { MockEmailProvider } from "./mock";
import { SmtpEmailProvider } from "./smtp";
import { SesEmailProvider } from "./ses";
import { SendGridEmailProvider } from "./sendgrid";

// 发送通道模式：默认取自 EMAIL_PROVIDER 环境变量；后台保存设置时可即时切换。
let mode = (process.env.EMAIL_PROVIDER || "mock").toLowerCase();
let cached: EmailProvider | null = null;

// 后台“设置”页保存 email.provider 后调用，立即生效无需重启。
export function setEmailProviderMode(m: string) {
  mode = (m || "mock").toLowerCase();
  cached = null;
}

// 按当前模式选择 Email provider。新增 provider 时在此处注册即可。
export function getEmailProvider(): EmailProvider {
  if (cached) return cached;
  switch (mode) {
    case "smtp":
      cached = new SmtpEmailProvider();
      break;
    case "ses":
      cached = new SesEmailProvider();
      break;
    case "sendgrid":
      cached = new SendGridEmailProvider();
      break;
    case "mock":
    default:
      cached = new MockEmailProvider();
  }
  return cached;
}

export type { EmailProvider, EmailMessage, EmailResult } from "./types";
