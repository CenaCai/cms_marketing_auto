// Lightweight API error type + helper.
export class ApiError extends Error {
  status: number;
  details?: unknown;
  constructor(status: number, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

export const badRequest = (msg: string, details?: unknown) =>
  new ApiError(400, msg, details);
export const unauthorized = (msg = "未认证") => new ApiError(401, msg);
export const forbidden = (msg = "无权限") => new ApiError(403, msg);
export const notFound = (msg = "资源不存在") => new ApiError(404, msg);
export const conflict = (msg = "资源冲突") => new ApiError(409, msg);
