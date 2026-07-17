import { NextResponse } from "next/server";
import { ZodError } from "zod";
import { ApiError } from "./errors";

export function ok<T>(data: T, status = 200) {
  return NextResponse.json({ ok: true, data }, { status });
}

export function fail(message: string, status = 400, details?: unknown) {
  return NextResponse.json({ ok: false, message, details }, { status });
}

// Standard handler wrapper: catches ApiError / ZodError and returns JSON.
export async function handle(fn: () => Promise<NextResponse>) {
  try {
    return await fn();
  } catch (e) {
    if (e instanceof ApiError) {
      return fail(e.message, e.status, e.details);
    }
    if (e instanceof ZodError) {
      return fail("参数校验失败", 422, e.flatten());
    }
    console.error("[api-error]", e);
    return fail("服务器内部错误", 500);
  }
}
