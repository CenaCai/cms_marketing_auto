import type { PutObjectInput, StorageProvider, StorageResult } from "./types";

// ---------------------------------------------------------------------
// S3 兼容存储接口（占位 / 留接口）
// 落地：npm i @aws-sdk/client-s3
// 兼容：AWS S3、MinIO、腾讯云 COS、阿里云 OSS、Cloudflare R2。
// 实现 send()：new S3Client({region, endpoint?, credentials}) 后 PutObjectCommand。
// 注意：自建/兼容存储通常需设置 endpoint 与 forcePathStyle=true。
// ---------------------------------------------------------------------
export class S3StorageProvider implements StorageProvider {
  readonly name = "s3";
  async put(_input: PutObjectInput): Promise<StorageResult> {
    throw new Error(
      "S3StorageProvider 尚未实现：请安装 @aws-sdk/client-s3 并补全 put()/getUrl() 逻辑。",
    );
  }
  getUrl(_key: string): string {
    throw new Error("S3StorageProvider 尚未实现。");
  }
}
