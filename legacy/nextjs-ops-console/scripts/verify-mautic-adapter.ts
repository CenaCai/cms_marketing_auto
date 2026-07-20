// 独立验证脚本：用修正后的 MauticRestClient 跑通真实 Mautic 7 全链路。
// 用法：在 cms_marketing_auto 目录下执行  ./node_modules/.bin/tsx scripts/verify-mautic-adapter.ts
import { MauticRestClient } from "../src/integrations/mautic/api";

const BASE = process.env.MAUTIC_BASE || "http://127.0.0.1:8080";
const USER = process.env.MAUTIC_USER || "api";
const SECRET = process.env.MAUTIC_SECRET;
if (!SECRET) {
  console.error("缺少环境变量 MAUTIC_SECRET（在 .env 中配置，勿硬编码密码）");
  process.exit(1);
}

const u = `__verify_${Date.now()}`;
const tagName = `${u}_tag`;
const segName = `${u}_seg`;
const email = `${u}@example.com`;

async function main() {
  const c = new MauticRestClient(BASE, USER, SECRET!);
  console.log("▶ 连接", BASE, "as", USER);

  const tags = await c.getTags();
  console.log("✅ getTags:", tags.length, "个，示例:", tags.slice(0, 3).map((t) => t.name));

  const seg = await c.getSegments();
  console.log("✅ getSegments:", seg.length, "个，示例:", seg.slice(0, 3).map((s) => s.name));

  const createdTag = await c.createTag(tagName, "#22c55e");
  console.log("✅ createTag:", createdTag);

  const createdSeg = await c.createSegment(segName);
  console.log("✅ createSegment:", createdSeg);

  const createdContact = await c.createContact({
    email,
    firstname: "Verify",
    lastname: "Adapter",
    tags: [tagName],
  });
  console.log("✅ createContact:", createdContact);

  await c.addContactToSegment(createdContact.id, createdSeg.id);
  console.log("✅ addContactToSegment: 已加入分群", createdSeg.id);

  await c.editContact(createdContact.id, { firstname: "Verified" });
  console.log("✅ editContact: PATCH 成功");

  const found = await c.findContactByEmail(email);
  console.log("✅ findContactByEmail:", found ? `找到 id=${found.id}` : "未找到");
}

async function cleanup() {
  const c = new MauticRestClient(BASE, USER, SECRET!);
  try {
    const t = (await c.getTags()).find((x) => x.name === tagName);
    if (t) {
      await c.delete(`/api/tags/${t.id}/delete`);
      console.log("🧹 删除标签", t.id);
    }
    const s = (await c.getSegments()).find((x) => x.name === segName);
    if (s) {
      await c.delete(`/api/segments/${s.id}/delete`);
      console.log("🧹 删除分群", s.id);
    }
    const f = await c.findContactByEmail(email);
    if (f) {
      await c.delete(`/api/contacts/${f.id}/delete`);
      console.log("🧹 删除联系人", f.id);
    }
  } catch (e) {
    console.warn("⚠️ 清理异常（可忽略）:", (e as Error).message);
  }
}

main()
  .then(cleanup)
  .then(() => console.log("\n🎉 Mautic 7 适配器验证通过（含清理）"))
  .catch(async (e) => {
    console.error("\n❌ 验证失败:", e);
    await cleanup();
    process.exit(1);
  });
