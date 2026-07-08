import type { PutObjectInput, StorageProvider, StorageResult } from "./types";

// 开发/演示用：不真实上传，返回本地占位 URL。
export class MockStorageProvider implements StorageProvider {
  readonly name = "mock";
  async put(input: PutObjectInput): Promise<StorageResult> {
    console.info(`[storage:mock] put key=${input.key} size=${typeof input.body === "string" ? input.body.length : input.body.byteLength}`);
    return { provider: "mock", key: input.key, url: `/mock-storage/${input.key}` };
  }
  getUrl(key: string): string {
    return `/mock-storage/${key}`;
  }
}
