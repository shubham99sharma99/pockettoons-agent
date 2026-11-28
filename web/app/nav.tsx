"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Ask" },
  { href: "/dashboard", label: "Dashboard" },
  { href: "/metrics", label: "Metrics" },
  { href: "/schema", label: "Schema" },
  { href: "/sql", label: "SQL" },
  { href: "/eval", label: "Eval" },
  { href: "/audit", label: "Audit" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav>
      {links.map((l) => (
        <Link key={l.href} href={l.href} className={path === l.href ? "active" : ""}>{l.label}</Link>
      ))}
    </nav>
  );
}
