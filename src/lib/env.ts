// Centralised, typed access to environment variables.
// Safe defaults keep the app runnable in `mock` mode without external services.

function str(key: string, fallback = ""): string {
  return process.env[key] ?? fallback;
}

function bool(key: string, fallback = false): boolean {
  const v = process.env[key];
  if (v === undefined) return fallback;
  return v === "true" || v === "1";
}

export const env = {
  jwtSecret: str("JWT_SECRET", "dev-insecure-secret-change-me"),
  jwtExpiresIn: str("JWT_EXPIRES_IN", "7d"),

  emailProvider: str("EMAIL_PROVIDER", "mock"),
  emailFrom: str("EMAIL_FROM", "Marketing <noreply@example.com>"),

  smsProvider: str("SMS_PROVIDER", "mock"),

  storageProvider: str("STORAGE_PROVIDER", "mock"),

  queueDriver: str("QUEUE_DRIVER", "memory"),

  aiProvider: str("AI_PROVIDER", "mock"),

  crawlerEnabled: bool("CRAWLER_ENABLED", false),
  crawlerProvider: str("CRAWLER_PROVIDER", "mock"),
};
