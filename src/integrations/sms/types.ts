// =====================================================================
// SMS integration seam
// ---------------------------------------------------------------------
// 第三方开源/SDK 依赖（均留接口，默认 mock）：
//   - twilio        —— 海外短信/WhatsApp，npm i twilio
//   - @vonage/server-sdk —— Vonage/Nexmo，npm i @vonage/server-sdk
//   - 阿里云短信 SDK   —— 国内短信，@alicloud/dysmsapi20170525
//   - 腾讯云短信 SDK   —— 国内短信，tencentcloud-sdk-nodejs-sms
// 默认 SMS_PROVIDER=mock。
// =====================================================================

export interface SmsMessage {
  to: string; // E.164 格式，如 +9715xxxxxxxx
  body: string;
  from?: string;
}

export interface SmsResult {
  provider: string;
  messageId?: string;
  accepted: boolean;
  raw?: unknown;
}

export interface SmsProvider {
  readonly name: string;
  send(msg: SmsMessage): Promise<SmsResult>;
}
