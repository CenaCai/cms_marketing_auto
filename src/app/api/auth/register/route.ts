import { handle, fail } from "@/lib/response";
import { forbidden } from "@/lib/errors";

// 注册入口已关闭：本系统仅通过 seed 预置 admin 账户，不开放自助注册。
export async function POST() {
  return handle(async () => {
    throw forbidden("注册已关闭");
  });
}
