import type { SmsMessage, SmsProvider, SmsResult } from "./types";

// Vonage / Nexmo 接口（占位 / 留接口）
// 落地：npm i @vonage/server-sdk，配置 VONAGE_API_KEY / VONAGE_API_SECRET / VONAGE_FROM
export class VonageSmsProvider implements SmsProvider {
  readonly name = "vonage";
  async send(_msg: SmsMessage): Promise<SmsResult> {
    throw new Error(
      "VonageSmsProvider 尚未实现：请安装 @vonage/server-sdk 并补全 send() 逻辑。",
    );
  }
}
