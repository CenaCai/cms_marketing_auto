import type { EmailMessage, EmailProvider, EmailResult } from "./types";

// 开发/演示用：不真实发送，仅打印日志并返回虚拟 messageId。
export class MockEmailProvider implements EmailProvider {
  readonly name = "mock";
  async send(msg: EmailMessage): Promise<EmailResult> {
    const messageId = `mock_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    console.info(
      `[email:mock] -> to=${msg.to} subject="${msg.subject}" messageId=${messageId}`,
    );
    return { provider: "mock", messageId, accepted: true };
  }
}
