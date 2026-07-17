import type { JobHandler, QueueService } from "./types";

interface PendingJob {
  type: string;
  data: Record<string, unknown>;
  runAt: number;
}

// 开发用内存队列：进程内单消费者，支持延迟（用于 Workflow Wait 节点）。
// 注意：多实例部署时请用 bullmq 驱动，否则任务会分散在不同进程。
export class MemoryQueue implements QueueService {
  readonly name = "memory";
  private processors = new Map<string, JobHandler>();
  private pending: PendingJob[] = [];
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;

  enqueue(
    type: string,
    data: Record<string, unknown>,
    opts?: { delayMs?: number },
  ): Promise<void> {
    this.pending.push({
      type,
      data,
      runAt: Date.now() + (opts?.delayMs ?? 0),
    });
    this.scheduleTick();
    return Promise.resolve();
  }

  registerProcessor(type: string, handler: JobHandler): void {
    this.processors.set(type, handler);
  }

  start(): void {
    this.running = true;
    this.scheduleTick();
  }

  private scheduleTick() {
    if (this.timer || !this.running) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.tick();
    }, 200);
  }

  private async tick() {
    const now = Date.now();
    const due = this.pending.filter((j) => j.runAt <= now);
    this.pending = this.pending.filter((j) => j.runAt > now);
    for (const job of due) {
      const handler = this.processors.get(job.type);
      if (handler) {
        try {
          await handler(job.data);
        } catch (e) {
          console.error(`[queue:memory] handler error for ${job.type}`, e);
        }
      } else {
        console.warn(`[queue:memory] no processor for ${job.type}, dropping`);
      }
    }
    if (this.running && (this.pending.length > 0 || this.timer === null)) {
      this.scheduleTick();
    }
  }

  async close(): Promise<void> {
    this.running = false;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }
}
