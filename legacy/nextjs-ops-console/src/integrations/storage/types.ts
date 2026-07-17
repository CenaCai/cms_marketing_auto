// =====================================================================
// Storage integration seam (S3-compatible)
// ---------------------------------------------------------------------
// 第三方开源/SDK 依赖（默认 mock）：
//   - @aws-sdk/client-s3 —— AWS S3 或兼容 S3 的对象存储（MinIO、腾讯云 COS、
//    阿里云 OSS、Cloudflare R2 等）。npm i @aws-sdk/client-s3
// 用途：EDM 附件、落地页封面图、导入模板、AI 素材等。
// =====================================================================

export interface PutObjectInput {
  key: string; // 对象键，如 "orgs/{id}/assets/cover.png"
  body: Buffer | Uint8Array | string;
  contentType?: string;
}

export interface StorageResult {
  provider: string;
  key: string;
  url: string; // 可访问 URL（mock 为本地占位路径）
}

export interface StorageProvider {
  readonly name: string;
  put(input: PutObjectInput): Promise<StorageResult>;
  getUrl(key: string): string;
}
