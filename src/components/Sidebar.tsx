"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV: { href: string; label: string }[] = [
  { href: "/", label: "Dashboard" },
  { href: "/contacts", label: "Contacts" },
  { href: "/tags", label: "Tags" },
  { href: "/segments", label: "Segments" },
  { href: "/templates", label: "Templates" },
  { href: "/campaigns", label: "Campaigns" },
  { href: "/workflows", label: "Workflows" },
  { href: "/events", label: "Events" },
  { href: "/reports", label: "Reports" },
  { href: "/ai", label: "AI Assistant" },
  { href: "/settings", label: "Settings" },
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
        background: "#fff",
      }}
    >
      <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 20, color: "var(--brand)" }}>
        🚀 CMS Marketing
      </div>
      <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {NAV.map((n) => {
          const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
          return (
            <Link
              key={n.href}
              href={n.href}
              style={{
                padding: "8px 10px",
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
      </nav>
    </aside>
  );
}
