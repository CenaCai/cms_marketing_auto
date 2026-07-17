import { env } from "@/lib/env";
import type { StorageProvider } from "./types";
import { MockStorageProvider } from "./mock";
import { S3StorageProvider } from "./s3";

let cached: StorageProvider | null = null;

export function getStorageProvider(): StorageProvider {
  if (cached) return cached;
  switch (env.storageProvider) {
    case "s3":
      cached = new S3StorageProvider();
      break;
    case "mock":
    default:
      cached = new MockStorageProvider();
  }
  return cached;
}

export type { StorageProvider, PutObjectInput, StorageResult } from "./types";
