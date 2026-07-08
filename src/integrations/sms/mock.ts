import type { SmsMessage, SmsProvider, SmsResult } from "./types";

export class MockSmsProvider implements SmsProvider {
  readonly name = "mock";
  async send(msg: SmsMessage): Promise<SmsResult> {
    const messageId = `mock_sms_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    console.info(`[sms:mock] -> to=${msg.to} body="${msg.body.slice(0, 20)}..." messageId=${messageId}`);
    return { provider: "mock", messageId, accepted: true };
  }
}
