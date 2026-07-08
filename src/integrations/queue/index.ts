import { env } from "@/lib/env";
import type { QueueService } from "./types";
import { MemoryQueue } from "./memory";
import { BullMqQueue } from "./bullmq";

let cached: QueueService | null = null;

export function getQueue(): QueueService {
  if (cached) return cached;
  switch (env.queueDriver) {
    case "bullmq":
      cached = new BullMqQueue();
      break;
    case "memory":
    default:
      cached = new MemoryQueue();
      // 开发模式下自动启动内存消费循环
      cached.start();
  }
  return cached;
}

export type { QueueService, JobHandler } from "./types";
