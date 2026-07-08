import { env } from "@/lib/env";
import type { EmailProvider } from "./types";
import { MockEmailProvider } from "./mock";
import { SmtpEmailProvider } from "./smtp";
import { SesEmailProvider } from "./ses";
import { SendGridEmailProvider } from "./sendgrid";

// 按环境变量选择 Email provider。新增 provider 时在此处注册即可。
let cached: EmailProvider | null = null;

export function getEmailProvider(): EmailProvider {
  if (cached) return cached;
  switch (env.emailProvider) {
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
