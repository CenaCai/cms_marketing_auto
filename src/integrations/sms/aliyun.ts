import type { SmsMessage, SmsProvider, SmsResult } from "./types";

// 阿里云短信接口（占位 / 留接口）—— 国内短信场景
// 落地：npm i @alicloud/dysmsapi20170525 @alicloud/openapi-client
// 需配置 ALIYUN_SMS_ACCESS_KEY / ALIYUN_SMS_SECRET / ALIYUN_SMS_SIGN_NAME / ALIYUN_SMS_TEMPLATE_CODE
export class AliyunSmsProvider implements SmsProvider {
  readonly name = "aliyun";
  async send(_msg: SmsMessage): Promise<SmsResult> {
    throw new Error(
      "AliyunSmsProvider 尚未实现：请安装 @alicloud/dysmsapi20170525 并补全 send() 逻辑。",
    );
  }
}
