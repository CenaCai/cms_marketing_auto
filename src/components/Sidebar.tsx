"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// 导航按「运营闭环」分组：数据资产 → 营销 → 自动化 → 分析 → 系统
const GROUPS: { title: string; items: { href: string; label: string }[] }[] = [
  {
    title: "数据资产",
    items: [
      { href: "/contacts", label: "联系人" },
      { href: "/contacts/import", label: "导入联系人" },
      { href: "/tags", label: "标签" },
      { href: "/segments", label: "分群" },
      { href: "/query", label: "SQL 精准圈人" },
    ],
  },
  {
    title: "营销",
    items: [
      { href: "/templates", label: "模板 (EDM/SMS)" },
      { href: "/campaigns", label: "活动 Campaign" },
      { href: "/landing-pages", label: "落地页 / H5" },
      { href: "/ai", label: "AI 助手" },
    ],
  },
  {
    title: "自动化",
    items: [
      { href: "/events", label: "事件中心" },
      { href: "/workflows", label: "工作流" },
    ],
  },
  {
    title: "分析",
    items: [{ href: "/reports", label: "报表" }],
  },
    {
      title: "系统",
      items: [
        { href: "/users", label: "账号与权限" },
        { href: "/integrations", label: "集成 (Mautic)" },
        { href: "/settings", label: "设置" },
      ],
    },
];

export default function Sidebar() {
  const pathname = usePathname();
  return (
    <aside
      style={{
        width: 220,
        borderRight: "1px solid var(--border)",
        padding: 16,
        height: "100vh",
        position: "sticky",
        top: 0,
        overflowY: "auto",
        background: "#fff",
      }}
    >
      <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 16, color: "var(--brand)" }}>
        🚀 CMS Marketing
      </div>
      <nav style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Link
          href="/"
          style={{
            padding: "8px 10px",
            borderRadius: 8,
            fontSize: 14,
            textDecoration: "none",
            color: pathname === "/" ? "#fff" : "var(--text)",
            background: pathname === "/" ? "var(--brand)" : "transparent",
          }}
        >
          Dashboard
        </Link>
        {GROUPS.map((g) => (
          <div key={g.title}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: 0.5,
                color: "#9ca3af",
                margin: "0 0 4px 10px",
              }}
            >
              {g.title}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {g.items.map((n) => {
                const active =
                  n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
                return (
                  <Link
                    key={n.href}
                    href={n.href}
                    style={{
                      padding: "7px 10px",
                      borderRadius: 8,
                      fontSize: 14,
                      textDecoration: "none",
                      color: active ? "#fff" : "var(--text)",
                      background: active ? "var(--brand)" : "transparent",
                    }}
                  >
                    {n.label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
    </aside>
  );
}
