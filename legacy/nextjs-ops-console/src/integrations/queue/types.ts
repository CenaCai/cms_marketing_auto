// =====================================================================
// Queue integration seam
// ---------------------------------------------------------------------
// 第三方开源依赖：
//   - bullmq + ioredis (Redis)  —— 生产路径，npm i bullmq ioredis
//   - 内置 in-memory 队列        —— 开发路径（默认），无需 Redis
// 用途：批量发送任务、失败重试、Workflow 延迟节点（Wait）、事件异步处理。
// 默认 QUEUE_DRIVER=memory。
// =====================================================================

export type JobHandler = (data: Record<string, unknown>) => Promise<void>;

export interface QueueService {
  readonly name: string;
  enqueue(
    type: string,
    data: Record<string, unknown>,
    opts?: { delayMs?: number },
  ): Promise<void>;
  // 注册某类 job 的处理函数（仅 in-memory / worker 启动前调用）
  registerProcessor(type: string, handler: JobHandler): void;
  // 启动消费循环（BullMQ 场景由独立 worker 进程负责；此处为内存队列）
  start(): void;
  // 优雅关闭
  close(): Promise<void>;
}
