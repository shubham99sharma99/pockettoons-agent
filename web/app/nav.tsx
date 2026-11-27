"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Ask" },
  { href: "/metrics", label: "Metrics" },
  { href: "/sql", label: "SQL" },
  { href: "/eval", label: "Eval" },
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
