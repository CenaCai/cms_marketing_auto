import type { JobHandler, QueueService } from "./types";

// ---------------------------------------------------------------------
// BullMQ + Redis 接口（占位 / 留接口）
// 落地步骤：
//   1) npm i bullmq ioredis
//   2) 配置 REDIS_URL
//   3) 生产者：new Queue(name, { connection }) 后 queue.add(type, data, { delay })
//   4) 消费者：单独 worker 进程 new Worker(name, async job => handler(job.data))
//      建议将 worker 放在 scripts/worker.ts，用 `tsx scripts/worker.ts` 启动。
// 当前直接抛错，避免误以为已接入。
// ---------------------------------------------------------------------
export class BullMqQueue implements QueueService {
  readonly name = "bullmq";
  enqueue(): Promise<void> {
    throw new Error(
      "BullMqQueue 尚未实现：请安装 bullmq ioredis 并补全生产者/消费者逻辑。" +
        " 参考 THIRD_PARTY_INTEGRATIONS.md 的 Queue 章节。",
    );
  }
  registerProcessor(): void {
    throw new Error("BullMqQueue 尚未实现：请在独立 worker 进程中注册处理器。");
  }
  start(): void {
    throw new Error("BullMqQueue 尚未实现。");
  }
  async close(): Promise<void> {
    /* noop */
  }
}
