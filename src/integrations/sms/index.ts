import { env } from "@/lib/env";
import type { SmsProvider } from "./types";
import { MockSmsProvider } from "./mock";
import { TwilioSmsProvider } from "./twilio";
import { VonageSmsProvider } from "./vonage";
import { AliyunSmsProvider } from "./aliyun";

let cached: SmsProvider | null = null;

export function getSmsProvider(): SmsProvider {
  if (cached) return cached;
  switch (env.smsProvider) {
    case "twilio":
      cached = new TwilioSmsProvider();
      break;
    case "vonage":
      cached = new VonageSmsProvider();
      break;
    case "aliyun":
      cached = new AliyunSmsProvider();
      break;
    case "mock":
    default:
      cached = new MockSmsProvider();
  }
  return cached;
}

export type { SmsProvider, SmsMessage, SmsResult } from "./types";
