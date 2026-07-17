import type { EmailMessage, EmailProvider, EmailResult } from "./types";

// ---------------------------------------------------------------------
// AWS SES 接口（占位 / 留接口）
// 真实落地步骤：
//   1) npm i @aws-sdk/client-ses
//   2) 配置 AWS_REGION / AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
//   3) 实现下方 send()：调用 SendEmailCommand（建议走 RawMessage 以支持 Html）
// 当前直接抛错，避免误以为已接入。
// ---------------------------------------------------------------------
export class SesEmailProvider implements EmailProvider {
  readonly name = "ses";
  async send(_msg: EmailMessage): Promise<EmailResult> {
    throw new Error(
      "SesEmailProvider 尚未实现：请安装 @aws-sdk/client-ses 并补全 send() 逻辑。" +
        " 参考 THIRD_PARTY_INTEGRATIONS.md 的 Email 章节。",
    );
  }
}
