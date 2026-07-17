// 验证扩展后的适配器：邮件资源创建/发送 + Campaign 触发。
import { MauticRestClient } from "../src/integrations/mautic/api";

const BASE = process.env.MAUTIC_BASE || "http://127.0.0.1:8080";
const USER = process.env.MAUTIC_USER || "api";
const SECRET = process.env.MAUTIC_SECRET;
if (!SECRET) {
  console.error("缺少环境变量 MAUTIC_SECRET（在 .env 中配置，勿硬编码密码）");
  process.exit(1);
}

async function main() {
  const c = new MauticRestClient(BASE, USER, SECRET);

  console.log("▶ createEmail");
  const email = await c.createEmail("__verify_email__", "验证主题", "<html><body>hi {{lead.email}}</body></html>");
  console.log("  ✅", email);

  console.log("▶ sendEmailToContact (发给 Mautic 联系人 id=1)");
  await c.sendEmailToContact(email.id, "1");
  console.log("  ✅ 发送请求已提交（mailer_dsn=null 时由 Mautic 丢弃；配真实 SMTP 即真发+追踪）");

  console.log("▶ getEmailStats");
  const stats = await c.getEmailStats(email.id);
  console.log("  ✅ stats 键:", Object.keys(stats).slice(0, 6).join(",") || "(空)");

  console.log("▶ addContactToCampaign (触发已存在的 P4 campaign id=1, 联系人 id=1)");
  await c.addContactToCampaign("1", "1");
  console.log("  ✅ 已把联系人加入 campaign，Mautic 旅程开始执行");

  // 清理邮件资源
  await fetch(`${BASE}/api/emails/${email.id}/delete`, { method: "DELETE", headers: c.headers() });
  console.log("🧹 已删除验证邮件");
}

main()
  .then(() => console.log("\n🎉 邮件/Campaign 适配器方法验证通过"))
  .catch((e) => {
    console.error("\n❌ 验证失败:", e);
    process.exit(1);
  });
