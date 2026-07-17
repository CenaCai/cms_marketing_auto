// =====================================================================
// Seed: 创建默认组织 + 全权限管理员账户
// 运行:  npm run db:seed   (需先 prisma db push 建表)
// =====================================================================
import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";

const prisma = new PrismaClient();

async function main() {
  // 默认组织（固定 id，便于幂等 upsert）
  const org = await prisma.organization.upsert({
    where: { id: "default-org" },
    update: { status: "active" },
    create: { id: "default-org", name: "默认组织", status: "active" },
  });

  // 全权限管理员账户
  const passwordHash = await bcrypt.hash("csts2026", 10);
  const admin = await prisma.user.upsert({
    where: { email: "admin@cms.local" },
    update: { passwordHash, status: "active" },
    create: {
      id: "admin-user",
      name: "Admin",
      username: "admin",
      email: "admin@cms.local",
      passwordHash,
      status: "active",
    },
  });

  await prisma.organizationMember.upsert({
    where: {
      organizationId_userId: { organizationId: org.id, userId: admin.id },
    },
    update: { role: "SUPER_ADMIN", status: "active" },
    create: {
      organizationId: org.id,
      userId: admin.id,
      role: "SUPER_ADMIN",
      status: "active",
    },
  });

  console.log("✅ Seed 完成");
  console.log("   组织: 默认组织 (default-org)");
  console.log("   账号: admin  (email=admin@cms.local)");
  console.log("   密码: csts2026");
  console.log("   角色: SUPER_ADMIN (全权限)");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
