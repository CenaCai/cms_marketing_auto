import type { SmsMessage, SmsProvider, SmsResult } from "./types";

// Twilio 接口（占位 / 留接口）
// 落地：npm i twilio，配置 TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER
// 实现：client.messages.create({ to, from, body })
export class TwilioSmsProvider implements SmsProvider {
  readonly name = "twilio";
  async send(_msg: SmsMessage): Promise<SmsResult> {
    throw new Error(
      "TwilioSmsProvider 尚未实现：请安装 twilio 并补全 send() 逻辑。" +
        " 参考 THIRD_PARTY_INTEGRATIONS.md 的 SMS 章节。",
    );
  }
}
